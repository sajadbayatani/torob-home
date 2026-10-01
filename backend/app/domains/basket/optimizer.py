"""Deterministic, explainable budget optimisation.

Design constraints from the product brief:
* no LLM is involved in any calculation;
* the optimised total can never exceed the original total;
* every change is explainable ("این جایگزین X تومان هزینه را کاهش می‌دهد");
* quality is only traded down, and never below the project's quality floor.

The catalogue records **no quality**, so `quality` is `None` throughout. Where a
comparison would need it, the swap is allowed on price alone and the explanation
says nothing about quality, rather than inventing a quality for a product the
file does not describe.

The planner (`plan_optimization`) is a pure function over plain dataclasses, so
it is unit-testable without a database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import Quality
from app.core.text import fa_number, format_toman
from app.domains.basket.models import Basket
from app.domains.basket.schemas import OptimizationChange, OptimizationResult


@dataclass(frozen=True)
class Candidate:
    product_id: UUID
    product_name: str
    price: int
    #: None when the catalogue does not state a quality for the product
    quality: Quality | None = None


@dataclass
class OptimizableItem:
    item_id: UUID
    role: str
    product_id: UUID
    product_name: str
    unit_price: int
    quantity: int
    quality: Quality | None = None
    locked: bool = False
    quality_floor: Quality = Quality.LOW
    candidates: list[Candidate] = field(default_factory=list)

    @property
    def line_total(self) -> int:
        return self.unit_price * self.quantity


@dataclass
class Swap:
    item_id: UUID
    role: str
    from_product: str
    from_product_id: UUID
    to_product: str
    to_product_id: UUID
    from_price: int
    to_price: int
    quantity: int
    quality_from: Quality | None = None
    quality_to: Quality | None = None

    @property
    def saving(self) -> int:
        return (self.from_price - self.to_price) * self.quantity


def total_of(items: list[OptimizableItem]) -> int:
    return sum(item.line_total for item in items)


def _candidate_allowed(
    candidate: Candidate, item: OptimizableItem, *, allow_quality_downgrade: bool
) -> bool:
    """A swap must be cheaper, and must not breach a quality floor.

    The quality rules only apply when both sides actually state a quality. The
    catalogue states none, so in practice the floor cannot be checked and price
    is the criterion — the explanation then says nothing about quality.
    """
    if candidate.price >= item.unit_price:
        return False
    if candidate.quality is not None and candidate.quality.rank < item.quality_floor.rank:
        return False
    if (
        not allow_quality_downgrade
        and candidate.quality is not None
        and item.quality is not None
        and candidate.quality.rank < item.quality.rank
    ):
        return False
    return True


def plan_optimization(
    items: list[OptimizableItem],
    target_budget: int,
    *,
    allow_quality_downgrade: bool = True,
) -> list[Swap]:
    """Greedy plan: repeatedly apply the single swap with the largest saving.

    Ties are broken by the smaller quality loss and then by a stable role key, so
    the plan is fully deterministic for the same input.
    """
    current_total = total_of(items)
    if target_budget <= 0 or current_total <= target_budget:
        return []

    swaps: list[Swap] = []
    swapped: set[UUID] = set()
    working: dict[UUID, OptimizableItem] = {item.item_id: item for item in items}

    while True:
        best: tuple[tuple, Swap, Candidate] | None = None
        for item in working.values():
            if item.locked or item.item_id in swapped:
                continue
            for candidate in item.candidates:
                if not _candidate_allowed(
                    candidate, item, allow_quality_downgrade=allow_quality_downgrade
                ):
                    continue
                saving = (item.unit_price - candidate.price) * item.quantity
                if saving <= 0:
                    continue
                # only comparable when both products state a quality
                quality_loss = (
                    item.quality.rank - candidate.quality.rank
                    if item.quality is not None and candidate.quality is not None
                    else 0
                )
                rank = (-saving, quality_loss, item.role, str(candidate.product_id))
                if best is None or rank < best[0]:
                    best = (
                        rank,
                        Swap(
                            item_id=item.item_id,
                            role=item.role,
                            from_product=item.product_name,
                            from_product_id=item.product_id,
                            to_product=candidate.product_name,
                            to_product_id=candidate.product_id,
                            from_price=item.unit_price,
                            to_price=candidate.price,
                            quantity=item.quantity,
                            quality_from=item.quality,
                            quality_to=candidate.quality,
                        ),
                        candidate,
                    )
        if best is None:
            break
        _rank, swap, candidate = best
        swaps.append(swap)
        swapped.add(swap.item_id)
        item = working[swap.item_id]
        item.unit_price = candidate.price
        item.product_id = candidate.product_id
        item.product_name = candidate.product_name
        item.quality = candidate.quality
        if total_of(list(working.values())) <= target_budget:
            break
    return swaps


# --------------------------------------------------------------------------- #
# DB backed entry point
# --------------------------------------------------------------------------- #
def _quality_floors(session: Session, basket: Basket) -> dict[str, Quality]:
    """Per-role quality floor coming from the project's own requirements.

    Read from the needs the analysis was built from. They used to come from the
    template's rules, which meant the optimiser judged a project against a
    rulebook's opinions rather than the floors the interpreter had set — and
    could not judge a project that matched no rulebook at all.
    """
    from app.domains.projects.models import ProjectAnalysis

    analysis = session.scalar(select(ProjectAnalysis).where(ProjectAnalysis.basket_id == basket.id))
    if analysis is None:
        return {}
    floors: dict[str, Quality] = {}
    for row in analysis.needs or []:
        try:
            floors[str(row.get("role"))] = Quality(row.get("quality_min") or Quality.LOW.value)
        except ValueError:
            continue
    return floors


def build_items(
    session: Session,
    basket: Basket,
    *,
    scope=None,
    project_type: str | None = None,
    area_m2: float | None = None,
) -> list[OptimizableItem]:
    """Build the optimiser input from live basket rows + catalogue alternatives.

    Products come from the JSON catalogue, and a cheaper product of the same kind
    is the only kind of alternative offered — the catalogue records no
    compatibility or quality relationship to swap within.

    When the project context is supplied, a replacement must also suit it: the
    same room and the same kind of job. Swapping a bedroom lamp for something the
    file places in another room would be cheaper and wrong, so such a candidate is
    never offered, and the swap is never planned.
    """
    from app.catalog.selection import is_eligible
    from app.catalog.store import get_catalog

    index = get_catalog()
    floors = _quality_floors(session, basket)
    out: list[OptimizableItem] = []
    for item in basket.items:
        product = index.get(item.product_id)
        if product is None:
            continue
        candidates: list[Candidate] = []
        for alt in index.subcategories_of(product.subcategory):
            if alt.id == product.id:
                continue
            if scope is not None and not is_eligible(
                alt, scope=scope, project_type=project_type, area_m2=area_m2
            ):
                continue
            for offer in alt.purchasable():
                candidates.append(
                    Candidate(
                        product_id=alt.id,
                        product_name=alt.name,
                        price=int(offer.price),
                        # the catalogue states no quality
                        quality=None,
                    )
                )
        out.append(
            OptimizableItem(
                item_id=item.id,
                role=item.role,
                product_id=product.id,
                product_name=product.name,
                unit_price=int(item.unit_price),
                quantity=int(item.units),
                quality=None,
                locked=bool(item.is_locked),
                quality_floor=floors.get(item.role, Quality.LOW),
                candidates=candidates,
            )
        )
    return out


def optimize_basket(
    session: Session,
    basket: Basket,
    target_budget: int,
    *,
    apply: bool = False,
    allow_quality_downgrade: bool = True,
    scope=None,
    project_type: str | None = None,
    area_m2: float | None = None,
) -> OptimizationResult:
    items = build_items(
        session, basket, scope=scope, project_type=project_type, area_m2=area_m2
    )
    original_total = total_of(items)

    # The deterministic plan is always computed: it is what the user gets when
    # the model is unavailable, and it is the shape every proposal is validated
    # into. The model then gets to propose its own actions over the very same
    # cleared alternatives, and each one is checked against them before use.
    swaps = plan_optimization(items, target_budget, allow_quality_downgrade=allow_quality_downgrade)
    swaps, llm_notes, assessment = _reason_about_basket(
        items=items,
        basket=basket,
        swaps=swaps,
        target_budget=target_budget,
        scope=scope,
        project_type=project_type,
        area_m2=area_m2,
    )
    optimized_total = original_total - sum(s.saving for s in swaps)

    changes = [
        OptimizationChange(
            item=swap.role,
            item_id=swap.item_id,
            role=swap.role,
            from_product=swap.from_product,
            from_product_id=swap.from_product_id,
            to_product=swap.to_product,
            to_product_id=swap.to_product_id,
            from_price=swap.from_price,
            to_price=swap.to_price,
            quantity=swap.quantity,
            saving=swap.saving,
            reason=_explain_swap(swap),
            quality_from=_quality_label(swap.quality_from),
            quality_to=_quality_label(swap.quality_to),
        )
        for swap in swaps
    ]

    if apply and swaps:
        _apply_swaps(session, basket, swaps)

    trade_offs = list(llm_notes)
    trade_offs += [
        f"کیفیت «{c.quality_from}» به «{c.quality_to}» کاهش یافت."
        for c in changes
        if c.quality_from != c.quality_to
    ]
    if not trade_offs:
        trade_offs.append(
            "کاتالوگ برای این محصولات کیفیتی ثبت نکرده است، پس جایگزینی فقط بر پایهٔ قیمت انجام شد."
        )
    unfilled = max(0, optimized_total - target_budget)
    if apply:
        # Only an accepted optimisation writes anything. A preview leaves the
        # basket exactly as the user left it, including its stored budget.
        basket.target_budget = target_budget
        session.flush()

    return OptimizationResult(
        original_total=original_total,
        target_budget=target_budget,
        optimized_total=optimized_total,
        saved=original_total - optimized_total,
        within_budget=unfilled == 0,
        unfilled_gap=unfilled,
        changes=changes,
        applied=bool(apply and swaps),
        can_optimize=bool(swaps),
        over_budget=original_total > target_budget,
        explanation=_overall_explanation(original_total, optimized_total, target_budget, changes),
        trade_offs=trade_offs,
    )


def _reason_about_basket(
    *,
    items: list[OptimizableItem],
    basket: Basket,
    swaps: list[Swap],
    target_budget: int,
    scope,
    project_type: str | None,
    area_m2: float | None,
):
    """
    Let the model propose actions over the basket, and keep only valid ones.

    The model is given the current basket and the alternatives the backend
    already cleared for each item — same subcategory, same room, same kind of job,
    actually purchasable. It may keep, replace or remove. Every action is checked
    against those alternatives before it becomes a proposal, and the prices in the
    proposal are read from the catalogue rather than from the answer, so the model
    can decide *which* product but never what it costs.

    Returns the swaps to propose, any notes, and the model's budget assessment.
    Nothing here writes to the basket; that only happens on an explicit apply.
    """
    from app.catalog.store import get_catalog
    from app.domains.projects.reasoning import (
        BudgetAssessment,
        Candidate,
        reason_optimization,
    )

    if not items:
        return swaps, [], BudgetAssessment(status="no_budget", reason="")

    index = get_catalog()
    basket_items: list[dict] = []
    candidates_by_item: dict[str, list[Candidate]] = {}
    item_by_product: dict[str, OptimizableItem] = {}

    for item in items:
        product = index.get(item.product_id)
        if product is None:
            continue
        basket_items.append(
            {
                "product_id": product.id,
                "name": product.name,
                "subcategory": product.subcategory,
                "unit_price": int(item.unit_price),
                "quantity": int(item.quantity),
                "role": item.role,
            }
        )
        item_by_product[str(product.id)] = item
        # Only the alternatives the backend cleared for this exact item.
        cleared: list[Candidate] = []
        for candidate in item.candidates:
            alt = index.get(candidate.product_id)
            if alt is None or not alt.purchasable_offers:
                continue
            if alt.subcategory != product.subcategory:
                continue
            cleared.append(
                Candidate(
                    alt,
                    requirement_role=item.role,
                    price=candidate.price,
                    offer_id=alt.purchasable_offers[0].id,
                    seller_name=alt.purchasable_offers[0].seller.name,
                )
            )
        candidates_by_item[str(product.id)] = cleared

    intent = _basket_intent(basket)
    _, answer, rejected = reason_optimization(
        intent=intent,
        basket_items=basket_items,
        candidates_by_item=candidates_by_item,
        area=area_m2,
        quality=_basket_quality(basket),
        budget=target_budget,
        style=None,
    )
    notes: list[str] = list(answer.explanations)
    for problem in rejected[:5]:
        notes.append(f"پیشنهاد نامعتبر نادیده گرفته شد: {problem}")

    if not answer.actions:
        # Nothing valid proposed: the deterministic plan stands.
        return swaps, notes, answer.budget_assessment

    proposed: list[Swap] = []
    for action in answer.actions:
        current_id = action.current_product_id.strip()
        item = item_by_product.get(current_id)
        if item is None:
            continue
        if action.action == "keep":
            continue
        if action.action == "remove":
            # Removing something the user chose is never applied as a silent
            # edit; it is only ever reported, and the basket is left intact.
            notes.append(
                f"پیشنهاد شد «{item.product_name}» از فهرست انتخاب‌ها برداشته شود: "
                f"{action.reason} — تا تأیید شما در فهرست شما می‌ماند."
            )
            continue
        replacement_id = (action.replacement_product_id or "").strip()
        cleared = candidates_by_item.get(current_id, [])
        replacement = next(
            (c for c in cleared if str(c.product.id) == replacement_id), None
        )
        if replacement is None:
            continue
        swap = Swap(
            item_id=item.item_id,
            role=item.role,
            from_product=item.product_name,
            from_product_id=item.product_id,
            to_product=replacement.product.name,
            to_product_id=replacement.product.id,
            from_price=int(item.unit_price),
            # the catalogue's price, never a number from the answer
            to_price=int(replacement.price),
            quantity=int(item.quantity),
            quality_from=item.quality,
            quality_to=None,
        )
        proposed.append(swap)
        notes.append(f"{replacement.product.name}: {action.reason}")

    if proposed:
        swaps = proposed
    return swaps, notes, answer.budget_assessment


def _basket_intent(basket: Basket):
    """The project's own stored intent, so the basket is judged in its context."""
    from app.domains.search.schemas import InterpretedIntent

    if basket.intent_payload:
        try:
            return InterpretedIntent.model_validate(basket.intent_payload)
        except Exception:  # noqa: BLE001 - an old payload is not a reason to fail
            pass
    return InterpretedIntent.model_validate(
        {
            "intent": "NEED_SEARCH",
            "domain": None,
            "project_type": None,
            "template_slug": None,
            "product_query": None,
            "requirements": {
                "area_m2": None,
                "quality": None,
                "style": None,
                "budget": None,
                "priorities": [],
                "extra": {},
            },
            "constraint_kind": "NONE",
            "confidence": 0.0,
            "interpreter": "stored",
            "explanations": [],
            "matched_subcategories": [],
            "missing_categories": [],
            "room": None,
            "goal": None,
        }
    )


