"""
Project-level reasoning by the model, over a candidate set the backend chose.

The split of labour is deliberate and one-directional:

* The **backend** decides what is *true*. It reads the canonical enriched
  catalogue, drops everything that cannot be part of this project, and hands the
  model a small, closed set of products that already satisfy every hard
  constraint. Prices, offers and availability are read from the file, never
  generated.
* The **model** decides what is *sensible*. Given the project as a whole — the
  room, the kind of work, the size, the quality asked for, the budget, and what
  the user already put in the basket — it picks among those candidates, judges
  whether the set hangs together, and explains itself.

The model is never shown the catalogue. It is shown a bounded candidate set for
the requirements in hand, and every identifier it returns is checked against that
set before anything downstream can act on it. An unknown or invented id is
dropped and reported, never honoured, so the catalogue boundary cannot be crossed
from the other side.

Two prompts live here, and neither of them is the intent interpreter's: this is
product reasoning, not understanding what the user asked for. A project costs at
most **one** call, whatever the number of requirements or basket items, because
the reasoning is about the project as a whole rather than per product.
"""

from __future__ import annotations

import logging
from typing import Any, Literal, Mapping
from uuid import UUID

from pydantic import Field, field_validator

from app.core.enums import ProjectType, Quality
from app.domains.search.schemas import StrictModel

logger = logging.getLogger("home_procurement.projects.reasoning")

#: How many products the backend offers per requirement. Enough for a genuine
#: choice between cheap and strong, small enough that the prompt stays small and
#: the answer is about the project rather than a catalogue.
CANDIDATES_PER_REQUIREMENT = 6

#: Complements are suggestions, not the recommendation itself, so fewer are
#: offered than alternatives.
COMPLEMENT_LIMIT = 3

#: Metadata keys worth the tokens. Everything here is already in the canonical
#: file; nothing is computed, tagged or inferred at runtime.
_METADATA_FIELDS = (
    "rooms",
    "product_roles",
    "use_cases",
    "project_types",
    "space_fit",
    "styles",
    "features",
    "alternative_subcategories",
    "complementary_subcategories",
)


# --------------------------------------------------------------------------- #
# Strict response schemas
# --------------------------------------------------------------------------- #
class _ReasoningBase(StrictModel):
    """Bounded free text, so a chatty answer cannot inflate the response."""

    @field_validator("reason", check_fields=False)
    @classmethod
    def _cap_reason(cls, value: str) -> str:
        return (value or "").strip()[:240]

    @field_validator("explanations", check_fields=False)
    @classmethod
    def _cap_explanations(cls, value: list[str]) -> list[str]:
        return [v.strip()[:240] for v in value if v and v.strip()][:6]


class Selection(_ReasoningBase):
    """Which offered candidate best satisfies one requirement."""

    requirement_role: str = Field(max_length=60)
    product_id: str = Field(max_length=64)
    reason: str = ""


class ComplementaryPick(_ReasoningBase):
    """
    A product worth having *alongside* the project's needs.

    Separate from a selection on purpose: a different bed is an alternative to
    the bed, never a complement to it. Only a different requirement qualifies.
    """

    requirement_role: str = Field(max_length=60)
    product_id: str = Field(max_length=64)
    reason: str = ""


class BasketAction(_ReasoningBase):
    """What the model thinks about something the user already chose."""

    action: Literal["keep", "replace", "remove"]
    current_product_id: str = Field(max_length=64)
    replacement_product_id: str | None = Field(default=None, max_length=64)
    reason: str = ""


class BudgetAssessment(_ReasoningBase):
    status: Literal["within_budget", "over_budget", "no_budget"]
    reason: str = ""


class ProjectReasoningResponse(_ReasoningBase):
    """The model's whole view of the project, in one answer."""

    selections: list[Selection] = Field(default_factory=list)
    complementary: list[ComplementaryPick] = Field(default_factory=list)
    basket_actions: list[BasketAction] = Field(default_factory=list)
    budget_assessment: BudgetAssessment = Field(default_factory=lambda: BudgetAssessment(status="no_budget"))
    explanations: list[str] = Field(default_factory=list)

    @field_validator("selections", "complementary", "basket_actions")
    @classmethod
    def _cap_lists(cls, value: list) -> list:
        return list(value)[:24]


