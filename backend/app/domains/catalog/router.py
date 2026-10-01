"""Catalog API: search, product detail, contextual relations, categories.

Every product, price and seller served here comes from
`data/catalog/products.json` via `app.catalog`. There is no product table, so
none of these endpoints touch the database.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import ApiError
from app.catalog import projections, store
from app.catalog.store import CatalogError, CatalogFilters, subcategory_label
from app.core.enums import Domain
from app.domains.catalog.schemas import (
    BrandOut,
    CategoryOut,
    ComplementaryResponse,
    Facets,
    ProductDetail,
    ProductSearchResponse,
    SimilarProduct,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["catalog"])


def _catalog_or_error():
    try:
        return store.get_catalog()
    except CatalogError as exc:
        raise ApiError(exc.message, exc.status_code) from exc


@router.get(
    "/products/search",
    response_model=ProductSearchResponse,
    summary="جستجوی محصول در کاتالوگ با مقایسهٔ فروشندگان",
    description=(
        "نتایج فقط از کاتالوگ `data/catalog/products.json` می‌آید؛ اگر محصولی در "
        "کاتالوگ نباشد، نتیجه‌ای ساخته نمی‌شود. فروشنده‌های هر محصول حداکثر پنج "
        "فروشندهٔ ارزان‌تر هستند."
    ),
)
async def search_products_endpoint(
    q: str = Query(..., min_length=1, max_length=200, description="متن جستجو"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    domain: Domain | None = None,
    category: str | None = Query(None, description="اسلاگ زیر‌دستهٔ کاتالوگ"),
    brand: str | None = Query(None, description="نام برند، عیناً همان‌طور که در کاتالوگ آمده"),
    only_available: bool = False,
    max_price: int | None = Query(
        None, ge=0, description="سقف بودجه به تومان؛ روی کمترین قیمت قابل خرید اعمال می‌شود"
    ),
    #: Defaults to **false**, and that is the point of this change.
    #:
    #: It used to default to true, so every product search — «شیر توالت» — paid for
    #: a full interpretation to attach one word and a sentence of explanation. The
    #: routing decision is now made deterministically by `app.catalog.matcher`, so
    #: the answer is available without a model. A caller that genuinely wants a
    #: model explanation, rather than the deterministic one, still asks for it.
    interpret: bool = Query(
        False, description="تفسیر نیت جستجو با مدل (هزینه‌بر؛ به‌طور پیش‌فرض خاموش)"
    ),
    #: Which product source answers, overriding PRODUCT_SOURCE for this request.
    #: Additive only: the default is the local file, and the local path below runs
    #: exactly the code it ran before this parameter existed.
    product_source: str | None = Query(
        None, description="جایگزینی موقت PRODUCT_SOURCE برای همین درخواست"
    ),
) -> ProductSearchResponse:
    from app.catalog.sources import (
        LocalJsonProductSource,
        ProductSourceError,
        build_product_source,
    )

    if product_source is not None:
        return await _search_from_named_source(product_source, q, limit, offset, category, domain)
    try:
        source = build_product_source()
    except ProductSourceError as exc:
        raise ApiError(exc.message, 500) from exc
    if not isinstance(source, LocalJsonProductSource):
        return await _search_via_source(source, q, limit, offset, category, domain)

    index = _catalog_or_error()

    # What the query is *about* is decided before anything is filtered, from the
    # file's own labels, and it is a hard constraint rather than a hint. It used to
    # be computed after the search and only reported, so a query that plainly said
    # "washing machine" still returned dishwashers, desks and chairs on the
    # strength of a stray word.
    detected = store.detect_category(index, q)
    # An explicit category is the caller's own choice and outranks a detection.
    resolved_category = category or (detected.slug if detected and detected.decisive else None)
    # An explicit budget outranks one stated in the query.
    resolved_ceiling = max_price if max_price is not None else store.detect_budget_ceiling(q)

    filters = CatalogFilters(
        category=resolved_category,
        top_category=domain.value if domain else None,
        brand=brand or None,
        only_available=only_available,
        max_price=resolved_ceiling,
    )
    matches, total = store.search(
        index, q, filters, limit=limit, offset=offset, detected_category=resolved_category
    )

    detected_category = category or (detected.slug if detected else None)
    detected_domain = domain.value if domain else (detected.top_category if detected else None)

    intent: str | None = None
    explanations: list[str] = []
    if interpret:
        intent, explanations = await _interpret(q)
    else:
        # Free, and honest about where it came from: the same catalogue match that
        # routes the query says what was asked for, without a model.
        intent, explanations = _deterministic_intent(q)

    return projections.build_search_response(
        query=q,
        index=index,
        matches=matches,
        total=total,
        limit=limit,
        offset=offset,
        detected_category=detected_category,
        detected_category_name=(
            subcategory_label(detected_category) if detected_category else None
        ),
        detected_domain=detected_domain,
        intent=intent,
        explanations=explanations,
    )


def _deterministic_intent(query: str) -> tuple[str | None, list[str]]:
    """
    The routing verdict, used as the search's own explanation.

    Same matcher the search router consults, so the search says why it answered
    the way it did without spending an inference. When the catalogue cannot place
    the query it says so and stays silent about intent, which is the truth: it does
    not know.
    """
    from app.catalog.matcher import product_verdict
    from app.catalog.store import get_catalog

    verdict = product_verdict(get_catalog(), query)
    if verdict.is_product:
        return "PRODUCT_SEARCH", ["درخواست شما مستقیماً با کاتالوگ تطبیق داده شد."]
    if verdict.reason == "no_product_words":
        return None, []
    return None, [
        "بخشی از عبارت شما به کالای مشخصی در کاتالوگ نرسید؛ "
        "برای فهم دقیق منظورتان، تفسیر کامل انجام می‌شود."
    ]


async def _interpret(query: str) -> tuple[str | None, list[str]]:
    """
    Intent interpretation stays a backend feature, but never fails a search.

    Awaited rather than run through ``asyncio.run`` because the endpoint is async —
    the product source may be remote — and ``asyncio.run`` cannot be called from
    inside a running loop. It raised, the broad ``except`` below caught it, and the
    model was silently never asked: a search with ``interpret=true`` returned a
    perfectly good answer with no explanation and nobody could tell why.
    """
    from app.db.session import get_session_factory
    from app.domains.search.service import SearchService

    try:
        with get_session_factory()() as session:
            result = await SearchService().interpret(query, session)
        return result.intent.value, list(result.explanations)
    except Exception:  # noqa: BLE001 - a search must not fail over interpretation
        # logged rather than silent: this is a swallowed failure, and a swallowed
        # failure that used to hide a loop error is exactly how that went unnoticed
        logger.warning("interpretation failed for %r; the search answers without it", query)
        return None, []


@router.get("/products/facets", response_model=Facets, summary="گزینه‌های فیلتر کاتالوگ")
def product_facets() -> Facets:
    return projections.build_facets(_catalog_or_error())


@router.get(
    "/products/meta",
    summary="وضعیت کاتالوگ",
    description="تعداد محصولات و ردیف‌های کنارگذاشته‌شده، برای دیدن سلامت فایل.",
)
def product_meta() -> dict:
    index = _catalog_or_error()
    return {
        "source": str(index.source) if index.source else None,
        "products": len(index),
        "subcategories": len(index.subcategories()),
        "brands": len(index.brands()),
        "skipped": [{"name": item.name, "reason": item.reason} for item in index.skipped],
    }


@router.get(
    "/products/{product_id}",
    response_model=ProductDetail,
    summary="جزئیات نرمال‌شدهٔ محصول به همراه فروشندگان",
)
def product_detail(product_id: UUID) -> ProductDetail:
    index = _catalog_or_error()
    product = index.get(product_id)
    if product is None:
        raise ApiError("محصول پیدا نشد.", 404)
    return projections.to_product_detail(product, index)



@router.get(
    "/products/{product_id}/similar",
    response_model=list[SimilarProduct],
    summary="محصولات مشابه از همان دسته (قطعی، بدون LLM)",
    description=(
        "ترتیب کاملاً قطعی است: همان دسته و همان برند، سپس همان دسته، سپس همان "
        "برند در همان دسته‌بندی. همه از کاتالوگ انتخاب می‌شوند."
    ),
)
def product_similar(
    product_id: UUID,
    limit: int = Query(6, ge=1, le=24),
) -> list[SimilarProduct]:
    index = _catalog_or_error()
    product = index.get(product_id)
    if product is None:
        raise ApiError("محصول پیدا نشد.", 404)
    return [projections.to_similar(match) for match in store.similar(index, product, limit)]


@router.get(
    "/products/{product_id}/complementary",
    response_model=ComplementaryResponse,
    summary="محصولات مکمل (انتخاب با LLM از نامزدهای کاتالوگ)",
    description=(
        "بک‌اند ابتدا چند نامزد محدود از کاتالوگ انتخاب می‌کند، مدل فقط همین نامزدها را "
        "می‌بیند و فقط شناسهٔ محصول برمی‌گرداند. هر شناسهٔ ناشناس پیش از پاسخ کنار "
        "گذاشته می‌شود، پس محصول ساختگی هرگز به فرانت‌اند نمی‌رسد."
    ),
)
def product_complementary(
    product_id: UUID,
    limit: int = Query(6, ge=1, le=12),
) -> ComplementaryResponse:
    index = _catalog_or_error()
    product = index.get(product_id)
    if product is None:
        raise ApiError("محصول پیدا نشد.", 404)
    from app.catalog.complementary import complementary_products

    result = complementary_products(index, product)
    response = projections.to_complementary(result)
    return response.model_copy(update={"items": response.items[:limit]})


@router.get("/categories", response_model=list[CategoryOut], summary="زیر‌دسته‌های موجود در کاتالوگ")
def categories(domain: Domain | None = None) -> list[CategoryOut]:
    index = _catalog_or_error()
    counts = dict(index.subcategories())
    out: list[CategoryOut] = []
    for product in index.products:
        if product.subcategory in counts and (domain is None or product.domain == domain.value):
            out.append(projections.category_out(product, counts[product.subcategory]))
    # one entry per subcategory
    seen: set[str] = set()
    unique: list[CategoryOut] = []
    for entry in out:
        if entry.slug in seen:
            continue
        seen.add(entry.slug)
        unique.append(entry)
    return unique


@router.get("/brands", response_model=list[BrandOut], summary="برندهای موجود در کاتالوگ")
def brands() -> list[BrandOut]:
    index = _catalog_or_error()
    return [BrandOut(id=name, slug=name, name=name) for name, _ in index.brands()]


# --------------------------------------------------------------------------- #
# Product sources other than the local file
# --------------------------------------------------------------------------- #
async def _search_from_named_source(
    name: str, q: str, limit: int, offset: int, category: str | None, domain
):
    """
    Serve a request from the source the *caller* named.

    A request parameter is a smaller claim than configuration: it names one
    request, and the deployment's own setting still stands. An unknown name still
    fails, for the same reason it fails in the factory.
    """
    from app.catalog.sources import TorobMcpProductSource
    from app.core.config import get_settings

    choice = name.strip().lower()
    if choice == "local":
        return await _search_via_local_file(q, limit, offset, category, domain)
    if choice == "torob_mcp":
        settings = get_settings()
        source = TorobMcpProductSource(settings.torob_mcp_url)
        return await _search_via_source(source, q, limit, offset, category, domain)
    raise ApiError(
        f"product_source={choice!r} پشتیبانی نمی‌شود. مقادیر مجاز: local | torob_mcp",
        400,
    )


async def _search_via_local_file(q: str, limit: int, offset: int, category, domain):
    """The same response the file-backed path builds, reached directly."""
    index = _catalog_or_error()
    from app.catalog.store import CatalogFilters

    detected = store.detect_category(index, q)
    resolved = category or (detected.slug if detected and detected.decisive else None)
    matches, total = store.search(
        index, q, CatalogFilters(category=resolved, top_category=domain.value if domain else None),
        limit=limit, offset=offset, detected_category=resolved,
    )
    return projections.build_search_response(
        query=q, index=index, matches=matches, total=total, limit=limit, offset=offset,
        detected_category=resolved,
        detected_category_name=subcategory_label(resolved) if resolved else None,
        detected_domain=domain.value if domain else (detected.top_category if detected else None),
        intent=None, explanations=[],
    )


async def _search_via_source(source, q: str, limit: int, offset: int, category, domain):
    """
    Serve the request from a :class:`ProductSource` other than the file.

    The source obtains products; everything after that is the existing projection
    and the existing response shape, so a Torob product is returned exactly as a
    file product is — same ``ProductOut``, same offers handling, same facets code.

    The products are indexed on the fly so the facets and the "N results from M
    products" line describe **what actually answered**, rather than the local file
    that this request did not use. The index is a container here, not a source of
    truth: nothing is read from it except these products.

    Ranking is Torob's own ordering. The local file's scoring reads the enriched
    metadata — rooms, roles, search terms — and none of it exists for a Torob
    product, so applying it would rank everything at zero and invent a rule to break
    the tie. Torob's relevance ordering is real and is used instead of fabricating
    one.
    """
    from app.catalog.sources import ProductSourceError
    from app.catalog.store import CatalogIndex, CatalogMatch

    try:
        products = await source.search(q, category=category, limit=limit + offset)
    except ProductSourceError as exc:
        # Not an empty result and never a silent fall back to the local file: the
        # operator asked for this source, so a failure here is a source failure.
        logger.error("product source failed: %s", exc)
        raise ApiError(f"منبع محصول در دسترس نبود: {exc}", 502) from exc

    page = products[offset : offset + limit]
    index = CatalogIndex(products=list(products))
    matches = [CatalogMatch(product, (), (), 0) for product in page]
    return projections.build_search_response(
        query=q, index=index, matches=matches, total=len(products), limit=limit, offset=offset,
        detected_category=category,
        detected_category_name=subcategory_label(category) if category else None,
        detected_domain=domain.value if domain else None,
        intent=None,
        explanations=[f"{len(products)} نتیجه از منبع محصول «{q}»."],
    )
