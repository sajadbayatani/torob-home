"""Sellers domain schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.core.enums import Availability


class SellerOut(BaseModel):
    """A seller as the catalogue records it.

    The catalogue stores Torob's numeric ``shop_id``, not a UUID, so ``id`` is the
    id as a string. The old seeded sellers are gone.
    """

    id: str
    slug: str
    name: str
    city: str | None = None
    is_demo: bool = False


class OfferOut(BaseModel):
    """One seller offer.

    The catalogue records no stock count, delivery time, warranty or original
    price, so those stay ``None`` and the UI omits them. ``price_updated_at`` is
    the seller's own wording (Torob reports a relative phrase), not a timestamp.
    """

    id: UUID
    seller: SellerOut
    price: int  # Toman
    original_price: int | None = None
    availability: Availability
    available: bool
    stock_count: int | None = None
    delivery_days: int | None = None
    warranty_months: int | None = None
    url: str | None = None
    price_updated_at: str | None = None
    is_price_unreliable: bool = False


class SellerDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    name: str
    city: str | None = None
    description_fa: str | None = None
    is_demo: bool = True
    offer_count: int = 0
    products: list[SellerProduct] = []


class SellerProduct(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    name: str
    price: int
    availability: Availability