class OptimizationAction(_ReasoningBase):
    action: Literal["keep", "replace", "remove"]
    current_product_id: str = Field(max_length=64)
    replacement_product_id: str | None = Field(default=None, max_length=64)
    reason: str = ""


class OptimizationReasoningResponse(_ReasoningBase):
    actions: list[OptimizationAction] = Field(default_factory=list)
    budget_assessment: BudgetAssessment = Field(
        default_factory=lambda: BudgetAssessment(status="no_budget")
    )
    explanations: list[str] = Field(default_factory=list)

    @field_validator("actions")
    @classmethod
    def _cap_actions(cls, value: list[OptimizationAction]) -> list[OptimizationAction]:
        return list(value)[:24]


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #
PROJECT_SYSTEM_PROMPT = """تو برای یک پروژهٔ خانه انتخاب محصول می‌کنی. ساختار می‌دهی، نه اینکه چیزی بسازی.

تو فقط می‌توانی از محصولاتی استفاده کنی که در فهرست candidates برایت فرستاده شده‌اند. هر شناسه‌ای که در آن فهرست نیست، وجود ندارد.

هرگز این‌ها را از خودت نساز:
- محصول، برند یا شناسهٔ محصول
- قیمت یا فروشنده یا موجودی
- مشخصات فنی، جنس، برند یا ویژگی‌ای که در فهرست نیامده
- دسته، اتاق یا رابطه‌ای که در متادیتای فهرست نیامده

آنچه در متادیتا نیامده، وجود ندارد. اگر چیزی را نمی‌دانی، از قیمت و متادیتای موجود استنتاج کن و دلیلش را بنویس.

میزان کیفیت (quality) یک خواستهٔ کاربر است، نه مشخصهٔ محصول. کاتالوگ کیفیت ثبت‌شده ندارد. پس کیفیت را از روی متادیتا، ویژگی‌ها، سبک و قیمت داوری کن:
- low: ساده و کاربردی
- medium: انتخاب متعادل و میانه
- high: محکم‌تر و کامل‌تر، وقتی گزینه‌ای هست
- ultra: قوی‌ترین گزینهٔ موجود، حتی اگر گران‌تر باشد
اگر تفاوت واقعی بین گزینه‌ها از متادیتا معلوم نیست، همان گزینهٔ متناسب با قیمت را انتخاب کن و در دلیل بگو که تفاوت قابل تشخیص نبوده. کیفیتی را به محصول نسبت نده که در فهرست نیامده.

بودجه سقف است، نه هدف خرج کردن. اگر مجموع انتخاب‌ها از بودجه بیشتر شد:
- اول ببین جایگزین ارزان‌ترِ معتبر برای همان نیاز هست یا نه
- اگر هست، همان را انتخاب کن
- اگر نیست، نیازها را حفظ کن و در budget_assessment بگو over_budget. نیاز ضروری را برای جا شدن در بودجه حذف یا ضعیف نکن.

کل مجموعه را با هم داوری کن، نه هر نیاز را جدا. یک انتخاب منسجم می‌خواهیم، نه ارزان‌ترین گزینه برای هر سطر.

قواعد دیگر:
- برای هر نیازی که در requirements آمده، دقیقاً یک selection بده، فقط از candidates همان نیاز.
- اگر برای نیازی candidate نداری، آن نیاز را در selections نیاور؛ خودمان آن را ناموجود گزارش می‌کنیم.
- complementary فقط برای نیازی باشد که خودش نیاز پروژه است و از complementary_subcategories می‌آید. جایگزینِ همان زیرمجموعه، هرگز complementary نیست.
- برای هر قلمی که کاربر در basket گذاشته، یک basket_action بده: keep، یا replace با شناسهٔ جایگزین از candidates همان زیرمجموعه، یا remove فقط وقتی دلیل روشنی داری. انتخاب صریح کاربر را بی‌دلیل برندار.
- reason کوتاه، فارسی و مشخص: چرا این گزینه برای این پروژه.
- هیچ فیلدی جز این‌ها ننویس. name، subcategory، quantity، price_toman، seller، quality و هر چیز دیگری که در ورودی دیدی **پاسخ نیست**؛ ورودی توصیف می‌شود نه خروجی. تنها سه فیلد هر انتخاب: requirement_role، product_id، reason.
- مبلغ‌ها را خودت حساب نکن؛ قیمت و جمع از کاتالوگ خوانده می‌شود.
- budget_assessment.status فقط یکی از within_budget | over_budget | no_budget است. هیچ مقدار دیگری، از جمله budget_not_provided، معتبر نیست؛ وقتی بودجه‌ای نیست همان no_budget را بنویس.
- فقط و فقط یک JSON object بده، بدون markdown و بدون متن بیرون از آن، دقیقاً با این ساختار:
{"selections":[{"requirement_role":"...","product_id":"...","reason":"..."}],"complementary":[],"basket_actions":[{"action":"keep","current_product_id":"...","replacement_product_id":null,"reason":"..."}],"budget_assessment":{"status":"no_budget","reason":"..."},"explanations":[]}
"""

