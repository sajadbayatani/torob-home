"""Sellers API, derived from the catalogue.

There is no seller table: sellers exist only as the `shop_name` of an offer in
`data/catalog/products.json`, so they are projected out of the catalogue rather
than stored. A seller id is Torob's own numeric ``shop_id``.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import ApiError
from app.catalog import projections
from app.catalog.store import CatalogError, get_catalog
from app.domains.sellers.schemas import OfferOut, SellerDetail, SellerOut

router = APIRouter(prefix="/sellers", tags=["sellers"])

MAX_OFFERS = 20


def _catalog():
    try:
        return get_catalog()
    except CatalogError as exc:
        raise ApiError(exc.message, exc.status_code) from exc


def _collect():
    """Every seller in the catalogue, with the offers they are known for."""
    index = _catalog()
    sellers: dict[str, dict] = {}
    for product in index.products:
        for offer in product.offers:
            entry = sellers.setdefault(
                offer.seller.id,
                {"seller": offer.seller, "offers": [], "products": 0},
            )
            if offer.seller.name:
                entry["seller"] = offer.seller
            entry["offers"].append((product, offer))
    return sellers


@router.get("", response_model=list[SellerOut], summary="فروشندگان موجود در کاتالوگ")
def sellers() -> list[SellerOut]:
    entries = _collect()
    out = [
        SellerOut(id=entry["seller"].id, slug=entry["seller"].id, name=entry["seller"].name,
                  city=entry["seller"].city, is_demo=False)
        for entry in entries.values()
        if entry["seller"].name
    ]
    out.sort(key=lambda s: s.name)
    return out


@router.get(
    "/{seller_id}",
    response_model=SellerDetail,
    summary="جزئیات فروشنده و محصولات قابل ارائه",
)
def seller_detail(
    seller_id: str,
    limit: int = Query(50, ge=1, le=200),
) -> SellerDetail:
    entry = _collect().get(seller_id)
    if entry is None:
        raise ApiError("فروشنده پیدا نشد.", 404)
    offers = sorted(entry["offers"], key=lambda pair: pair[1].price)[:limit]
    return SellerDetail(
        id=entry["seller"].id,
        slug=entry["seller"].id,
        name=entry["seller"].name,
        city=entry["seller"].city,
        description_fa=None,
        is_demo=False,
        offer_count=len(entry["offers"]),
        products=[
            {
                "id": str(product.id),
                "slug": str(product.id),
                "name": product.name,
                "price": int(offer.price),
                "availability": offer.availability,
            }
            for product, offer in offers
        ],
    )


@router.get(
    "/offers/search",
    response_model=list[OfferOut],
    summary="پیشنهادهای فروشندگان در کاتالوگ",
)
def seller_offers(
    product_id: str | None = Query(None, description="شناسهٔ محصول در کاتالوگ"),
    seller_id: str | None = Query(None, description="شناسهٔ فروشنده در کاتالوگ"),
    only_available: bool = False,
    limit: int = Query(100, ge=1, le=500),
) -> list[OfferOut]:
    index = _catalog()
    products = [index.get(product_id)] if product_id else index.products
    out: list[OfferOut] = []
    for product in products:
        if product is None:
            raise ApiError("محصول پیدا نشد.", 404)
        for offer in product.offers:
            if seller_id and offer.seller.id != seller_id:
                continue
            if only_available and not offer.available:
                continue
            out.append(projections.offer_out(offer))
    out.sort(key=lambda o: o.price)
    return out[:limit]
