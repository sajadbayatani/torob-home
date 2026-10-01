"""Basket service: item management and server-side money maths.

Products and offers are **not** in the database. Every read and write resolves
them through `app.catalog`, which reads `data/catalog/products.json`. An unknown
product id is an error, never a new product, and a price is only ever the price
the catalogue records for the chosen offer.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.catalog import projections
from app.catalog.store import (
    CatalogError,
    CatalogIndex,
    CatalogOffer,
    CatalogProduct,
    get_catalog,
)
from app.domains.basket.models import Basket, BasketItem
from app.domains.basket.schemas import (
    CURRENCY,
    BasketCreateRequest,
    BasketItemCreate,
    BasketItemOut,
    BasketItemUpdate,
    BasketOut,
)
from app.domains.projects.models import ProjectAnalysis


class BasketError(RuntimeError):
    """Domain level error with an HTTP-friendly message."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _catalog() -> CatalogIndex:
    try:
        return get_catalog()
    except CatalogError as exc:
        raise BasketError(exc.message, exc.status_code) from exc


# --------------------------------------------------------------------------- #
# loading
# --------------------------------------------------------------------------- #
def _basket_options() -> tuple:
    return (selectinload(Basket.items),)


def load_basket(session: Session, basket_id: UUID) -> Basket:
    basket = session.scalars(
        select(Basket).where(Basket.id == basket_id).options(*_basket_options())
    ).first()
    if basket is None:
        raise BasketError("فهرست انتخاب‌ها پیدا نشد.", 404)
    return basket


# --------------------------------------------------------------------------- #
# money
# --------------------------------------------------------------------------- #
def compute_total(items: list[BasketItem]) -> int:
    """The only place a basket total is ever computed."""
    return sum(item.line_total for item in items)


def compute_items_count(items: list[BasketItem]) -> int:
    """
    How many products are selected.

    This replaced a sum of item quantities, which asked a question the product does
    not have an answer to. An item is one product on a shortlist, so the count of
    items *is* the count of products.
    """
    return len(items)


# --------------------------------------------------------------------------- #
# serialisation
# --------------------------------------------------------------------------- #
def serialize_basket(session: Session, basket: Basket) -> BasketOut:
    """Build the response, hydrating every item from the catalogue.

    An item whose product has since disappeared from the file is reported as an
    error rather than silently priced at zero.
    """
    index = _catalog()
    items: list[BasketItemOut] = []
    for item in basket.items:
        product = index.get(item.product_id)
        if product is None:
            raise BasketError(
                "یکی از قلم‌های فهرست انتخاب‌ها دیگر در کاتالوگ نیست. فهرست را دوباره بسازید.", 409
            )
        offer = _find_offer(product, item.offer_id)
        if offer is None:
            raise BasketError(
                "پیشنهاد فروشندهٔ یکی از قلم‌های فهرست انتخاب‌ها دیگر در کاتالوگ نیست.", 409
            )
        best_price = min(
            (o.price for o in product.purchasable()), default=offer.price
        )
        alternatives = [
            candidate
            for candidate in index.subcategories_of(product.subcategory)
            if candidate.id != product.id and candidate.min_price < product.min_price
        ]
        alt_prices = [
            candidate.min_price for candidate in alternatives if candidate.min_price < offer.price
        ]
        items.append(
            BasketItemOut(
                id=item.id,
                product=projections.to_product_out(product, offer_limit=3),
                offer=projections.offer_out(offer),
                unit_price=int(item.unit_price),
                line_total=int(item.line_total),
                role=item.role,
                origin=item.origin,
                is_locked=bool(item.is_locked),
                reason=item.reason_fa,
                replaced_item_id=item.replaced_item_id,
                is_best_price=int(item.unit_price) <= best_price,
                best_price=best_price,
                alternative_count=len(alternatives),
                alternative_min_price=min(alt_prices) if alt_prices else None,
            )
        )

    total = compute_total(basket.items)
    project = session.scalar(select(ProjectAnalysis).where(ProjectAnalysis.basket_id == basket.id))
    budget = basket.target_budget
    return BasketOut(
        id=basket.id,
        kind=basket.kind,
        title=basket.title_fa,
        currency=CURRENCY,
        items=items,
        items_count=compute_items_count(items),
        total=total,
        project_id=project.id if project else None,
        target_budget=budget,
        budget_gap=(total - budget) if budget is not None else None,
        within_budget=(total <= budget) if budget is not None else None,
        intent=basket.intent_payload,
        notes=basket.notes_fa,
        created_at=basket.created_at.isoformat(),
        updated_at=basket.updated_at.isoformat(),
    )


