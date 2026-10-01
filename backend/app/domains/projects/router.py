"""Projects API: need analysis + templates."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ApiError, commit, db_session
from app.catalog import get_catalog, projections
from app.core.config import LLMNotConfigured
from app.core.enums import CategoryKind, Domain, Quality
from app.core.request_id import current as request_id
from app.domains.basket.service import BasketError, load_basket, serialize_basket
from app.domains.catalog.schemas import (
    CategoryOut,
    ComplementaryProduct,
    ComplementaryResponse,
)
from app.domains.projects.models import ProjectAnalysis, ProjectRequirement, ProjectTemplate
from app.domains.projects.schemas import (
    AnalyzeRequest,
    OptimizeProjectRequest,
    ProjectAnalysisOut,
    ProjectAnalyzeResponse,
    ProjectCandidate,
    ProjectConstraints,
    ProjectOptimizeResponse,
    ProjectTemplateOut,
    ReanalyzeRequest,
    RecommendedCategory,
)
from app.domains.projects.service import ProjectEngine, ProjectError, template_out
from app.domains.search.schemas import InterpretedIntent, RequirementSpec
from app.domains.search.service import SearchService
from app.llm import LLMRejected, LLMUnavailable
from app.llm.errors import llm_error

logger = logging.getLogger("home_procurement.projects")

router = APIRouter(prefix="/projects", tags=["projects"])


class _ReplayCandidate:
    """
    A product the model already chose, rebuilt from the catalogue on load.

    The price is read from the file again rather than from the stored snapshot,
    so a replay can never show a price the catalogue no longer has, and the
    product is dropped if it has since left or become unpurchasable.
    """

    __slots__ = ("product", "price", "offer_id", "seller_name", "requirement_role", "complementary_for")

    def __init__(self, product, *, price: int, offer_id, seller_name: str) -> None:
        self.product = product
        self.price = price
        self.offer_id = offer_id
        self.seller_name = seller_name
        self.requirement_role = ""
        self.complementary_for = None


def _reasoning_status(stored_reasoning: dict) -> str:
    """Read the stored outcome of the reasoning step, for the response."""
    if not stored_reasoning:
        return "not_needed"
    return stored_reasoning.get("status") or "not_needed"


def _available_categories(categories: list[RecommendedCategory]) -> list["CategoryOut"]:
    """The catalogue subcategories this project matched, in order, deduplicated."""
    out: list["CategoryOut"] = []
    for entry in categories:
        if not entry.in_catalog:
            continue
        if any(existing.slug == entry.category.slug for existing in out):
            continue
        out.append(entry.category)
    return out


def _domain_of(index, subcategory: str | None) -> Domain:
    """The top-level domain a catalogue subcategory belongs to."""
    top = index.top_category_of(subcategory) if subcategory else None
    try:
        return Domain(top) if top else Domain.BATHROOM
    except ValueError:
        return Domain.BATHROOM


@router.get(
    "/templates",
    response_model=list[ProjectTemplateOut],
    summary="قالب‌های پروژهٔ موجود ( bathroom / kitchen )",
    description=(
        "These are **presets**, not requirements. A natural-language project's needs "
        "come from the interpreter, and a project with no matching template here is "
        "an ordinary project. This endpoint remains for admin and preset tooling."
    ),
)
def templates(
    domain: Domain | None = None, session: Session = Depends(db_session)
) -> list[ProjectTemplateOut]:
    stmt = select(ProjectTemplate).where(ProjectTemplate.is_active.is_(True))
    if domain:
        stmt = stmt.where(ProjectTemplate.domain == domain)
    rows = list(session.scalars(stmt.order_by(ProjectTemplate.slug)).all())
    out: list[ProjectTemplateOut] = []
    for template in rows:
        count = len(
            list(
                session.scalars(
                    select(ProjectRequirement).where(ProjectRequirement.template_id == template.id)
                ).all()
            )
        )
        out.append(template_out(template, count))
    return out


@router.post(
    "/analyze",
    response_model=ProjectAnalyzeResponse,
    summary="تحلیل نیاز/پروژه و ساخت فهرست پیشنهادی",
    description=(
        "نیت کاربر تفسیر می‌شود، الزامات (متراژ، کیفیت، بودجه) استخراج می‌شود، "
        "قواعد قالب پروژه اجرا می‌شود و فهرست پیشنهادی به همراه برآورد هزینه ساخته می‌شود."
    ),
)
async def analyze(
    payload: AnalyzeRequest, session: Session = Depends(db_session)
) -> ProjectAnalyzeResponse:
    # Whether the model was asked, or an existing interpretation reused, is the
    # thing most worth knowing about this endpoint: two inferences for one user
    # query is the bug this arrangement exists to prevent.
    reused = payload.interpretation is not None
    logger.info(
        "project.analyze request_id=%s llm_called=%s interpretation_reused=%s",
        request_id(),
        not reused,
        reused,
    )
    engine = ProjectEngine(SearchService())
    try:
        response = await engine.analyze(session, payload, reused=reused)
    except ProjectError as exc:
        session.rollback()
        raise ApiError(exc.message, exc.status_code) from exc
    except (LLMNotConfigured, LLMRejected, LLMUnavailable, ValidationError) as exc:
        # only reached when no interpretation was supplied, so the model was
        # needed. A model that is down is not an internal error.
        session.rollback()
        raise llm_error(exc) from exc
    commit(session)
    return response


@router.get(
    "/{analysis_id}",
    response_model=ProjectAnalysisOut,
    summary="نتیجهٔ تحلیل پروژهٔ ذخیره‌شده",
)
def analysis_detail(
    analysis_id: UUID, session: Session = Depends(db_session)
) -> ProjectAnalysisOut:
    analysis = session.scalar(select(ProjectAnalysis).where(ProjectAnalysis.id == analysis_id))
    if analysis is None:
        raise ApiError("تحلیل پروژه پیدا نشد.", 404)

    # A read. The stored analysis is rendered as it stands and never written to;
    # recalculation is the POST endpoint's job, and it is the only place that
    # takes new constraints.
    return _to_out(analysis, session)


@router.post(
    "/{analysis_id}/reanalyze",
    response_model=ProjectAnalyzeResponse,
    summary="تغییر محدودیت‌ها و ارزیابی دوبارهٔ پروژه",
    description="کاربر می‌تواند بودجه، کیفیت، متراژ یا استایل را تغییر دهد و پروژه دوباره ارزیابی شود.",
)
def reanalyze(
    analysis_id: UUID,
    payload: ReanalyzeRequest,
    session: Session = Depends(db_session),
) -> ProjectAnalyzeResponse:
    analysis = session.scalar(select(ProjectAnalysis).where(ProjectAnalysis.id == analysis_id))
    if analysis is None:
        raise ApiError("تحلیل پروژه پیدا نشد.", 404)

    # The stored interpretation already holds the user's intent, room, project
    # type and template, so it is reused as-is: the model is never asked again.
    # What the changed parameters *can* affect — the needs of the project and
    # which products suit them — is worked out again from scratch below.
    intent = InterpretedIntent.model_validate(analysis.intent_payload)
    basket = load_basket(session, analysis.basket_id) if analysis.basket_id else None

    engine = ProjectEngine(SearchService())
    try:
        response = engine.build(
            session,
            intent=intent,
            constraints=payload.constraints,
            query=analysis.original_query,
            reused=True,
            basket=basket,
        )
    except ProjectError as exc:
        session.rollback()
        raise ApiError(exc.message, exc.status_code) from exc

    # The analysis this basket already owns was updated in place by the engine,
    # so the project's identity, its basket and the user's chosen items all
    # survive. Re-render it through the same path the GET uses, so what is
    # returned after a recalculation is what a reload would show.
    stored = session.scalar(
        select(ProjectAnalysis).where(ProjectAnalysis.id == response.analysis.id)
    )
    if stored is not None:
        response.analysis = _to_out(stored, session)
    commit(session)
    return response


def _optimization_proposals(analysis, session: Session, *, apply: bool) -> OptimizationResult:
    """
    Turn the reasoning call's basket actions into explicit proposals.

    Every action was already validated when the answer came back: the item has to
    be in the basket and a replacement has to be one of the alternatives that were
    offered. Prices are read from the catalogue again here, so the saving is the
    backend's arithmetic and not the model's.

    ``remove`` is only ever reported. A product the user chose is not dropped
    because a model said so, and nothing is added: a proposal that is not applied
    leaves the basket exactly as it was.
    """
    from app.core.text import format_toman
    from app.domains.basket.optimizer import Swap, _apply_swaps, _basket_intent
    from app.domains.basket.schemas import OptimizationChange, OptimizationResult

    index = get_catalog()
    basket = load_basket(session, analysis.basket_id) if analysis.basket_id else None
    actions = (analysis.reasoning or {}).get("basket_actions") or []
    intent = _basket_intent(basket) if basket is not None else None

    changes: list[OptimizationChange] = []
    notes: list[str] = []
    swaps: list = []
    total = 0
    target = analysis.budget

    for item in (basket.items if basket is not None else []):
        product = index.get(item.product_id)
        if product is not None:
            total += int(item.unit_price) * int(item.quantity)

    for action in actions:
        current_id = str(action.get("current_product_id") or "")
        item = next((i for i in (basket.items if basket else []) if str(i.product_id) == current_id), None)
        current = index.get(UUID(current_id)) if current_id else None
        if item is None or current is None:
            continue
        kind = action.get("action")
        reason = (action.get("reason") or "").strip()

        if kind == "keep":
            continue
        if kind == "remove":
            notes.append(
                f"پیشنهاد شد «{current.name}» از فهرست انتخاب‌ها برداشته شود: {reason} — "
                "تا تأیید شما در فهرست شما می‌ماند."
            )
            continue
        if kind != "replace":
            continue
        replacement_id = str(action.get("replacement_product_id") or "")
        replacement = index.get(UUID(replacement_id)) if replacement_id else None
        if replacement is None or not replacement.purchasable_offers:
            notes.append(f"جایگزین پیشنهادی برای «{current.name}» دیگر در دسترس نیست.")
            continue
        offer = replacement.purchasable_offers[0]
        to_price = int(offer.price)
        quantity = int(item.quantity)
        saving = (int(item.unit_price) - to_price) * quantity
        if saving <= 0:
            notes.append(
                f"«{replacement.name}» ارزان‌تر از «{current.name}» نیست؛ فهرست انتخاب‌ها دست‌نخورده ماند."
            )
            continue

        changes.append(
            OptimizationChange(
                item=item.role,
                item_id=item.id,
                role=item.role,
                from_product=current.name,
                from_product_id=current.id,
                to_product=replacement.name,
                to_product_id=replacement.id,
                from_price=int(item.unit_price),
                to_price=to_price,
                quantity=quantity,
                saving=saving,
                reason=reason or "همان نیاز با هزینهٔ کمتر",
                quality_from="—",
                quality_to="—",
            )
        )
        swaps.append(
            Swap(
                item_id=item.id,
                role=item.role,
                from_product=current.name,
                from_product_id=current.id,
                to_product=replacement.name,
                to_product_id=replacement.id,
                from_price=int(item.unit_price),
                to_price=to_price,
                quantity=quantity,
            )
        )

    saved = sum(c.saving for c in changes)
    optimized_total = total - saved
    if apply and swaps:
        _apply_swaps(session, basket, swaps)
    elif target is not None:
        basket.target_budget = target

    return OptimizationResult(
        original_total=total,
        target_budget=target,
        can_optimize=bool(changes),
        over_budget=bool(target is not None and total > target),
        optimized_total=optimized_total,
        saved=saved,
        within_budget=target is None or optimized_total <= target,
        unfilled_gap=max(0, optimized_total - target) if target is not None else 0,
        changes=changes,
        applied=bool(apply and swaps),
        basket=serialize_basket(session, basket) if basket is not None else None,
        explanation=(
            f"{len(changes)} تغییر پیشنهاد شد و "
            f"{format_toman(saved)} کاهش هزینه دارد؛ تا تأیید شما انتخاب‌هایتان تغییری نمی‌کند."
            if changes
            else (
                "تغییر معتبری پیدا نشد؛ فهرست انتخاب‌های شما دست‌نخورده ماند."
                if total
                else "هنوز محصولی در فهرست انتخاب‌ها نیست؛ از پیشنهادهای پروژه چیزی اضافه کنید."
            )
        ),
        trade_offs=notes or ["قیمت‌ها از کاتالوگ خوانده شده‌اند و پیشنهاد جایگزینی معتبر بود."],
    )


@router.post(
    "/{analysis_id}/optimize",
    response_model=ProjectOptimizeResponse,
    summary="بهینه‌سازی پروژه با مقادیر فعلی فرم",
    description=(
        "یک عمل واحد: پروژه و فهرست انتخاب‌های فعلی با هم و با مقادیری که همین حالا در فرم "
        "وارد شده‌اند دوباره ارزیابی می‌شوند. محدودیت‌ها از تفسیر قبلی می‌آیند و "
        "مدل دوباره خوانده نمی‌شود."
    ),
)
def optimize_project(
    analysis_id: UUID,
    payload: OptimizeProjectRequest,
    apply: bool = Query(default=False),
    session: Session = Depends(db_session),
) -> ProjectOptimizeResponse:
    """
    Re-evaluate the project and its current basket in one step.

    This is the one action the interface offers. The requirements and the
    recommendations are worked out again from the values the user has entered,
    and the basket proposals come out of the *same* model call — the project
    reasoning is handed the basket, so there is nothing to ask twice.

    Nothing is written to the basket here. The actions are returned as proposals
    and applied only when the user asks for it with ``apply=true``.
    """
    analysis = session.scalar(select(ProjectAnalysis).where(ProjectAnalysis.id == analysis_id))
    if analysis is None:
        raise ApiError("تحلیل پروژه پیدا نشد.", 404)

    # The project's own interpretation: the room, the kind of work and the
    # template. The model is not asked again.
    intent = InterpretedIntent.model_validate(analysis.intent_payload)
    basket = load_basket(session, analysis.basket_id) if analysis.basket_id else None

    constraints = ProjectConstraints(
        area_m2=payload.area_m2,
        quality=payload.quality,
        budget=payload.budget,
        style=payload.style,
    )

    engine = ProjectEngine(SearchService())
    try:
        response = engine.build(
            session,
            intent=intent,
            constraints=constraints,
            query=analysis.original_query,
            reused=True,
            basket=basket,
            # the form states the complete current state, so a cleared value is
            # cleared and must not fall back to what the user entered before
            resolved=True,
        )
    except ProjectError as exc:
        session.rollback()
        raise ApiError(exc.message, exc.status_code) from exc

    stored = session.scalar(
        select(ProjectAnalysis).where(ProjectAnalysis.id == response.analysis.id)
    )
    view = _to_out(stored, session) if stored is not None else response.analysis
    proposals = _optimization_proposals(stored, session, apply=apply)

    commit(session)
    return ProjectOptimizeResponse(
        analysis=view,
        basket=response.basket,
        budget_status=response.budget_status,
        optimization=proposals,
    )


@router.get(
    "/{analysis_id}/complementary",
    response_model=ComplementaryResponse,
    summary="محصولات مکملِ کل پروژه",
)
def project_complementary(
    analysis_id: UUID,
    limit: int = Query(default=6, ge=0, le=24),
    session: Session = Depends(db_session),
) -> ComplementaryResponse:
    """
    Products that complete the project as a whole, in at most one model call.

    The pool is the chosen items' own declared complements, room-scoped, and the
    ids the model returns are validated against it. Nothing here is added to the
    basket: it is advice, and the project page keeps it separate from the
    requirements and the recommendations for that reason.
    """
    from app.catalog.complementary import (
        ProjectComplementaryResult,
        project_complementary_products,
    )

    analysis = session.scalar(select(ProjectAnalysis).where(ProjectAnalysis.id == analysis_id))
    if analysis is None:
        raise ApiError("تحلیل پروژه پیدا نشد.", 404)

    index = get_catalog()
    chosen: list = []
    selections = (analysis.reasoning or {}).get("selections") or {}
    for recorded in selections.values():
        product_id = (recorded or {}).get("product_id")
        if not product_id:
            continue
        product = index.get(UUID(str(product_id)))
        if product is not None and product.id not in {p.id for p in chosen}:
            chosen.append(product)
    if not chosen and analysis.basket_id:
        # what the user actually chose
        for item in load_basket(session, analysis.basket_id).items:
            product = index.get(item.product_id)
            if product is not None and product.id not in {p.id for p in chosen}:
                chosen.append(product)
    if not chosen:
        # nothing chosen yet: the project's own recommendations are what the
        # result was built around, and they are what a complement would complete
        for candidate in _to_out(analysis, session).candidates:
            product = index.get(candidate.product.id)
            if product is not None and product.id not in {p.id for p in chosen}:
                chosen.append(product)

    result = project_complementary_products(index, chosen)
    # the requested limit bounds what the client asked for; the pool itself is
    # bounded by the configured candidate limit inside the callee
    result = ProjectComplementaryResult(
        items=result.items[:limit],
        available=result.available,
        note=result.note,
        candidate_count=result.candidate_count,
        discarded_ids=result.discarded_ids,
    )
    return ComplementaryResponse(
        items=[
            ComplementaryProduct(
                id=str(c.product.id),
                name=c.product.name,
                image_url=c.product.image_url,
                category=c.product.subcategory,
                category_name=c.product.subcategory_name,
                price=int(c.product.min_price),
                reason=c.reason,
                source=c.source,
            )
            for c in result.items
        ],
        llm_available=result.available,
        candidate_count=result.candidate_count,
        note=result.note,
        discarded_ids=list(result.discarded_ids),
    )


def _replay_complements(analysis, stored_reasoning, index, plan_by_role):
    """
    The complementary advice the model gave, re-checked against the catalogue.

    Ids only, exactly like the selections: the product is looked up now, and
    dropped if it has left the catalogue or stopped being purchasable, so a
    reload can never show something we could not sell today.
    """
    out: list[ProjectCandidate] = []
    for product_id in (stored_reasoning.get("complementary") or []):
        product = index.get(UUID(str(product_id)))
        if product is None or not product.purchasable_offers:
            continue
        offer = product.purchasable_offers[0]
        out.append(
            ProjectCandidate(
                role="complement",
                label=product.name[:80],
                quantity=1,
                unit="عدد",
                product=to_product_out(product, offer_limit=2),
                offer=offer_out(offer),
                unit_price=int(offer.price),
                line_total=int(offer.price),
                seller_name=offer.seller.name,
                reason="مکملِ نیاز پروژه بر پایهٔ رابطهٔ اعلام‌شده در کاتالوگ.",
                quality=None,
                quality_fa=None,
            )
        )
    return out


def _to_out(analysis: ProjectAnalysis, session: Session) -> ProjectAnalysisOut:
    """Rebuild the API view of a stored analysis from its basket (source of truth)."""
    from app.core.enums import QUALITY_FA
    from app.domains.basket.service import BasketError as _BasketError
    from app.domains.projects.needs import ProjectNeed
    from app.domains.projects.service import (
        ProjectEngine,
        recommend_for_requirement,
    )

    if not analysis.basket_id:
        raise ApiError("فهرست انتخاب‌های این تحلیل در دسترس نیست.", 404)
    try:
        basket = load_basket(session, analysis.basket_id)
    except _BasketError as exc:  # pragma: no cover - defensive
        raise ApiError(exc.message, 404) from exc
    basket_out = serialize_basket(session, basket)

    intent = InterpretedIntent.model_validate(analysis.intent_payload)
    stored = RequirementSpec.model_validate(analysis.requirements or {})
    requirements = ProjectConstraints(
        area_m2=stored.area_m2,
        quality=stored.quality,
        style=stored.style,
        budget=stored.budget,
        priorities=stored.priorities,
    )

    index = get_catalog()

    # The project's requirements, replayed from what was stored. They used to be
    # re-read from the template here, which meant a saved project showed whatever
    # the rulebook said rather than what the user asked for — and a project with
    # no matching rulebook could not be shown at all. `ProjectNeed`s are a plain
    # frozen dataclass, so the snapshot reconstructs exactly what was resolved.
    needs = [
        ProjectNeed(
            role=str(row.get("role") or f"req_{position}"),
            description=str(row.get("description") or ""),
            terms=tuple(row.get("terms") or ()),
            slugs=tuple(row.get("slugs") or ()),
            quantity=int(row.get("quantity") or 1),
            required=bool(row.get("required", True)),
            quality_min=Quality(row.get("quality_min") or Quality.LOW.value),
        )
        for position, row in enumerate(analysis.needs or [], start=1)
    ]

    # A project's department is read off the catalogue subcategory its needs
    # resolved to, or taken from the preset when there is one. It was never a
    # column, because it is derived from what the project actually needs.
    domain = (
        analysis.template.domain
        if analysis.template is not None
        else ProjectEngine._role_domain(
            index, needs[0].slug if needs else None, Domain.FURNITURE
        )
    )

    # The model's validated choices are replayed, not re-derived: re-running the
    # reasoning here would cost a call on every page load and could disagree with
    # the analysis the user was shown. Anything the model did not choose falls
    # back to the cheapest suitable candidate, exactly as the engine would.
    stored_reasoning = analysis.reasoning or {}
    stored_selections = stored_reasoning.get("selections") or {}

    categories_out: list[RecommendedCategory] = []
    candidates: list[ProjectCandidate] = []
    for need in needs:
        recorded = stored_selections.get(need.role) or {}
        replayed = None
        if recorded.get("product_id"):
            product = index.get(UUID(str(recorded["product_id"])))
            offers = product.purchasable_offers if product else ()
            if product is not None and offers:
                replayed = _ReplayCandidate(
                    product=product,
                    price=int(offers[0].price),
                    offer_id=offers[0].id,
                    seller_name=offers[0].seller.name,
                )
        category, candidate = recommend_for_requirement(
            index,
            need,
            intent=intent,
            domain=domain,
            area=float(analysis.area_m2) if analysis.area_m2 else None,
            quality=analysis.quality,
            selected=replayed,
            selected_reason=recorded.get("reason") or None,
        )
        categories_out.append(category)
        if candidate is not None:
            candidates.append(candidate)

    estimated_total = sum(candidate.line_total for candidate in candidates)

    return ProjectAnalysisOut(
        id=analysis.id,
        template_slug=analysis.template.slug if analysis.template is not None else None,
        title=analysis.title_fa,
        domain=domain,
        project_type=analysis.template.project_type if analysis.template else None,
        area_m2=float(analysis.area_m2) if analysis.area_m2 else None,
        quality=analysis.quality,
        quality_fa=QUALITY_FA[analysis.quality],
        style=analysis.style,
        budget=analysis.budget,
        requirements=requirements,
        estimated_total=estimated_total,
        confidence=float(analysis.confidence),
        interpreter=analysis.interpreter,
        interpretation=intent,
        reasoning_status=_reasoning_status(stored_reasoning),
        categories=categories_out,
        available_categories=_available_categories(categories_out),
        candidates=candidates,
        missing_categories=[category for category in categories_out if not category.in_catalog],
        basket_id=basket.id,
        # The engine's own explanations — including the deterministic budget
        # verdict — are stored with the analysis and replayed here, so a reloaded
        # or recalculated project explains itself the same way the original did.
        explanations=list(stored_reasoning.get("explanations") or intent.explanations),
        created_at=analysis.created_at.isoformat(),
    )
