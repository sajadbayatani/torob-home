"""Project (need) engine: interpreted intent + template rules -> a basket.

Division of labour, and it matters:

* The **interpreter** (an LLM) decides *what the user wants*: a domain, a project
  type, a room, and which catalogue subcategories the need maps to. It never
  names a product.
* The **template** in the database decides the arithmetic: which roles a job of
  this kind has, how many of each, and the quality floor.
* The **catalogue file** decides what actually exists. A role whose
  subcategory is not in ``products.json`` is reported as missing, with fixed
  wording, and never matched to something else that merely sounds similar.

No arithmetic here involves the LLM.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.projections import offer_out, to_product_out
from app.catalog.selection import (
    RoomScope,
    build_room_scope,
    is_eligible,
    select_candidates,
)
from app.catalog.store import CatalogProduct, get_catalog, subcategory_label
from app.core.enums import (
    QUALITY_FA,
    BasketKind,
    CategoryKind,
    DataSource,
    Domain,
    Quality,
    domain_from,
)
from app.core.text import fa_number, format_toman
from app.domains.basket.models import Basket
from app.domains.basket.service import serialize_basket
from app.domains.catalog.schemas import CategoryOut
from app.domains.projects.models import ProjectAnalysis, ProjectTemplate
from app.domains.projects.needs import resolve_needs
from app.domains.projects.reasoning import (
    CANDIDATES_PER_REQUIREMENT,
    build_candidate_set,
    reason_project,
)
from app.domains.projects.schemas import (
    UNAVAILABLE_NOT_STOCKED,
    UNAVAILABLE_NOT_SUITABLE,
    UNAVAILABLE_REASON_NOT_STOCKED,
    UNAVAILABLE_REASON_NOT_SUITABLE,
    AnalyzeRequest,
    ProjectAnalysisOut,
    ProjectAnalyzeResponse,
    ProjectCandidate,
    ProjectConstraints,
    ProjectTemplateOut,
    RecommendedCategory,
)
from app.domains.search.schemas import InterpretedIntent
from app.domains.search.service import SearchService

logger = logging.getLogger("home_procurement.projects")

#: The quality floor applied when the user stated none.
#:
#: It has to exist — the column is NOT NULL and every recommendation is judged
#: against a floor — so the question is only which value is the least opinionated
#: one. MEDIUM is the middle of the scale: it excludes nothing and promises
#: nothing. It is deliberately *not* a template's `default_quality`, because one
#: project's default is not an answer to a question about a different project,
#: and inheriting it is how a hall became 80 m² of medium-quality refrigerator.
DEFAULT_QUALITY = Quality.MEDIUM

ROLE_FA: dict[str, str] = {
    "tiles": "کاشی و سرامیک",
    "install_materials": "مصالح نصب",
    "toilet": "توالت",
    "vanity": "روشویی",
    "faucet": "شیرآلات",
    "mirror": "آینه",
    "shower": "دوش و سر دوش",
    "accessories": "اکسسوری",
    "bathtub": "وان حمام",
    "lighting": "روشنایی",
    "cabinet": "کابینت",
    "counter_top": "اپن",
    "sink": "سینک",
    "cooktop": "اجاق گاز",
    "oven": "فر",
    "hood": "هود",
    "fridge": "یخچال",
    "hardware": "یراق آشپزخانه",
    "appliance": "لوازم برقی",
    "bed": "تخت خواب",
    "wardrobe": "کمد لباس",
    "sofa": "مبل راحتی",
    "desk": "میز",
    "dining_table": "میز ناهارخوری",
    "dining_chair": "صندلی ناهارخوری",
    "decor": "پرده و فرش",
    "refrigerator": "یخچال و فریزر",
    "washing_machine": "ماشین لباسشویی",
    "dishwasher": "ماشین ظرفشویی",
    "vacuum": "جاروبرقی",
    "television": "تلویزیون",
    "microwave": "مایکروویو",
}


class ProjectError(RuntimeError):
    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def role_label(role: str) -> str:
    return ROLE_FA.get(role, role)



def project_scope(index, intent: InterpretedIntent) -> tuple[RoomScope, str | None]:
    """
    The room scope and project type an analysis is to be judged under.

    A room the interpreter placed in the catalogue's own vocabulary wins over the
    user's literal wording, because «پذیرایی» and ``living_room`` share no
    characters and no string rule can connect them — the catalogue simply does
    not use the word. When there is no placed room, the user's words are matched
    against the file's vocabulary as before.
    """
    from app.catalog.selection import scope_for_room_token

    scope = scope_for_room_token(index, intent.room_token)
    if not scope.tokens:
        scope = build_room_scope(index, intent.room)
    return scope, intent.project_type.value if intent.project_type else None


def revalidate_basket(
    session: Session,
    basket: Basket,
    *,
    index,
    scope: RoomScope,
    project_type: str | None,
    area_m2: float | None,
) -> list[str]:
    """
    Re-judge the items the user chose, against the constraints just changed.

    A recalculation must not throw away a deliberate choice, so an item is only
    ever dropped when the new constraints make it unusable rather than merely
    unhelpful: the product left the catalogue, stopped being purchasable, or is
    no longer something this room or this kind of job can take. A merely worse
    or dearer option is left alone and only reported, and a locked item is never
    removed at all. Nothing is added and nothing is swapped for a substitute.
    """
    notes: list[str] = []
    for item in list(basket.items):
        product = index.get(item.product_id)
        if product is None or not is_eligible(
            product, scope=scope, project_type=project_type, area_m2=area_m2
        ):
            reason = (
                "از کاتالوگ خارج شده یا دیگر قابل خرید نیست"
                if product is None or not product.purchasable_offers
                else "برای این اتاق یا این نوع کار دیگر مناسب نیست"
            )
            label = product.name if product is not None else str(item.product_id)
            if item.is_locked:
                notes.append(
                    f"«{label}» قفل شده است؛ با وجود ناسازگاری ({reason}) "
                    "به‌دلیل انتخاب خودتان دست‌نخورده باقی ماند."
                )
                continue
            session.delete(item)
            notes.append(f"«{label}» از لیست انتخاب‌ها حذف شد: {reason}.")
    if basket.target_budget is not None:
        session.flush()
    return notes


def _unplaced_need(need, plan, quantity: int) -> RecommendedCategory:
    """
    A need the project has, with no product beside it because none was chosen.

    Not the same as a need the site does not stock: that one is reported with the
    fixed "not available" wording. This one says the interpreter named the need,
    the catalogue has things for it, and the reasoning did not place any of them
    in *this* space — a different statement, left to the explanation to make.

    The label is the interpreter's own description, because that is what the
    project is about now: there is no rulebook whose name could stand in for it.
    """
    return _category_for(need, quantity, ProjectEngine._role_domain(
        get_catalog(), need.slug, Domain.FURNITURE
    ))


def _category_for(
    need, quantity: int, domain: Domain, *, catalog_match: bool = True
) -> RecommendedCategory:
    """The displayable row for one need, resolved to what the catalogue holds."""
    from app.domains.catalog.schemas import CategoryOut

    index = get_catalog()
    slug = need.slug
    name = subcategory_label(slug) if slug else need.description
    return RecommendedCategory(
        role=need.role,
        label=need.description or name,
        category=CategoryOut(
            id=slug or need.role,
            slug=slug or need.role,
            name=name,
            domain=domain,
            kind=CategoryKind.FIXTURE,
            description_fa=None,
            product_count=len(index.subcategories_of(slug)) if slug else 0,
        ),
        quantity=quantity,
        unit=_unit_of(index, slug),
        is_required=bool(need.required),
        quality_min=need.quality_min,
        reason=need.description,
        project_need=True,
        catalog_match=catalog_match,
        in_catalog=catalog_match,
    )


def _unavailable(
    category: RecommendedCategory,
    *,
    stocked: bool = False,
    not_in_stock: bool = False,
):
    """
    Mark a requirement the catalogue cannot cover, without touching the need.

    ``project_need`` stays True: this row was decided from the project context
    and is a genuine requirement. Only ``catalog_match`` drops, and the fixed
    wording says why. The caller gets no candidate, so nothing unreachable is
    ever put in front of the user as purchasable.
    """
    category.project_need = True
    category.catalog_match = False
    category.in_catalog = False
    if stocked:
        category.note = UNAVAILABLE_NOT_SUITABLE
        category.unavailable_reason = UNAVAILABLE_REASON_NOT_SUITABLE
    else:
        category.note = UNAVAILABLE_NOT_STOCKED
        category.unavailable_reason = UNAVAILABLE_REASON_NOT_STOCKED
    return category


def recommend_for_requirement(
    index,
    need,
    *,
    intent: InterpretedIntent,
    domain: Domain,
    area: float | None,
    quality: Quality,
    plan=None,
    selected=None,
    selected_reason: str | None = None,
):
    """
    One need, and the product chosen for it.

    ``plan`` is the candidate set the backend cleared for this need and
    ``selected`` is the one the model chose from it, already validated. When no
    model answer is supplied — a reload, or a model that did not choose — the
    first candidate is used, which is the cheapest suitable one, so the
    deterministic behaviour is unchanged.

    Returns the need as a displayable category, the recommended item if the
    catalogue has one that belongs, and otherwise None. The catalogue is
    consulted only here, and it can never introduce a need of its own.
    """
    quantity = plan.quantity if plan is not None else need.quantity
    label = need.description
    slug = need.slug
    scope, project_type = project_scope(index, intent)
    category = _category_for(need, quantity, ProjectEngine._role_domain(index, slug, domain))

    # The candidate set is the catalogue boundary: everything in it already
    # suits this room, this kind of job and this space, and can be bought. The
    # model chooses from it; it can never widen it.
    if plan is not None:
        candidates = [candidate.product for candidate in plan.candidates]
    else:
        candidates = select_candidates(
            index, slug, scope=scope, project_type=project_type, area_m2=area
        )[:CANDIDATES_PER_REQUIREMENT]
    if selected is not None:
        # Only honoured if the product is still among the candidates: a choice
        # stored earlier is dropped when the product has since left, stopped
        # being purchasable, or no longer suits this project.
        product = [p for p in candidates if str(p.id) == str(selected.product.id)][:1]
    else:
        product = candidates[:1]
    if not product:
        # Nothing eligible. The need stays a need of the project either way;
        # only our ability to supply it is in question, and the two reasons are
        # reported apart so the wording is never a guess.
        stocked = bool(index.subcategories_of(slug)) if slug else False
        return _unavailable(category, stocked=stocked), None

    chosen = product[0]
    offer = chosen.purchasable_offers[0] if chosen.purchasable_offers else None
    if offer is None:
        # a product with no purchasable offer is not something we can sell
        return _unavailable(category, not_in_stock=True), None

    category.project_need = True
    category.catalog_match = True
    category.in_catalog = True
    category.note = None
    unit_price = int(offer.price)
    candidate = ProjectCandidate(
        role=need.role,
        label=label,
        quantity=quantity,
        unit=category.unit,
        product=to_product_out(chosen, offer_limit=3),
        offer=offer_out(offer),
        unit_price=unit_price,
        line_total=unit_price * quantity,
        seller_name=offer.seller.name,
        # the model's own words when it chose, and the deterministic wording
        # when it did not — never a reason invented on its behalf
        reason=selected_reason or ProjectEngine._item_reason(need, quantity, quality, area),
        # the catalogue states no quality, so none is claimed
        quality=None,
        quality_fa=None,
    )
    return category, candidate


class ProjectEngine:
    def __init__(self, search_service: SearchService | None = None) -> None:
        self._search = search_service or SearchService()

    # ------------------------------------------------------------------ #
    async def analyze(
        self, session: Session, request: AnalyzeRequest, *, reused: bool = False
    ) -> ProjectAnalyzeResponse:
        """
        Build a project basket from a request.

        If the request already carries an interpretation, it is used as-is and
        the model is not consulted again. One user query costs one inference:
        the caller interprets once, then hands the result here.
        """
        intent = request.interpretation
        if intent is None:
            intent = await self._search.interpret(request.query, session)
        else:
            # a caller-supplied interpretation still goes through enrichment, so a
            # slug or brand it names is resolved against the catalogue, never
            # trusted because it arrived in a request body
            intent = self._search.enrich(intent, session)
        return self.build(
            session,
            intent=intent,
            constraints=request.constraints,
            query=request.query,
            reused=reused or request.interpretation is not None,
        )

    # ------------------------------------------------------------------ #
    def build(
        self,
        session: Session,
        *,
        intent: InterpretedIntent,
        constraints: ProjectConstraints | None = None,
        query: str = "",
        reused: bool = False,
        basket: Basket | None = None,
        resolved: bool = False,
    ) -> ProjectAnalyzeResponse:
        constraints = constraints or ProjectConstraints()
        domain = intent.domain
        if domain is None and constraints.area_m2 and intent.product_query:
            domain = intent.product_query.domain

        # The project's requirements are the interpreter's understanding of the
        # sentence, and nothing here may add to them or substitute for them. A
        # template is an *optional preset* — see `ProjectEngine._find_template`
        # — and a project with no template is an ordinary project, not a refusal:
        # "a gaming corner in my hall" has no rulebook, and inventing one is how
        # a hall once came to ask for a refrigerator.
        template = self._find_template(session, intent)
        if template is not None and domain is None:
            domain = template.domain

        # Two ways to resolve a value, and the difference matters.
        #
        # By default an absent constraint means "not stated here", so the value
        # the interpretation already carries is used. That is right for the first
        # analysis of a query.
        #
        # With ``resolved=True`` the caller is stating the *complete* current
        # constraint set, so an absent value means the user cleared it. Falling
        # back to the interpretation there would resurrect a number the user has
        # just removed — a budget of 30M would come back after being emptied. An
        # absent value then falls to the template's own default, which is a
        # property of the project rather than something the user once typed.
        #
        # A template's `default_area_m2` and `default_quality` are deliberately
        # not consulted. They are one project's opinion about a space the user
        # never described: the appliance rulebook's own default is 80 m², and
        # inheriting it is how a project about a hall came to be 80 m² of
        # medium-quality refrigerator. An area the user did not state stays
        # unknown, and says so on screen.
        #
        # Quality is the one value that cannot stay absent — it is the floor
        # every recommendation is judged against, and the table and the schema
        # both require one. `DEFAULT_QUALITY` is a neutral middle, chosen because
        # it excludes nothing and promises nothing, not because any project
        # asked for it.
        if resolved:
            quality = constraints.quality or DEFAULT_QUALITY
            area = constraints.area_m2
            style = constraints.style
            budget = constraints.budget
        else:
            quality = (
                constraints.quality
                or intent.requirements.quality
                or DEFAULT_QUALITY
            )
            area = constraints.area_m2 or intent.requirements.area_m2
            style = constraints.style or intent.requirements.style
            budget = constraints.budget or intent.requirements.budget

        explanations = list(intent.explanations)

        # ---- step 1: what does this project need? ------------------------
        # The interpreter said, in its own words, what the user is trying to
        # achieve. Those are the requirements, in the order it listed them, and
        # the only thing that decides the project's needs.
        #
        # What used to happen here is the opposite: a template supplied a fixed
        # list, and a room filter cut it down. A user who described something the
        # rulebook had never heard of got a project about something else, which is
        # why "a gaming corner in my hall" arrived carrying a refrigerator and 80
        # m². There is no rulebook to cut down now, and no room filter to apply
        # to the model's answer — the room is a constraint on *which products may
        # answer a need*, handled in step 2, not a filter on what the project is.
        index = get_catalog()
        room_scope, project_type = project_scope(index, intent)
        needs = resolve_needs(
            index,
            intent.project_requirements,
            scope=room_scope,
            project_type=project_type,
            area_m2=area,
            quality=quality,
        )

        # A department for the rows to be labelled with. It was the template's,
        # and it came free with a rulebook; a project without one still needs a
        # label, so it is read off the first need the catalogue resolved and
        # falls back to the broadest department rather than to a refusal.
        display_domain = domain or (
            self._role_domain(index, needs[0].slug, Domain.FURNITURE) if needs else Domain.FURNITURE
        )

        if not needs:
            # A project the interpreter could not break into needs is still a
            # project, and is reported as such. Refusing here would be the old
            # mistake in a new place: the project is valid, the understanding was
            # just thin.
            explanations.append(
                "از این توضیح، نیاز مشخصی برای پروژه درنیامد. "
                "اگر بگویید دقیقاً چه چیزی لازم دارید، فهرست انتخاب‌ها کامل‌تر می‌شود."
            )

        explanations.append(
            f"متراژ و سطح کیفیت اعمال‌شده: "
            f"{f'{fa_number(area)} متر مربع' if area else 'نامشخص'} / {QUALITY_FA[quality]}."
        )

        # ---- step 2: which of those can we actually buy? ------------------
        # The catalogue is consulted here and only here. It is a source of things
        # that exist, never a source of things the project needs.

        # True only when the caller handed us a basket the user already built,
        # which is the recalculation case.
        recalculating = basket is not None
        if basket is None:
            # A new project starts with an empty basket on purpose: nothing is
            # ever recommended *into* a basket. Recalculation reuses the basket
            # the user already built, so their explicit choices survive.
            basket = Basket(
                kind=BasketKind.PROJECT,
                title_fa=self._title(template, area, intent),
                owner_token="local",
                intent_payload=intent.model_dump(mode="json"),
            )
            session.add(basket)
        basket.intent_payload = intent.model_dump(mode="json")
        session.flush()

        if recalculating and basket.items:
            # Only a recalculation re-judges the basket. The items in it are the
            # user's own choices, so each is re-tested rather than rebuilt, and
            # anything dropped is named in the response.
            basket_notes = revalidate_basket(
                session,
                basket,
                index=get_catalog(),
                scope=room_scope,
                project_type=intent.project_type.value if intent.project_type else None,
                area_m2=area,
            )
            if basket_notes:
                explanations.extend(basket_notes)

        index = get_catalog()
        categories: list[RecommendedCategory] = []
        candidates: list[ProjectCandidate] = []
        missing: list[RecommendedCategory] = []
        available: list[CategoryOut] = []
        seen_slugs: set[str] = set()
        order = 0

        # The catalogue boundary: one bounded candidate set per need, built from
        # the enriched file and the project's own room, job and size. The model
        # reasons over these and nothing else.
        plans = build_candidate_set(index, needs, intent=intent, area=area)
        plan_by_role = {plan.role: plan for plan in plans}

        # One call for the whole project, never one per requirement. It is skipped
        # entirely when there is no choice to make and the basket is empty.
        _, outcome = reason_project(
            intent=intent,
            plans=plans,
            area=area,
            quality=quality,
            style=style,
            budget=budget,
            basket_items=_basket_snapshot(basket),
        )
        if outcome.rejected:
            explanations.extend(
                f"پیشنهاد نامعتبر نادیده گرفته شد: {reason}"
                for reason in outcome.rejected[:5]
            )
        explanations.extend(outcome.explanations[:5])

        # A requirement the reasoning had a real choice about, and declined, is a
        # need we cannot place for this space — not a reason to recommend the
        # cheapest thing that happens to exist. This is what stops a living-room
        # project from turning up with a bed and a dining table: those are in the
        # template, and they are in the catalogue, and neither of those makes them
        # part of *this* project.
        #
        # When the reasoning did not run at all — nothing to choose between, or the
        # call failed — nothing is withheld, so a project still gets a
        # recommendation rather than a hole. That degradation is stated, not hidden.
        if outcome.error:
            explanations.append(
                "انتخاب محصول با مدل زبانی انجام نشد؛ پیشنهادها بر پایهٔ قواعد "
                "پروژه و ارزان‌ترین گزینهٔ هر نیاز ساخته شده‌اند."
            )
            # The detail stays in the log: an exception message is for whoever
            # is diagnosing this, not for the person reading their project.

        for need in needs:
            plan = plan_by_role.get(need.role)
            chosen = outcome.selections.get(need.role)
            reason = None
            if chosen is not None and plan is not None:
                reason = _reason_for(outcome, need.role)
            had_a_choice = plan is not None and len(plan.candidates) > 1
            declined = outcome.ran and had_a_choice and chosen is None
            if declined:
                # Reported as a need of the project with no product beside it. The
                # template says the role exists; nothing says it belongs to this
                # space, and the reasoning had the products to judge that.
                categories.append(_unplaced_need(need, plan, need.quantity))
                explanations.append(
                    f"«{need.description}» برای این فضا انتخاب نشد؛ "
                    "این قلم برای این پروژه لازم نیست یا گزینهٔ مناسبی ندارد."
                )
                continue

            # The one code path that turns a requirement into advice. Loading a
            # stored project goes through the very same function, so a
            # recalculation cannot quietly disagree with the original analysis.
            recommended, candidate = recommend_for_requirement(
                index,
                need,
                intent=intent,
                domain=display_domain,
                area=area,
                quality=quality,
                plan=plan,
                selected=chosen,
                selected_reason=reason,
            )
            categories.append(recommended)

            if not recommended.catalog_match:
                # Kept, and reported as a need we cannot meet. It is never
                # dropped for want of a product, and nothing is invented for it.
                missing.append(recommended)
                if recommended.note == UNAVAILABLE_NOT_SUITABLE:
                    explanations.append(
                        f"برای «{recommended.label}» محصولی هست، ولی هیچ‌کدام در کاتالوگ "
                        "برای این اتاق یا این نوع کار مناسب نیستند؛ "
                        f"{UNAVAILABLE_NOT_SUITABLE}"
                    )
                else:
                    explanations.append(
                        f"برای «{recommended.label}» محصولی در کاتالوگ پیدا نشد؛ "
                        f"{UNAVAILABLE_NOT_STOCKED}"
                    )
                continue

            slug = need.slug
            if slug and slug not in seen_slugs:
                seen_slugs.add(slug)
                available.append(recommended.category)

            offer = candidate.offer
            freshness = f"، {offer.price_updated_at}" if offer.price_updated_at else ""
            # fa_number keeps the digits Persian: these lines are rendered
            # verbatim by the UI, and a Latin digit would show up as one.
            offered = fa_number(len(plan.candidates) if plan else 1)
            explanations.append(
                f"{candidate.label}: انتخاب‌شده از میان {offered} گزینهٔ موجود — "
                f"{offer.seller.name} ({format_toman(candidate.unit_price)}{freshness})."
            )
            candidates.append(candidate)
            # Deliberately *not* added to the basket, and neither are the
            # complements. A recommendation is advice, not a purchase.
            order += 1

        complements = _complement_candidates(outcome, plan_by_role, index, quality, area)
        if complements:
            explanations.append(
                f"پیشنهاد مکمل: {'، '.join(c.label for c in complements)} — "
                "برای کامل‌تر شدن پروژه، نه برای جایگزینی نیازها."
            )

        session.flush()
        basket_out = serialize_basket(session, basket)

        # No optimisation here. Optimising means rearranging a basket the user has
        # built, and this basket is empty on purpose — it is the one the project
        # page will add chosen items to. The estimate below is what the
        # recommendation would cost if they took all of it.
        recommended_total = sum(candidate.line_total for candidate in candidates)

        # The budget verdict is computed here, not taken from the model: the
        # arithmetic is deterministic and the totals are ours. When the estimate
        # cannot be brought inside the budget the project says so plainly, and the
        # requirements are kept rather than weakened to fit.
        if budget is not None and recommended_total > budget:
            shortfall = recommended_total - budget
            explanations.append(
                f"با بودجهٔ {format_toman(budget)}، مجموع پیشنهادها "
                f"{format_toman(recommended_total)} شد؛ "
                f"{format_toman(shortfall)} از بودجه بیشتر است و "
                f"این پروژه با گزینه‌های موجود کاملاً در بودجه جا نمی‌شود."
            )

        # A basket carries exactly one analysis (``basket_id`` is unique), so a
        # recalculation updates the analysis this basket already has instead of
        # inserting a second one and colliding with that constraint.
        analysis = (
            session.scalar(
                select(ProjectAnalysis).where(ProjectAnalysis.basket_id == basket.id)
            )
            if recalculating
            else None
        )
        if analysis is None:
            analysis = ProjectAnalysis(basket_id=basket.id)
            session.add(analysis)

        # The template is recorded when one matched, and left null when none did.
        # A project with no template is normal now, and saying so in the row is
        # how a later reader can tell it from one that merely lost its link.
        analysis.template_id = template.id if template is not None else None
        #: What this project was actually built from. Stored so a reload
        #: replays the user's own requirements instead of re-deriving them from
        #: a rulebook that may have changed, or may not exist for this project.
        analysis.needs = [
            {
                "role": need.role,
                "description": need.description,
                "terms": list(need.terms),
                "slugs": list(need.slugs),
                "quantity": need.quantity,
                "required": need.required,
                "quality_min": need.quality_min.value,
            }
            for need in needs
        ]
        analysis.title_fa = basket.title_fa or self._title(template, area, intent)
        analysis.original_query = query or (
            intent.product_query.text if intent.product_query else ""
        )
        analysis.area_m2 = Decimal(str(area)) if area else None
        analysis.quality = quality
        analysis.style = style
        analysis.budget = budget
        analysis.requirements = constraints.model_dump(mode="json")
        analysis.intent_payload = intent.model_dump(mode="json")
        analysis.reasoning = {
            "selections": {
                role: {
                    "product_id": str(candidate.product.id),
                    "reason": _reason_for(outcome, role) or "",
                }
                for role, candidate in outcome.selections.items()
            },
            "complementary": [str(c.product.id) for _, c in outcome.complementary],
            # what the model said about what the user already chose, already
            # validated against the alternatives that were offered
            # Whether the model actually chose, so a 200 from this endpoint can
            # never be read as a successful analysis when it was not.
            "status": (
                "ok" if outcome.ran else ("failed" if outcome.error else "not_needed")
            ),
            "basket_actions": [
                a.model_dump(mode="json") for a in outcome.basket_actions
            ],
            "budget_assessment": outcome.budget_assessment.model_dump(mode="json"),
            # the engine's whole explanation list, not only the model's: the
            # deterministic budget verdict and the per-candidate notes live here
            # too, and a reload has to reproduce all of it
            "explanations": list(explanations),
        }
        analysis.estimated_total = recommended_total
        analysis.confidence = Decimal(str(intent.confidence))
        analysis.interpreter = intent.interpreter
        analysis.data_source = DataSource.SEED
        session.flush()

        analysis_out = ProjectAnalysisOut(
            id=analysis.id,
            #: Null when no rulebook matched, which is a normal project rather
            #: than a broken one. The client keys off `title` and `needs`, not
            #: off a slug it must therefore treat as optional.
            template_slug=template.slug if template is not None else None,
            title=analysis.title_fa,
            domain=domain,
            project_type=(
                intent.project_type
                if intent.project_type is not None
                else (template.project_type if template is not None else None)
            ),
            area_m2=float(analysis.area_m2) if analysis.area_m2 else None,
            quality=quality,
            quality_fa=QUALITY_FA[quality],
            style=style,
            budget=budget,
            requirements=constraints,
            estimated_total=recommended_total,
            confidence=float(analysis.confidence),
            interpreter=intent.interpreter,
            interpretation=intent,
            reasoning_status=(
                "ok" if outcome.ran else ("failed" if outcome.error else "not_needed")
            ),
            categories=categories,
            available_categories=available,
            candidates=candidates,
            complementary=complements,
            missing_categories=missing,
            basket_id=basket.id,
            explanations=explanations,
            created_at=analysis.created_at.isoformat(),
        )

        return ProjectAnalyzeResponse(
            analysis=analysis_out,
            basket=basket_out,
            budget_status={
                "estimated_total": recommended_total,
                "target_budget": budget,
                "gap": (recommended_total - budget) if budget else None,
                "within_budget": (recommended_total <= budget) if budget else None,
            },
        )

    # ------------------------------------------------------------------ #
    def _find_template(self, session: Session, intent: InterpretedIntent):
        """
        The project's rulebook, **if there is one that genuinely matches**.

        A template used to be the project's identity: it supplied the whole
        requirement list, and the interpreter's own reading of the sentence was
        discarded in favour of it. That is gone — the requirements come from the
        model now, and a project with no template is an ordinary project.

        What is left here is an *optional preset*, looked up by the slug the
        interpreter already resolved (``SearchService.enrich`` fills it in from a
        named domain and project type). It can refine the quantity of a need the
        model asked for, and name the project when the user said nothing else. It
        cannot introduce a need, and its absence is not an error.

        There is no search, and in particular no "pick the best-scoring template"
        pass: with no room and no domain every template is equally unjustified, so
        a scan over them returned whichever row the database happened to send
        first. That is the same nondeterminism that let one run build a bathroom
        renovation for a hall and the next an appliance renovation for it.
        """
        if not intent.template_slug:
            return None
        return session.scalar(
            select(ProjectTemplate).where(
                ProjectTemplate.slug == intent.template_slug,
                ProjectTemplate.is_active.is_(True),
            )
        )

    @staticmethod
    def _role_domain(index, slug: str | None, fallback: Domain) -> Domain:
        """The domain a subcategory really belongs to, not a guessed one."""
        if not slug:
            return fallback
        top = index.top_category_of(slug)
        if not top:
            return fallback
        return domain_from(top) or fallback

    @staticmethod
    def _effective_quality(target: Quality, floor: Quality) -> Quality:
        return target if target.rank >= floor.rank else floor

    @staticmethod
    def _title(
        template: ProjectTemplate | None, area: float | None, intent: InterpretedIntent
    ) -> str:
        """
        The user's own words lead, then the room they named.

        A template may name the project when nothing else can, but it is the last
        resort rather than the first: naming a hall project after a rulebook is
        how the project ended up described as something it is not.
        """
        if intent.goal:
            return intent.goal
        room = intent.room or (template.name_fa if template is not None else None)
        if room and area:
            return f"{room} {fa_number(area)} متر مربع"
        if room:
            return room
        return template.name_fa if template is not None else "پروژهٔ خانه"

    @staticmethod
    def _item_reason(need, quantity: int, quality: Quality, area: float | None) -> str:
        base = (
            f"این گزینه با توجه به متراژ {fa_number(area) if area else '—'} متر مربع و "
            f"سطح کیفیت {QUALITY_FA[quality]} انتخاب شد."
        )
        return base


def _cheapest_candidate(
    index,
    slug: str | None,
    *,
    scope: RoomScope,
    project_type: str | None,
    area_m2: float | None,
) -> CatalogProduct | None:
    """
    The best candidate the catalogue actually offers for this role.

    Eligibility comes first, from the enriched metadata: a product is only a
    candidate if the file places it in one of the project's rooms and does not
    rule out this kind of job. Within the eligible set, suitability for the space
    decides and price breaks ties.

    Quality cannot narrow this — the catalogue states none, and inventing a
    quality figure would be a claim the shop cannot back up.
    """
    candidates = select_candidates(
        index, slug, scope=scope, project_type=project_type, area_m2=area_m2
    )
    return candidates[0] if candidates else None


def _basket_snapshot(basket: Basket) -> list[dict]:
    """
    What the user has chosen, in the shape the reasoning prompt reads.

    Prices come from the basket rows, which the server wrote from the catalogue,
    so the model is never told a price the backend did not read.
    """
    out: list[dict] = []
    for item in basket.items:
        product = get_catalog().get(item.product_id)
        if product is None:
            continue
        out.append(
            {
                "product_id": product.id,
                "name": product.name,
                "subcategory": product.subcategory,
                "unit_price": int(item.unit_price),
                "quantity": int(item.quantity),
                "role": item.role,
            }
        )
    return out


def _reason_for(outcome, role: str) -> str | None:
    """The model's stated reason for a role, if it gave one."""
    return outcome.reasons.get(role)


