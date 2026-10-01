"""Projections: catalogue records -> the API schemas the frontend consumes.

Keeping this separate from `store` means the catalogue's shape and the API's
shape can differ without either leaking into the other. The rule throughout:
**a value the file does not carry stays `None`.** No defaults, no placeholders.
"""

from __future__ import annotations

from app.catalog.store import (
    CatalogIndex,
    CatalogMatch,
    CatalogOffer,
    CatalogProduct,
    category_label,
    subcategory_label,
)
from app.core.enums import CategoryKind, Domain, domain_from
from app.domains.catalog.schemas import (
    AttributeOut,
    BrandOut,
    CategoryOut,
    ComplementaryProduct,
    ComplementaryResponse,
    FacetValue,
    Facets,
    ProductDetail,
    ProductOut,
    ProductSearchItem,
    ProductSearchResponse,
    SimilarProduct,
)
from app.domains.sellers.schemas import OfferOut, SellerOut

#: every catalogue subcategory is a finished product, not a building material
CATEGORY_KIND = CategoryKind.FIXTURE

#: how many offers a product projection carries
DETAIL_OFFER_LIMIT = 5
CARD_OFFER_LIMIT = 3


def _domain(value: str) -> Domain:
    # an unknown top-level category must not break the response
    return domain_from(value) or Domain.BATHROOM


def seller_out(offer: CatalogOffer) -> SellerOut:
    return SellerOut(
        id=offer.seller.id,
        slug=offer.seller.id,
        name=offer.seller.name,
        city=offer.seller.city,
        is_demo=False,
    )


def offer_out(offer: CatalogOffer) -> OfferOut:
    return OfferOut(
        id=offer.id,
        seller=seller_out(offer),
        price=offer.price,
        original_price=None,
        availability=offer.availability,
        available=offer.available,
        stock_count=None,
        delivery_days=None,
        warranty_months=None,
        url=offer.url,
        price_updated_at=offer.price_updated_at,
        is_price_unreliable=offer.is_price_unreliable,
    )


def brand_out(product: CatalogProduct) -> BrandOut | None:
    if not product.brand:
        return None
    return BrandOut(id=product.brand, slug=product.brand, name=product.brand)


def category_out(product: CatalogProduct, product_count: int = 0) -> CategoryOut:
    return CategoryOut(
        id=product.subcategory,
        slug=product.subcategory,
        name=product.subcategory_name,
        domain=_domain(product.category),
        kind=CATEGORY_KIND,
        description_fa=None,
        product_count=product_count,
    )


def attribute_outs(product: CatalogProduct) -> list[AttributeOut]:
    return [
        AttributeOut(
            key=attribute.key,
            label=attribute.label,
            value=attribute.value,
            value_num=attribute.value_num,
            unit=attribute.unit,
        )
        for attribute in product.attributes
    ]


def to_product_out(
    product: CatalogProduct,
    *,
    offer_limit: int = DETAIL_OFFER_LIMIT,
    match_score: float | None = None,
    product_count: int = 0,
) -> ProductOut:
    """Project a catalogue product onto the public product shape."""
    offers = product.purchasable_offers[:offer_limit]
    return ProductOut(
        id=product.id,
        slug=str(product.id),
        name=product.name,
        subtitle=None,
        brand=brand_out(product),
        category=category_out(product, product_count),
        domain=_domain(product.category),
        subcategory=product.subcategory,
        model=product.model,
        image_url=product.image_url,
        source_url=product.source_url,
        quality=None,
        quality_fa=None,
        style=None,
        unit=None,
        rating=None,
        warranty_months=None,
        origin_country=None,
        attributes=attribute_outs(product),
        offers=[offer_out(offer) for offer in offers],
        offers_count=product.offers_count,
        min_price=product.min_price,
        max_price=product.max_price,
        available_offers_count=product.available_offers_count,
        is_demo=False,
        match_score=match_score,
    )


def to_product_detail(product: CatalogProduct, index: CatalogIndex) -> ProductDetail:
    projection = to_product_out(product, offer_limit=DETAIL_OFFER_LIMIT)
    return ProductDetail(
        **projection.model_dump(),
        description=None,
        reference_price=product.min_price,
    )



