"""Basket schemas. Every monetary total is produced by the backend."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import BasketKind, ItemOrigin
from app.domains.catalog.schemas import ProductOut
from app.domains.search.schemas import InterpretedIntent, StrictModel
from app.domains.sellers.schemas import OfferOut

CURRENCY = "IRT"  # Toman


class BasketItemCreate(StrictModel):
    """
    Adding a product *selects* that product.

    There is deliberately no count. This is a product-discovery and selection
    experience: a shopper is building a shortlist of things to look at or buy, not
    a cart of units, so "how many" is not a question the list has an answer to.
    Adding the same product again is the same selection, not a second one.
    """

    product_id: UUID
    offer_id: UUID | None = None  # omitted -> cheapest purchasable offer
    role: str = Field(default="item", max_length=60)
    reason: str | None = Field(default=None, max_length=300)
    origin: ItemOrigin = ItemOrigin.MANUAL
    is_locked: bool = False


class BasketItemUpdate(StrictModel):
    """
    What may change about a selection.

    No count, for the same reason as :class:`BasketItemCreate`. What can change is
    which offer it is held at, whether it is locked, and why it is on the list.
    """

    offer_id: UUID | None = None
    is_locked: bool | None = None
    reason: str | None = Field(default=None, max_length=300)
    role: str | None = Field(default=None, max_length=60)


class BasketCreateRequest(StrictModel):
    kind: BasketKind = BasketKind.PRODUCT
    title: str | None = Field(default=None, max_length=200)
    product_id: UUID | None = None
    owner_token: str = Field(default="local", max_length=64)


class BasketItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product: ProductOut
    offer: OfferOut
    unit_price: int
    line_total: int
    role: str
    origin: ItemOrigin
    is_locked: bool
    reason: str | None = None
    replaced_item_id: UUID | None = None
    is_best_price: bool = True
    best_price: int | None = None
    alternative_count: int = 0
    alternative_min_price: int | None = None


class BasketOut(BaseModel):
    id: UUID
    kind: BasketKind
    title: str | None = None
    currency: str = CURRENCY
    items: list[BasketItemOut] = Field(default_factory=list)
    #: how many products are selected. There is no sum of quantities, because an
    #: item is one product and not a number of units.
    items_count: int = 0
    total: int = 0
    project_id: UUID | None = None
    target_budget: int | None = None
    budget_gap: int | None = None
    within_budget: bool | None = None
    intent: InterpretedIntent | None = None
    notes: str | None = None
    created_at: str
    updated_at: str


class OptimizeRequest(StrictModel):
    target_budget: int | None = Field(default=None, ge=0)
    #: Accepted and deliberately **ignored**.
    #:
    #: This used to be the fallback that re-interpreted the user's original query to
    #: recover a budget, which meant optimising a list spent a model call reading a
    #: sentence the list already knows the answer to — and could fail with an
    #: interpretation error. It is kept only so an existing caller that still sends
    #: it is not rejected; a budget must come from ``target_budget`` or from the
    #: project that produced the list.
    query: str | None = Field(default=None, max_length=500)
    apply: bool = False
    allow_quality_downgrade: bool = True


class OptimizationChange(BaseModel):
    item: str
    item_id: UUID
    role: str
    from_product: str
    from_product_id: UUID
    to_product: str
    to_product_id: UUID
    from_price: int
    to_price: int
    saving: int
    reason: str
    quality_from: str
    quality_to: str


class OptimizationResult(BaseModel):
    original_total: int
    #: None when the project states no budget, so there is no ceiling to
    #: optimise against. Reported rather than rejected, so the action can answer
    #: "nothing to do here" instead of failing.
    target_budget: int | None = None
    #: True when a real change is available: the basket is over budget and at
    #: least one item has a valid, cheaper alternative. Drives whether the
    #: optimise action is worth offering at all.
    can_optimize: bool = False
    #: True when the basket as it stands exceeds the target budget
    over_budget: bool = False
    optimized_total: int
    saved: int
    within_budget: bool
    unfilled_gap: int
    changes: list[OptimizationChange] = Field(default_factory=list)
    applied: bool = False
    basket: BasketOut | None = None
    explanation: str = ""
    trade_offs: list[str] = Field(default_factory=list)
