"""Complementary products: the LLM picks, the catalogue decides.

The rule that makes this safe is the order of operations:

1. the **backend** selects a small, bounded candidate set from real catalogue
   products;
2. the LLM sees **only those candidates**, as ``id`` + a few factual fields;
3. the LLM returns **product ids** with a short reason each;
4. the backend **validates every returned id against the catalogue** and drops
   anything unknown, duplicated, or out of order.

So an id the model invents has nowhere to land: it is discarded before the
response is built. When no key is configured, or the call fails, the answer is an
empty list with a reason — never a guess.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.catalog.selection import (
    RoomScope,
    complementary_slugs,
    rooms_of,
    scope_for_rooms,
)
from app.catalog.store import CatalogIndex, CatalogProduct, subcategory_label
from app.core.config import get_settings
from app.llm import LLMUnavailable, chat_json, is_configured

logger = logging.getLogger("home_procurement.complementary")

#: Why a subcategory could plausibly go with this one. Used to build the
#: candidate pool, never presented as a catalogue fact.
COMPLEMENT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # a washbasin is used with a faucet
    ("sink", ("sink-faucet", "bathroom-mirror", "toilet")),
    ("sink-faucet", ("sink", "bathroom-mirror", "toilet-faucet")),
    ("bathroom-mirror", ("sink", "sink-faucet")),
    ("toilet", ("toilet-faucet", "sink")),
    ("toilet-faucet", ("toilet", "sink-faucet")),
    # kitchen pairings
    ("kitchen-sink", ("kitchen-faucet", "cooktop", "built-in-oven")),
    ("kitchen-faucet", ("kitchen-sink", "kitchen-hood")),
    ("kitchen-hood", ("cooktop", "built-in-oven", "kitchen-sink")),
    ("cooktop", ("built-in-oven", "kitchen-hood")),
    ("built-in-oven", ("cooktop", "kitchen-hood")),
    ("refrigerator", ("washing-machine", "dishwasher", "kitchen-hood")),
    ("washing-machine", ("refrigerator", "dishwasher")),
    ("dishwasher", ("refrigerator", "kitchen-sink")),
    ("microwave", ("refrigerator", "cooktop")),
    ("television", ("sofa",)),
    ("sofa", ("television", "dining-table")),
    ("dining-table", ("dining-chair",)),
    ("dining-chair", ("dining-table",)),
    ("bed", ("wardrobe", "sofa")),
    ("wardrobe", ("bed",)),
    ("desk", ("wardrobe",)),
)

#: same rules, keyed for lookup
COMPLEMENTS: dict[str, tuple[str, ...]] = dict(COMPLEMENT_RULES)


@dataclass(frozen=True)
class Candidate:
    """One product the LLM is allowed to choose."""

    id: str
    name: str
    subcategory: str
    subcategory_fa: str
    brand: str | None
    model: str | None
    min_price: int
    group: str  # "complement", "same_kind" or "same_room"


@dataclass(frozen=True)
class Complementary:
    """One validated recommendation."""

    product: CatalogProduct
    reason: str
    source: str  # "llm" or "heuristic"


@dataclass(frozen=True)
class ComplementaryResult:
    items: tuple[Complementary, ...]
    available: bool
    #: why the list is empty, in Persian, for the UI
    note: str | None
    candidate_count: int
    discarded_ids: tuple[str, ...] = ()


def _offer_price(product: CatalogProduct) -> int:
    offers = product.purchasable()
    return min((offer.price for offer in offers), default=product.min_price)


def build_candidate_pool(
    index: CatalogIndex,
    product: CatalogProduct,
    limit: int,
    *,
    scope: RoomScope | None = None,
) -> list[Candidate]:
    """
    The bounded set the LLM may choose from.

    Two things decide membership, both read from the catalogue: which
    subcategories the file says go with this product, and which rooms this
    product belongs to. A complement has to be both — the pairing table is
    written product-against-product and knows nothing about which room the
    project is in, so a bedroom's pairings are followed only as far as other
    bedroom products.

    The product itself and anything in its own subcategory are excluded: those
    are *similar* products, not complements, and the sections are separate.
    """
    settings = get_settings()
    limit = max(1, limit or settings.complementary_candidate_limit)
    room_scope = scope or scope_for_rooms(product.metadata.get("rooms") or ())

    # What complements this product is a fact about the product, recorded in the
    # catalogue. It used to come from a table written here, which is why a
    # product could be offered things the file never said went with it.
    wanted = complementary_slugs(product) or COMPLEMENTS.get(product.subcategory, ())
    groups: list[tuple[str, list[CatalogProduct]]] = [
        ("complement", []),
        ("same_room", []),
    ]
    complement_slugs = set(wanted)
    for slug in wanted:
        groups[0][1].extend(
            p
            for p in index.subcategories_of(slug)
            if p.id != product.id and room_scope.admits(p)
        )
    # Only when the file names no complement at all. Otherwise this filled the
    # pool with everything in the top-level category, which for furniture meant
    # sofas, dining tables, chairs and desks being offered for a bedroom.
    if not wanted:
        groups[1][1].extend(
            p
            for p in index.iter_category(product.category)
            if p.id != product.id
            and p.subcategory not in complement_slugs
            and room_scope.admits(p)
        )

    pool: list[Candidate] = []
    seen: set[str] = set()
    for group, products in groups:
        for candidate in products:
            if candidate.id in seen:
                continue
            seen.add(candidate.id)
            pool.append(
                Candidate(
                    id=str(candidate.id),
                    name=candidate.name,
                    subcategory=candidate.subcategory,
                    subcategory_fa=candidate.subcategory_name,
                    brand=candidate.brand,
                    model=candidate.model,
                    min_price=_offer_price(candidate),
                    group=group,
                )
            )
            if len(pool) >= limit:
                return pool
    return pool


SYSTEM_PROMPT = """تو دستیار یک فروشگاه لوازم خانگی فارسی هستی.