def find_item_out(basket: BasketOut, item_id: UUID) -> BasketItemOut:
    for item in basket.items:
        if item.id == item_id:
            return item
    raise BasketError("این قلم در فهرست انتخاب‌ها پیدا نشد.", 404)


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #
def create_basket(
    session: Session, payload: BasketCreateRequest, *, intent: dict | None = None
) -> Basket:
    basket = Basket(
        kind=payload.kind,
        title_fa=payload.title,
        owner_token=payload.owner_token,
        intent_payload=intent,
    )
    session.add(basket)
    session.flush()
    if payload.product_id:
        add_item(
            session,
            basket,
            BasketItemCreate(product_id=payload.product_id),
        )
    session.flush()
    return load_basket(session, basket.id)


def _find_offer(product: CatalogProduct, offer_id: UUID) -> CatalogOffer | None:
    return next((offer for offer in product.offers if offer.id == offer_id), None)


def _require_product(product_id: UUID) -> CatalogProduct:
    product = _catalog().get(product_id)
    if product is None:
        # Never fabricate: an unknown product id is an error, not a new product.
        raise BasketError("محصول موردنظر در کاتالوگ پیدا نشد.", 404)
    return product


def resolve_offer(product: CatalogProduct, offer_id: UUID | None) -> CatalogOffer:
    """The offer to buy from: the named one, else the cheapest purchasable one."""
    offers = list(product.purchasable_offers)
    if not offers:
        raise BasketError("برای این محصول هیچ فروشنده‌ای در کاتالوگ ثبت نشده است.", 404)
    if offer_id is not None:
        chosen = _find_offer(product, offer_id)
        if chosen is None:
            raise BasketError("فروشندهٔ انتخاب‌شده برای این محصول معتبر نیست.", 400)
        return chosen
    purchasable = [offer for offer in offers if offer.available]
    return purchasable[0] if purchasable else offers[0]


def add_item(session: Session, basket: Basket, payload: BasketItemCreate) -> BasketItem:
    product = _require_product(payload.product_id)
    offer = resolve_offer(product, payload.offer_id)

    existing = next(
        (i for i in basket.items if i.product_id == product.id and i.role == payload.role), None
    )
    if existing is not None:
        # Re-adding a product is the same selection, not a second one and not a
        # larger one. What may legitimately change is which offer it is held at.
        existing.offer_id = offer.id
        existing.unit_price = int(offer.price)
        session.flush()
        return existing

    item = BasketItem(
        basket_id=basket.id,
        product_id=product.id,
        offer_id=offer.id,
        unit_price=int(offer.price),
        role=payload.role,
        origin=payload.origin,
        is_locked=payload.is_locked,
        reason_fa=payload.reason,
    )
    basket.items.append(item)
    session.flush()
    return item


def update_item(
    session: Session, basket: Basket, item_id: UUID, payload: BasketItemUpdate
) -> BasketItem:
    item = next((i for i in basket.items if i.id == item_id), None)
    if item is None:
        raise BasketError("این قلم در فهرست انتخاب‌ها پیدا نشد.", 404)

    if payload.is_locked is not None:
        item.is_locked = payload.is_locked
    if payload.reason is not None:
        item.reason_fa = payload.reason
    if payload.role is not None:
        item.role = payload.role
    if payload.offer_id is not None:
        product = _require_product(item.product_id)
        offer = resolve_offer(product, payload.offer_id)
        item.offer_id = offer.id
        item.unit_price = int(offer.price)
    session.flush()
    return item


def remove_item(session: Session, basket: Basket, item_id: UUID) -> None:
    item = next((i for i in basket.items if i.id == item_id), None)
    if item is None:
        raise BasketError("این قلم در فهرست انتخاب‌ها پیدا نشد.", 404)
    basket.items.remove(item)
    session.flush()


def delete_basket(session: Session, basket: Basket) -> None:
    """
    Remove a basket and everything hanging off it.

    A project basket owns a `ProjectAnalysis`, and that analysis is what carries
    the project title and the original query. Deleting only the basket would
    leave the project behind with no items, which is exactly the stale state this
    endpoint is meant to prevent — so the analysis goes too, and the project
    disappears with it.
    """
    analysis = session.scalar(select(ProjectAnalysis).where(ProjectAnalysis.basket_id == basket.id))
    if analysis is not None:
        session.delete(analysis)
        session.flush()
    session.delete(basket)
    session.flush()


def set_target_budget(session: Session, basket: Basket, budget: int | None) -> Basket:
    basket.target_budget = budget
    session.flush()
    return basket