def _complement_candidates(outcome, plan_by_role, index, quality, area) -> list[ProjectCandidate]:
    """
    Complements the model proposed, as advice only.

    Each one has already been checked against the file's own declared
    relationship and against the project's room, so nothing here can be an
    alternative in disguise. None of them is added to the basket.
    """
    out: list[ProjectCandidate] = []
    for role, candidate in outcome.complementary:
        plan = plan_by_role.get(role)
        if plan is None or not plan.complements:
            continue
        offers = candidate.product.purchasable_offers
        offer = offers[0] if offers else None
        if offer is None:
            continue
        out.append(
            ProjectCandidate(
                role=f"{role}__complement",
                label=candidate.product.name[:80],
                quantity=1,
                unit="عدد",
                product=to_product_out(candidate.product, offer_limit=2),
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


def _unit_of(index, slug: str | None) -> str:
    """The catalogue states no unit, so the neutral default is used."""
    return "عدد"


def _refresh_candidates(
    session: Session, basket: Basket, previous: list[ProjectCandidate]
) -> list[ProjectCandidate]:
    """After optimisation, re-read candidate prices from the basket rows."""
    snapshot = serialize_basket(session, basket)
    by_role = {item.role: item for item in snapshot.items}
    refreshed: list[ProjectCandidate] = []
    for candidate in previous:
        item = by_role.get(candidate.role)
        if item is None:
            continue
        refreshed.append(
            candidate.model_copy(
                update={
                    "product": item.product,
                    "offer": item.offer,
                    "unit_price": item.unit_price,
                    "line_total": item.line_total,
                    "seller_name": item.offer.seller.name,
                    "quantity": item.quantity,
                }
            )
        )
    return refreshed


def template_out(template: ProjectTemplate, requirement_count: int) -> ProjectTemplateOut:
    return ProjectTemplateOut(
        id=template.id,
        slug=template.slug,
        name=template.name_fa,
        domain=template.domain,
        project_type=template.project_type,
        description_fa=template.description_fa,
        requirement_count=requirement_count,
    )


__all__ = ["ProjectEngine", "ProjectError", "ROLE_FA", "role_label", "template_out"]