OPTIMIZATION_SYSTEM_PROMPT = """تو فهرست انتخاب‌های کاربر را بهینه می‌کنی. ساختار می‌دهی، نه اینکه چیزی بسازی.

این فهرست سبد خرید یا سفارش نیست: محصولاتی است که کاربر برای این کار در نظر دارد و می‌خواهد فروشنده‌ها و قیمت‌هایشان را مقایسه کند. خرید را خود کاربر از فروشنده انجام می‌دهد.

تو فقط می‌توانی از محصولاتی استفاده کنی که در فهرست candidates برایت فرستاده شده‌اند. هر شناسه‌ای که در آن فهرست نیست، وجود ندارد.

هرگز این‌ها را از خودت نساز:
- محصول، برند یا شناسهٔ محصول
- قیمت، فروشنده یا موجودی
- مشخصاتی که در فهرست نیامده
- دسته یا رابطه‌ای که در متادیتای فهرست نیامده

آنچه در متادیتا نیامده، وجود ندارد.

تو پیشنهاد می‌دهی، تغییر نمی‌دهی. فهرست انتخاب‌های کاربر بدون تأیید او عوض نمی‌شود.

قواعد:
- برای هر قلم موجود در basket دقیقاً یک action بده.
- keep: قلم درست است. این پیش��ش پیش‌فرض است وقتی دلیلی برای تغییر نیست.
- replace: فقط با یکی از candidateهای همان زیرمجموعه و همان نقش. ارزان‌تر یا مناسب‌تر برای پروژه.
- remove: فقط وقتی قلم با اتاق یا نوع کار پروژه ناسازگار است. برای کم کردن هزینه، remove نکن؛ replace کن.
- جایگزین باید از همان زیرمجموعه باشد. جایگزینِ زیرمجموعهٔ دیگر یا محصولِ نامرتبط ممنوع است.
- میزان کیفیت خواستهٔ کاربر است، نه مشخصهٔ محصول. کاتالوگ کیفیت ثبت نشده دارد؛ از متادیتا و قیمت داوری کن و چیزی نسبت نده که در فهرست نیامده.
- اگر کاربر محصولی گرفته که گران است ولی درست است، پیشنهاد خرید ارزان‌تر نده مگر واقعاً معادل باشد. انتخاب کاربر محترم است.
- مجموع انتخاب‌ها و بودجهٔ هدف را با هم ببین. اگر جایگزینی هست که هم نیاز را پوشش می‌دهد و هم زیر بودجه می‌ماند، همان را پیشنهاد بده.
- اگر هیچ تغییر معتبری نیست، برای همه keep بده و در budget_assessment توضیح بده که تغییری لازم نیست.
- reason کوتاه، فارسی و مشخص.
- هیچ فیلدی جز این‌ها ننویس؛ name، price_toman، seller و مانند آن‌ها ورودی‌اند نه پاسخ. هر اقدام فقط: action، current_product_id، replacement_product_id، reason.
- فقط و فقط یک JSON object بده، بدون markdown و بدون متن بیرون از آن، دقیقاً با این ساختار:
{"actions":[{"action":"keep","current_product_id":"...","replacement_product_id":null,"reason":"..."}],"budget_assessment":{"status":"no_budget","reason":"..."},"explanations":[]}
"""


# --------------------------------------------------------------------------- #
# Candidate set — the catalogue boundary
# --------------------------------------------------------------------------- #
class Candidate:
    """One product the backend has already cleared for a requirement."""

    __slots__ = ("product", "requirement_role", "price", "offer_id", "seller_name", "complementary_for")

    def __init__(
        self,
        product,
        *,
        requirement_role: str,
        price: int,
        offer_id: UUID,
        seller_name: str,
        complementary_for: str | None = None,
    ) -> None:
        self.product = product
        self.requirement_role = requirement_role
        self.price = price
        self.offer_id = offer_id
        self.seller_name = seller_name
        #: when set, this candidate is offered because the file says it goes
        #: with that subcategory, so it is a complement and not an alternative
        self.complementary_for = complementary_for