#: how a "similar" product relates, decided in `app.catalog.store.similar`
SIMILAR_TYPES: dict[int, tuple[str, str]] = {
    400: ("same_subcategory", "همان دسته و همان برند"),
    300: ("same_subcategory", "همان دسته"),
    200: ("same_brand", "همان برند"),
    100: ("same_category", "همان دسته‌بندی"),
}


def to_similar(match: CatalogMatch) -> SimilarProduct:
    """One similar product, with the rule that picked it."""
    match_type, _ = SIMILAR_TYPES.get(match.score, ("same_category", "همان دسته‌بندی"))
    return SimilarProduct(
        product=to_product_out(match.product, offer_limit=1),
        match_type=match_type,
        reason=match.reasons[0] if match.reasons else "از همان دستهٔ کاتالوگ.",
    )


def to_project_complementary(result) -> ComplementaryResponse:
    """Project a whole project's complements; ids already validated.

    Same shape as a single product's, so the frontend reuses one component.
    """
    return ComplementaryResponse(
        items=[
            ComplementaryProduct(
                product_id=item.product.id,
                product=to_product_out(item.product, offer_limit=1),
                reason=item.reason,
                source=item.source,
            )
            for item in result.items
        ],
        llm_available=result.available,
        candidate_count=result.candidate_count,
        note=result.note,
        discarded_ids=list(result.discarded_ids),
    )


def to_complementary(result) -> ComplementaryResponse:
    """Project the complementary result, ids already validated."""
    return ComplementaryResponse(
        items=[
            ComplementaryProduct(
                product_id=item.product.id,
                product=to_product_out(item.product, offer_limit=1),
                reason=item.reason,
                source=item.source,
            )
            for item in result.items
        ],
        llm_available=result.available,
        candidate_count=result.candidate_count,
        note=result.note,
        discarded_ids=list(result.discarded_ids),
    )


def build_facets(index: CatalogIndex) -> Facets:
    """Filter options, counted from the catalogue itself."""
    return Facets(
        categories=[
            FacetValue(value=slug, label=category_label(slug), count=count)
            for slug, count in index.categories()
        ],
        brands=[FacetValue(value=name, label=name, count=count) for name, count in index.brands()],
        subcategories=[
            FacetValue(value=slug, label=subcategory_label(slug), count=count)
            for slug, count in index.subcategories()
        ],
    )


def build_search_response(
    *,
    query: str,
    index: CatalogIndex,
    matches: list[CatalogMatch],
    total: int,
    limit: int,
    offset: int,
    detected_category: str | None = None,
    detected_category_name: str | None = None,
    detected_domain: str | None = None,
    intent: str | None = None,
    explanations: list[str] | None = None,
) -> ProductSearchResponse:
    """Assemble the search response, with explanations that cannot be false."""
    lines = list(explanations or [])
    if matches:
        lines.append(f"{len(matches)} نتیجه از {len(index)} محصول کاتالوگ.")
        lines.append(f"بیشترین تطبیق: «{matches[0].product.name}».")
    else:
        lines.append(f"هیچ محصولی از {len(index)} محصول کاتالوگ با این عبارت تطبیق نداشت.")
    suggestions = [facet.label for facet in build_facets(index).subcategories[:4]]
    return ProductSearchResponse(
        query=query,
        total=total,
        limit=limit,
        offset=offset,
        detected_category=detected_category,
        detected_category_name=detected_category_name,
        detected_domain=_domain(detected_domain) if detected_domain else None,
        intent=intent,
        items=[
            ProductSearchItem(
                product=to_product_out(
                    match.product,
                    offer_limit=CARD_OFFER_LIMIT,
                    match_score=float(match.score),
                ),
                matched_terms=list(match.matched_terms),
                reasons=list(match.reasons),
            )
            for match in matches
        ],
        facets=build_facets(index),
        explanations=lines,
        suggestions=suggestions,
    )


__all__ = [
    "attribute_outs",
    "to_complementary",
    "to_similar",
    "brand_out",
    "build_facets",
    "build_search_response",
    "category_out",
    "offer_out",
    "seller_out",
    "to_product_detail",
    "to_product_out",
]