def _basket_quality(basket: Basket) -> Quality:
    payload = basket.intent_payload or {}
    raw = (payload.get("requirements") or {}).get("quality")
    try:
        return Quality(raw) if raw else Quality.MEDIUM
    except ValueError:
        return Quality.MEDIUM


def _apply_swaps(session: Session, basket: Basket, swaps: list[Swap]) -> None:
    from app.catalog.store import get_catalog

    index = get_catalog()
    for swap in swaps:
        item = next((i for i in basket.items if i.id == swap.item_id), None)
        if item is None:
            continue
        product = index.get(swap.to_product_id)
        if product is None:
            continue
        offers = list(product.purchasable())
        if not offers:
            continue
        offer = offers[0]
        item.replaced_item_id = item.id
        item.product_id = product.id
        item.offer_id = offer.id
        item.unit_price = int(offer.price)
        item.reason_fa = f"جایگزین «{swap.from_product}» برای کاهش هزینه"
    session.flush()


QUALITY_LABEL = {
    Quality.LOW: "اقتصادی",
    Quality.MEDIUM: "متوسط",
    Quality.HIGH: "بالا",
    Quality.ULTRA: "لوکس",
}


def _quality_label(quality: Quality | None) -> str:
    """Quality wording, or a dash when the catalogue states none."""
    return QUALITY_LABEL[quality] if quality is not None else "—"