class RequirementPlan:
    """A need, the quantity it resolves to, and its candidate list."""

    __slots__ = ("need", "label", "quantity", "candidates", "complements")

    def __init__(self, need, label: str, quantity: int) -> None:
        self.need = need
        self.label = label
        self.quantity = quantity
        #: products that could satisfy this need; a real choice
        self.candidates: list[Candidate] = []
        #: products the file says go *with* this need; never an alternative
        self.complements: list[Candidate] = []

    @property
    def role(self) -> str:
        return self.need.role

    @property
    def slug(self) -> str | None:
        return self.need.slug


def build_candidate_set(
    index,
    needs,
    *,
    intent,
    area: float | None,
    limit: int = CANDIDATES_PER_REQUIREMENT,
) -> list[RequirementPlan]:
    """
    Every candidate the model is allowed to choose between, and nothing else.

    The needs arrive already resolved against the catalogue — each carries the
    subcategories the file answers it with — so this stage is arithmetic over
    real rows and the hard constraints: a product is offered only if the enriched
    file places it in one of this project's rooms, allows this kind of job, and
    can actually be bought. The first candidate is the cheapest suitable one,
    which is what the project falls back to when the model does not choose, so
    behaviour without a model is unchanged.

    A need the catalogue answers with nothing gets a plan with no candidates.
    That is deliberate: the need is real and stays visible, reported as unmet.
    Dropping it would hide what the user asked for, and widening the pool to
    "something nearby" would be inventing a requirement.
    """
    from app.catalog.selection import select_candidates

    scope, project_type = _scope(index, intent)
    plans: list[RequirementPlan] = []
    for need in needs:
        plan = RequirementPlan(need, need.description, need.quantity)
        for slug in need.slugs:
            for product in select_candidates(
                index, slug, scope=scope, project_type=project_type, area_m2=area
            )[:limit]:
                offers = product.purchasable_offers
                if not offers:
                    continue
                offer = offers[0]
                plan.candidates.append(
                    Candidate(
                        product,
                        requirement_role=need.role,
                        price=int(offer.price),
                        offer_id=offer.id,
                        seller_name=offer.seller.name,
                    )
                )
            if plan.candidates:
                # The first subcategory that yields anything is the one this need
                # is answered from; the rest stay in reserve rather than widening
                # the choice into unrelated products.
                break
        # Complements come from the file's own declared relationships, for a
        # *different* subcategory, and are room-filtered like anything else. A
        # second product of the same subcategory is an alternative, so it can
        # never enter this pool.
        from app.catalog.selection import complementary_subcategories_for, select_candidates

        for slug in need.slugs:
            for other_slug in complementary_subcategories_for(index, slug):
                for product in select_candidates(
                    index, other_slug, scope=scope, project_type=project_type, area_m2=area
                )[:COMPLEMENT_LIMIT]:
                    offers = product.purchasable_offers
                    if not offers:
                        continue
                    offer = offers[0]
                    plan.complements.append(
                        Candidate(
                            product,
                            requirement_role=need.role,
                            price=int(offer.price),
                            offer_id=offer.id,
                            seller_name=offer.seller.name,
                            complementary_for=slug,
                        )
                    )
        plans.append(plan)
    return plans


def _scope(index, intent):
    from app.domains.projects.service import project_scope

    return project_scope(index, intent)


def _role_label(role: str) -> str:
    from app.domains.projects.service import role_label

    return role_label(role)


# --------------------------------------------------------------------------- #
# Prompt payload
# --------------------------------------------------------------------------- #
def _metadata_of(product) -> dict[str, Any]:
    meta = product.metadata or {}
    out: dict[str, Any] = {}
    for key in _METADATA_FIELDS:
        value = meta.get(key)
        if value:
            out[key] = list(value) if isinstance(value, (list, tuple, set)) else value
    return out