وظیفه: از میان «نامزدهای» داده‌شده، محصولات **مکمل** محصول اصلی را انتخاب کنی.

قواعد سخت:
- فقط و فقط از نامزدهای داده‌شده انتخاب کن. هرگز محصولی خارج از این فهرست نساز.
- فقط `id` برگردان. نام محصول را خودت ننویس؛ نام از فهرست نامزدها خوانده می‌شود.
- اگر نامزدی واقعاً مکمل نیست، انتخابش نکن. کمتر بهتر است.
- برای هر انتخاب یک `reason` کوتاه و **واقعی** بنویس (حداکثر ۱۲ کلمه) که فقط بگوید
  این محصول چرا کنار محصول اصلی به کار می‌آید. ادعای سازگاری فنی، برند یا قیمت نکن.
- بین ۰ تا ۵ مورد برگردان.

خروجی فقط و فقط یک JSON object با این ساختار باشد:
{"items":[{"id":"<id از فهرست>","reason":"<دلیل کوتاه فارسی>"}]}"""


def _user_prompt(product: CatalogProduct, pool: list[Candidate]) -> str:
    lines = [
        "محصول اصلی:",
        f"- id: {product.id}",
        f"- نام: {product.name}",
        f"- دسته: {product.subcategory_name}",
        f"- برند: {product.brand or '—'}",
        f"- کمترین قیمت: {product.min_price} تومان",
        "",
        f"نامزدها ({len(pool)} مورد):",
    ]
    for candidate in pool:
        lines.append(
            f"- id: {candidate.id} | دسته: {candidate.subcategory_fa} | نام: {candidate.name}"
            f" | برند: {candidate.brand or '—'} | قیمت: {candidate.min_price}"
            f" | گروه: {candidate.group}"
        )
    lines += [
        "",
        "از بین این نامزدها، مکمل‌های واقعی محصول اصلی را انتخاب کن.",
    ]
    return "\n".join(lines)


def _heuristic_pairs(
    index: CatalogIndex, product: CatalogProduct, exclude: set[UUID] | None = None
) -> list[Complementary]:
    """
    The no-LLM path: catalogue pairings only, with a factual reason.

    This never guesses a product — it uses the same rules the model is given,
    and says only what the catalogue itself shows. `exclude` holds products the
    caller already has, so the cheapest *remaining* one is offered instead of
    something already on the list.
    """
    skip = {product.id} | (exclude or set())
    out: list[Complementary] = []
    for slug in COMPLEMENTS.get(product.subcategory, ()):
        products = [p for p in index.subcategories_of(slug) if p.id not in skip]
        if not products:
            continue
        cheapest = min(products, key=_offer_price)
        out.append(
            Complementary(
                product=cheapest,
                reason=f"در کاتالوگ، {subcategory_label(slug)} هم در همین دسته کاربرد دارد.",
                source="heuristic",
            )
        )
    return out


def _parse_selection(
    payload: dict,
    index: CatalogIndex,
    pool: list[Candidate],
) -> tuple[list[Complementary], tuple[str, ...]]:
    """
    Turn the model's reply into recommendations, or into nothing.

    Every id is looked up in the catalogue. Unknown, duplicate and out-of-pool ids
    are discarded and reported separately, so the caller can say how many were
    dropped without trusting any of them.
    """
    by_id = {candidate.id: candidate for candidate in pool}
    seen: set[str] = set()
    out: list[Complementary] = []
    discarded: list[str] = []

    # a model can return any JSON, so the shape is checked before it is read
    if not isinstance(payload, dict):
        return [], ()

    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        return [], ()

    for entry in raw_items[: get_settings().complementary_max_results * 3]:
        if not isinstance(entry, dict):
            continue
        raw_id = entry.get("id") or entry.get("product_id")
        if not isinstance(raw_id, str) or not raw_id.strip():
            continue
        candidate_id = raw_id.strip()
        # the model may echo the id with different casing
        candidate = by_id.get(candidate_id) or by_id.get(candidate_id.lower())
        product = index.get(candidate_id)
        if candidate is None or product is None:
            # not in the pool, or not a real catalogue product: discard
            discarded.append(candidate_id)
            continue
        if str(product.id) in seen:
            continue
        reason = entry.get("reason")
        reason = reason.strip() if isinstance(reason, str) and reason.strip() else ""
        if not reason:
            # no reason means no claim we can make
            discarded.append(candidate_id)
            continue
        seen.add(str(product.id))
        out.append(Complementary(product=product, reason=reason[:160], source="llm"))

    return out[: get_settings().complementary_max_results], tuple(discarded)


def complementary_products(
    index: CatalogIndex, product: CatalogProduct
) -> ComplementaryResult:
    """
    Complementary products for one catalogue product.

    Uses the LLM when it is configured, and the catalogue's own pairings
    otherwise. Both paths can only return products that exist.
    """
    settings = get_settings()
    pool = build_candidate_pool(index, product, settings.complementary_candidate_limit)

    if not pool:
        return ComplementaryResult(
            items=(),
            available=is_configured(),
            note="در کاتالوگ برای این دسته محصول مکملی ثبت نشده است.",
            candidate_count=0,
        )

    if not is_configured():
        return ComplementaryResult(
            items=tuple(_heuristic_pairs(index, product)),
            available=False,
            note=(
                "کلید OpenRouter تنظیم نشده است، بنابراین پیشنهاد مکمل فقط بر پایهٔ "
                "جفت‌های خودِ کاتالوگ ساخته شده است."
            ),
            candidate_count=len(pool),
        )

    try:
        payload = chat_json(
            system=SYSTEM_PROMPT,
            user=_user_prompt(product, pool),
            schema_model=_ComplementAnswer,
        )
    except LLMUnavailable as exc:
        logger.info("complementary selection fell back: %s", exc)
        return ComplementaryResult(
            items=tuple(_heuristic_pairs(index, product)),
            available=False,
            note="سرویس پیشنهاد مکمل در دسترس نبود؛ فهرست بر پایهٔ کاتالوگ ساخته شد.",
            candidate_count=len(pool),
        )

    items, discarded = _parse_selection(payload, index, pool)
    if not items:
        return ComplementaryResult(
            items=(),
            available=True,
            note="از میان نامزدهای کاتالوگ، مکمل مطمئنی انتخاب نشد.",
            candidate_count=len(pool),
            discarded_ids=discarded,
        )
    return ComplementaryResult(
        items=tuple(items),
        available=True,
        note=None,
        candidate_count=len(pool),
        discarded_ids=discarded,
    )


# --------------------------------------------------------------------------- #
# a whole project
# --------------------------------------------------------------------------- #
class _ComplementItem(BaseModel):
    """One chosen candidate, by catalogue id."""

    model_config = ConfigDict(extra="forbid")

    id: str
    reason: str = ""


class _ComplementAnswer(BaseModel):
    """The shape a complementary reply must have; validated again by the parser."""

    model_config = ConfigDict(extra="forbid")

    items: list[_ComplementItem] = Field(default_factory=list)


PROJECT_SYSTEM_PROMPT = """تو دستیار یک فروشگاه لوازم خانگی فارسی هستی.