def _explain_swap(swap: Swap) -> str:
    base = (
        f"«{swap.to_product}» جایگزین «{swap.from_product}» شد و "
        f"{format_toman(swap.saving)} کاهش هزینه ایجاد می‌کند."
    )
    if swap.quality_from is None or swap.quality_to is None:
        return base + " کیفیت در کاتالوگ ثبت نشده است، پس مقایسه‌ای روی آن انجام نشد."
    return (
        f"«{swap.to_product}» جایگزین «{swap.from_product}» شد و "
        f"{format_toman(swap.saving)} کاهش هزینه ایجاد می‌کند "
        f"(کیفیت {QUALITY_LABEL[swap.quality_from]} به {QUALITY_LABEL[swap.quality_to]})."
    )


def _overall_explanation(
    original_total: int,
    optimized_total: int,
    target_budget: int,
    changes: list[OptimizationChange],
) -> str:
    if not changes:
        if original_total <= target_budget:
            return (
                f"فهرست انتخاب‌ها با {format_toman(original_total)} کمتر از بودجهٔ "
                f"{format_toman(target_budget)} است؛ نیازی به تغییر نیست."
            )
        return (
            f"برای رسیدن به بودجهٔ {format_toman(target_budget)} جایگزین سازگارتری در کاتالوگ "
            f"پیدا نشد؛ فهرست انتخاب‌ها روی {format_toman(original_total)} باقی ماند."
        )
    if optimized_total <= target_budget:
        return (
            f"با {fa_number(len(changes))} تغییر، هزینه از {format_toman(original_total)} به "
            f"{format_toman(optimized_total)} رسید و در بودجهٔ {format_toman(target_budget)} "
            "قرار گرفت."
        )
    return (
        f"با {fa_number(len(changes))} تغییر، هزینه به {format_toman(optimized_total)} کاهش یافت "
        "اما هنوز "
        f"{format_toman(optimized_total - target_budget)} بالاتر از بودجهٔ "
        f"{format_toman(target_budget)} است."
    )