def _candidate_payload(candidate: Candidate, *, in_basket: bool) -> dict[str, Any]:
    product = candidate.product
    return {
        "id": str(product.id),
        "name": product.name,
        "subcategory": product.subcategory,
        "subcategory_label": _subcategory_label(product.subcategory),
        "brand": product.brand,
        "price_toman": candidate.price,
        "seller": candidate.seller_name,
        "requirement_role": candidate.requirement_role,
        "in_basket": in_basket,
        "metadata": _metadata_of(product),
    }


def _subcategory_label(slug: str) -> str:
    from app.catalog.store import subcategory_label

    try:
        return subcategory_label(slug)
    except Exception:  # pragma: no cover - a slug the file does not label
        return slug


def project_payload(
    *,
    intent,
    plans: list[RequirementPlan],
    area: float | None,
    quality: Quality,
    style: str | None,
    budget: int | None,
    basket_items: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """The whole project, and only the candidates cleared for it."""
    # Everything here is about to be JSON, and a value read from a Numeric column
    # arrives as a Decimal, which json refuses. The area is the one that does:
    # when the user gives no area it falls back to the template's default, so a
    # project asked without a size used to fail to render its own prompt.
    area_value = float(area) if area is not None else None
    in_basket = {str(item["product_id"]) for item in basket_items}
    # A product already offered as a candidate for some requirement does not need
    # repeating as a complement. Dropping the duplicates keeps the prompt — and
    # therefore the cost — proportional to the actual decision.
    already = {str(c.product.id) for plan in plans for c in plan.candidates}
    complements = [
        candidate
        for plan in plans
        for candidate in plan.complements
        if str(candidate.product.id) not in already
    ]
    return {
        "project": {
            "room": intent.room,
            "project_type": intent.project_type.value if intent.project_type else None,
            "area_m2": area_value,
            "quality": quality.value if quality is not None else None,
            "style": style,
            "budget_toman": int(budget) if budget is not None else None,
        },
        "requirements": [
            {
                "role": plan.role,
                "label": plan.label,
                "subcategory": plan.slug,
                "quantity": plan.quantity,
                "required": bool(plan.need.required),
                "quality_min": plan.need.quality_min.value,
            }
            for plan in plans
        ],
        "candidates": [
            _candidate_payload(candidate, in_basket=str(candidate.product.id) in in_basket)
            for plan in plans
            for candidate in plan.candidates
        ],
        "complementary_candidates": [
            dict(
                _candidate_payload(candidate, in_basket=False),
                complements_subcategory=candidate.complementary_for,
            )
            for candidate in complements
        ],
        "basket": [
            {
                "product_id": str(item["product_id"]),
                "name": item["name"],
                "subcategory": item["subcategory"],
                "price_toman": item["unit_price"],
                "quantity": item["quantity"],
                "role": item["role"],
            }
            for item in basket_items
        ],
    }


# --------------------------------------------------------------------------- #
# Validation — the model cannot widen its own candidate set
# --------------------------------------------------------------------------- #
class ReasoningOutcome:
    """What survived validation, plus enough detail to explain what did not."""

    __slots__ = (
        "ran",
        "error",
        "selections",
        "reasons",
        "complementary",
        "basket_actions",
        "budget_assessment",
        "explanations",
        "rejected",
    )

    def __init__(self) -> None:
        #: True only when the model answered and its answer was validated. When
        #: False the selections are empty, and the caller must say so rather than
        #: present the deterministic answer as if the model had agreed with it.
        self.ran: bool = False
        #: the failure that stopped it, for the log and for the response
        self.error: str | None = None
        #: requirement role -> the candidate the model chose
        self.selections: dict[str, Candidate] = {}
        #: requirement role -> the model's own words for that choice
        self.reasons: dict[str, str] = {}
        self.complementary: list[tuple[str, Candidate]] = []
        self.basket_actions: list[BasketAction] = []
        self.budget_assessment: BudgetAssessment = BudgetAssessment(status="no_budget")
        self.explanations: list[str] = []
        self.rejected: list[str] = []


def _allowed_candidates(plans: list[RequirementPlan]) -> dict[str, Candidate]:
    return {str(c.product.id): c for plan in plans for c in plan.candidates}


def _validate(
    response: ProjectReasoningResponse,
    plans: list[RequirementPlan],
    basket_ids: set[str],
) -> ReasoningOutcome:
    outcome = ReasoningOutcome()
    allowed = _allowed_candidates(plans)
    role_of = {plan.role: plan for plan in plans}
    seen_roles: set[str] = set()

    for selection in response.selections:
        product_id = selection.product_id.strip()
        plan = role_of.get(selection.requirement_role)
        if plan is None:
            outcome.rejected.append(f"unknown requirement {selection.requirement_role!r}")
            continue
        candidate = allowed.get(product_id)
        if candidate is None:
            # the model named something it was never offered
            outcome.rejected.append(
                f"product {product_id} is not in the candidate set for {selection.requirement_role!r}"
            )
            continue
        if candidate.requirement_role != selection.requirement_role:
            outcome.rejected.append(
                f"product {product_id} was offered for {candidate.requirement_role!r}, "
                f"not {selection.requirement_role!r}"
            )
            continue
        if selection.requirement_role in seen_roles:
            continue
        seen_roles.add(selection.requirement_role)
        outcome.selections[selection.requirement_role] = candidate
        if selection.reason:
            outcome.reasons[selection.requirement_role] = selection.reason

    # Looked up inside the requirement's own pool. A product that complements one
    # requirement is not thereby a complement to another, so the pool is not
    # flattened across the project.
    for pick in response.complementary:
        plan = role_of.get(pick.requirement_role)
        product_id = pick.product_id.strip()
        candidate = next(
            (
                c
                for c in (plan.complements if plan is not None else ())
                if str(c.product.id) == product_id
            ),
            None,
        )
        if plan is None or candidate is None:
            # either an unknown requirement, or a product that was never offered
            # as a complement — an alternative cannot become one by being asked
            outcome.rejected.append(
                f"complementary {product_id} is not a declared complement of "
                f"{pick.requirement_role!r}"
            )
            continue
        if candidate.complementary_for != plan.slug:
            outcome.rejected.append(
                f"complementary {product_id} does not go with {plan.slug!r}"
            )
            continue
        chosen = outcome.selections.get(pick.requirement_role)
        if chosen is not None and str(chosen.product.id) == product_id:
            outcome.rejected.append(
                f"complementary {product_id} is the requirement's own selection"
            )
            continue
        outcome.complementary.append((pick.requirement_role, candidate))

    for action in response.basket_actions:
        current = action.current_product_id.strip()
        if current not in basket_ids:
            outcome.rejected.append(f"basket action for unknown basket item {current}")
            continue
        if action.action == "replace":
            replacement = (action.replacement_product_id or "").strip()
            candidate = allowed.get(replacement)
            if candidate is None:
                outcome.rejected.append(
                    f"replacement {replacement} is not in the candidate set"
                )
                continue
        outcome.basket_actions.append(action)

    outcome.budget_assessment = response.budget_assessment
    outcome.explanations = list(response.explanations)
    return outcome


# --------------------------------------------------------------------------- #
# The calls
# --------------------------------------------------------------------------- #
def reason_project(
    *,
    intent,
    plans: list[RequirementPlan],
    area: float | None,
    quality: Quality,
    style: str | None,
    budget: int | None,
    basket_items: list[Mapping[str, Any]],
) -> tuple[ProjectReasoningResponse | None, ReasoningOutcome]:
    """
    One call about the whole project. Returns the validated outcome.

    A project with nothing to choose between costs no call at all: if every
    requirement has a single candidate and the basket is empty, the deterministic
    order is already the only answer there is.
    """
    basket_ids = {str(item["product_id"]) for item in basket_items}
    has_choice = any(len(plan.candidates) > 1 for plan in plans) or bool(basket_items)
    total_candidates = sum(len(plan.candidates) for plan in plans)
    if not has_choice:
        logger.info(
            "project.reasoning reason=no_choice candidates=%s basket_items=%s call=false",
            total_candidates,
            len(basket_items),
        )
        outcome = _validate(ProjectReasoningResponse(), plans, basket_ids)
        outcome.error = None
        return None, outcome

    from app.llm import chat_json

    payload = project_payload(
        intent=intent,
        plans=plans,
        area=area,
        quality=quality,
        style=style,
        budget=budget,
        basket_items=basket_items,
    )
    try:
        raw = chat_json(
            system=PROJECT_SYSTEM_PROMPT,
            user=_render(payload),
            schema_model=ProjectReasoningResponse,
        )
        response = ProjectReasoningResponse.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 - a model problem must not break a project
        # The message and traceback are logged, not just the class: a bare type
        # name is not enough to tell a bad reply from a bad request, and that is
        # how this failure went uninvestigated.
        logger.warning(
            "project.reasoning reason=candidate_selection call=true candidates=%s "
            "basket_items=%s selected=none status=failed error=%s detail=%s",
            total_candidates,
            len(basket_items),
            type(exc).__name__,
            str(exc)[:300],
            exc_info=True,
        )
        outcome = _validate(ProjectReasoningResponse(), plans, basket_ids)
        outcome.error = f"{type(exc).__name__}: {str(exc)[:200]}"
        return None, outcome

    outcome = _validate(response, plans, basket_ids)
    outcome.ran = True
    logger.info(
        "project.reasoning reason=candidate_selection call=true candidates=%s "
        "basket_items=%s selected=%s complementary=%s rejected=%s status=ok",
        total_candidates,
        len(basket_items),
        sorted(str(c.product.id) for c in outcome.selections.values()),
        [str(c.product.id) for _, c in outcome.complementary],
        len(outcome.rejected),
    )
    return response, outcome


def reason_optimization(
    *,
    intent,
    basket_items: list[Mapping[str, Any]],
    candidates_by_item: Mapping[str, list[Candidate]],
    area: float | None,
    quality: Quality,
    budget: int | None,
    style: str | None,
) -> tuple[OptimizationReasoningResponse | None, OptimizationReasoningResponse, list[str]]:
    """
    One call about the user's own basket. Returns the validated actions and the
    ids that were refused.

    The model only ever sees the current basket and the alternatives the backend
    cleared for it. Nothing is added: the basket is the user's, and a proposal
    that the user declines leaves it untouched.
    """
    basket_ids = {str(item["product_id"]) for item in basket_items}
    has_choice = any(
        len([c for c in candidates_by_item.get(str(i["product_id"]), [])]) > 0
        for i in basket_items
    )
    if not basket_items or not has_choice:
        logger.info(
            "basket.optimize reason=no_alternatives basket_items=%s call=false",
            len(basket_items),
        )
        return None, OptimizationReasoningResponse(), []

    from app.llm import chat_json

    payload = {
        "project": {
            "room": intent.room,
            "project_type": intent.project_type.value if intent.project_type else None,
            "area_m2": float(area) if area is not None else None,
            "quality": quality.value if quality is not None else None,
            "style": style,
            "budget_toman": int(budget) if budget is not None else None,
        },
        "basket": [
            {
                "product_id": str(item["product_id"]),
                "name": item["name"],
                "subcategory": item["subcategory"],
                "price_toman": item["unit_price"],
                "quantity": item["quantity"],
                "role": item["role"],
                "alternatives": [
                    _candidate_payload(c, in_basket=False)
                    for c in candidates_by_item.get(str(item["product_id"]), [])
                ],
            }
            for item in basket_items
        ],
    }

    allowed = {
        str(c.product.id) for group in candidates_by_item.values() for c in group
    }
    try:
        raw = chat_json(
            system=OPTIMIZATION_SYSTEM_PROMPT,
            user=_render(payload),
            schema_model=OptimizationReasoningResponse,
        )
        response = OptimizationReasoningResponse.model_validate(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "basket.optimize reason=optimization call=true basket_items=%s alternatives=%s "
            "actions=none status=failed error=%s",
            len(basket_items),
            len(allowed),
            type(exc).__name__,
        )
        return None, OptimizationReasoningResponse(), []

    rejected: list[str] = []
    kept: list[OptimizationAction] = []
    for action in response.actions:
        current = action.current_product_id.strip()
        if current not in basket_ids:
            rejected.append(f"action for unknown basket item {current}")
            continue
        if action.action == "replace":
            replacement = (action.replacement_product_id or "").strip()
            if replacement not in allowed:
                rejected.append(f"replacement {replacement} is not a cleared alternative")
                continue
        kept.append(action)

    logger.info(
        "basket.optimize reason=optimization call=true basket_items=%s alternatives=%s "
        "actions=%s rejected=%s status=ok",
        len(basket_items),
        len(allowed),
        [f"{a.action}:{a.current_product_id}" for a in kept],
        rejected[:5],
    )
    return response, OptimizationReasoningResponse(
        actions=kept,
        budget_assessment=response.budget_assessment,
        explanations=response.explanations,
    ), rejected


def _render(payload: Mapping[str, Any]) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