وظیفه: از میان «نامزدهای» داده‌شده، محصولات **مکملِ کلِ پروژه** را انتخاب کنی؛ یعنی
اقلامی که در کنار محصولاتِ از پیش انتخاب‌شدهٔ پروژه، خانه را کامل‌تر می‌کنند.

قواعد سخت:
- فقط و فقط از نامزدهای داده‌شده انتخاب کن. هرگز محصولی خارج از این فهرست نساز.
- فقط `id` برگردان. نام محصول را خودت ننویس؛ نام از فهرست نامزدها خوانده می‌شود.
- اگر نامزدی واقعاً مکمل نیست، انتخابش نکن. کمتر بهتر است.
- برای هر انتخاب یک `reason` کوتاه و **واقعی** بنویس (حداکثر ۱۲ کلمه) که فقط بگوید
  این محصول چرا در کنار بقیهٔ پروژه به کار می‌آید. ادعای سازگاری فنی، برند یا قیمت نکن.
- بین ۰ تا ۶ مورد برگردان.

خروجی فقط و فقط یک JSON object با این ساختار باشد:
{"items": [{"id": "<uuid>", "reason": "<دلیل کوتاه فارسی>"}]}

هیچ متنی بیرون از JSON ننویس."""


@dataclass(frozen=True, slots=True)
class ProjectComplement:
    """One complement of a whole project, with the role it would fill."""

    product: CatalogProduct
    reason: str
    source: str


@dataclass(frozen=True, slots=True)
class ProjectComplementaryResult:
    items: tuple[ProjectComplement, ...]
    available: bool
    note: str | None
    candidate_count: int
    discarded_ids: tuple[str, ...] = ()


def build_project_candidate_pool(
    index: CatalogIndex,
    products: list[CatalogProduct],
    limit: int,
    *,
    scope: RoomScope | None = None,
) -> list[Candidate]:
    """
    One bounded pool for a whole project.

    The same rules as a single product, applied to every product the project
    already has, then de-duplicated. A complement must belong to a room the
    project's own products belong to, which is what keeps a bedroom from being
    offered a dining table. `group` records which pairing asked for the candidate
    so the prompt can show the model why it is there.
    """
    seen: set[UUID] = {p.id for p in products}
    # A second bed is an *alternative* bed, not something that goes with one. The
    # project already covers these roles, so offering more of the same is
    # presenting an alternative as a complement.
    covered: set[str] = {p.subcategory for p in products}
    pool: list[Candidate] = []
    ordered: list[Candidate] = []
    room_scope = scope or scope_for_rooms(rooms_of(products))

    for product in products:
        ordered.extend(build_candidate_pool(index, product, limit, scope=room_scope))

    # complements first (they are the point of the section), then same-room
    for group in ("complement", "same_room"):
        for candidate in ordered:
            if candidate.group != group or candidate.id in seen:
                continue
            if candidate.subcategory in covered:
                continue
            seen.add(candidate.id)
            pool.append(candidate)
            if len(pool) >= max(limit, 1):
                return pool
    return pool


def _project_user_prompt(products: list[CatalogProduct], pool: list[Candidate]) -> str:
    lines = ["محصولاتِ از پیش انتخاب‌شدهٔ پروژه:"]
    for product in products:
        lines.append(f"- id: {product.id} | نام: {product.name} | دسته: {product.subcategory_name}")
    lines += ["", f"نامزدها ({len(pool)} مورد):"]
    for candidate in pool:
        lines.append(
            f"- id: {candidate.id} | دسته: {candidate.subcategory_fa} | نام: {candidate.name}"
            f" | برند: {candidate.brand or '—'} | قیمت: {candidate.min_price}"
            f" | گروه: {candidate.group}"
        )
    lines += ["", "از بین این نامزدها، مکمل‌های واقعیِ کلِ پروژه را انتخاب کن."]
    return "\n".join(lines)


def project_complementary_products(
    index: CatalogIndex, products: list[CatalogProduct]
) -> ProjectComplementaryResult:
    """
    Complements for a whole project, in at most one model call.

    A project has several products, so calling the model per product would cost
    several calls and repeat itself. Here the pools are merged into one bounded
    list and the model is asked once what completes the project; the ids it
    returns are then validated exactly as they are for a single product.
    """
    settings = get_settings()
    if not products:
        return ProjectComplementaryResult((), is_configured(), None, 0)

    pool = build_project_candidate_pool(
        index, products, settings.complementary_candidate_limit
    )
    if not pool:
        return ProjectComplementaryResult(
            (),
            is_configured(),
            "در کاتالوگ برای این پروژه محصول مکملی ثبت نشده است.",
            0,
        )

    if not is_configured():
        return ProjectComplementaryResult(
            tuple(_project_pairs(index, products)),
            False,
            (
                "کلید OpenRouter تنظیم نشده است، بنابراین پیشنهاد مکمل فقط بر پایهٔ "
                "جفت‌های خودِ کاتالوگ ساخته شده است."
            ),
            len(pool),
        )

    try:
        payload = chat_json(
            system=PROJECT_SYSTEM_PROMPT,
            user=_project_user_prompt(products, pool),
            schema_model=_ComplementAnswer,
        )
    except LLMUnavailable as exc:
        logger.info("project complementary selection fell back: %s", exc)
        return ProjectComplementaryResult(
            tuple(_project_pairs(index, products)),
            False,
            "سرویس پیشنهاد مکمل در دسترس نبود؛ فهرست بر پایهٔ کاتالوگ ساخته شد.",
            len(pool),
        )

    items, discarded = _parse_selection(payload, index, pool)
    if not items:
        return ProjectComplementaryResult(
            (),
            True,
            "از میان نامزدهای کاتالوگ، مکمل مطمئنی انتخاب نشد.",
            len(pool),
            discarded,
        )
    return ProjectComplementaryResult(
        tuple(
            ProjectComplement(product=i.product, reason=i.reason, source=i.source)
            for i in items
        ),
        True,
        None,
        len(pool),
        discarded,
    )


def _project_pairs(
    index: CatalogIndex, products: list[CatalogProduct]
) -> list[ProjectComplement]:
    """The no-LLM path for a project: catalogue pairings, de-duplicated."""
    out: list[ProjectComplement] = []
    seen: set[UUID] = {p.id for p in products}
    for product in products:
        # everything the project already has is passed as excluded, so a pairing
        # resolves to a product that is genuinely still missing
        for pair in _heuristic_pairs(index, product, exclude=seen):
            if pair.product.id in seen:
                continue
            seen.add(pair.product.id)
            out.append(
                ProjectComplement(
                    product=pair.product, reason=pair.reason, source=pair.source
                )
            )
    return out


__all__ = [
    "COMPLEMENTS",
    "PROJECT_SYSTEM_PROMPT",
    "ProjectComplement",
    "ProjectComplementaryResult",
    "build_project_candidate_pool",
    "project_complementary_products",
    "COMPLEMENT_RULES",
    "Candidate",
    "Complementary",
    "ComplementaryResult",
    "build_candidate_pool",
    "complementary_products",
]
