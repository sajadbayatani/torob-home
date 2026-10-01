"""Basket domain models.

Money rule: a client can never influence a total. `unit_price` is written only
by the server, from the catalogue offer that was chosen when the item was added,
and every line and basket total is recomputed from it on read.

`product_id` and `offer_id` are plain columns, **not** foreign keys. Products and
offers live in the JSON catalogue, not in the database, so there is no row to
point at; the ids are validated against `data/catalog/products.json` on every
write instead.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import BasketKind, DataSource, ItemOrigin
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

Enum = SAEnum


class Basket(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "baskets"

    kind: Mapped[BasketKind] = mapped_column(
        Enum(BasketKind, name="basket_kind_enum"), default=BasketKind.PRODUCT
    )
    title_fa: Mapped[str | None] = mapped_column(String(200), nullable=True)
    owner_token: Mapped[str] = mapped_column(String(64), default="local", index=True)
    # Snapshot of the interpreted intent (search interpretation or project needs)
    intent_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    target_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Toman
    notes_fa: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_source: Mapped[DataSource] = mapped_column(
        Enum(DataSource, name="data_source_enum"), default=DataSource.SEED
    )

    items: Mapped[list[BasketItem]] = relationship(
        back_populates="basket",
        cascade="all, delete-orphan",
        order_by="BasketItem.created_at",
    )


class BasketItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "basket_items"
    __table_args__ = (
        UniqueConstraint("basket_id", "product_id", "role", name="uq_basket_item_product_role"),
    )

    basket_id: Mapped[UUID] = mapped_column(
        ForeignKey("baskets.id", ondelete="CASCADE"), index=True
    )
    # catalogue ids: validated against products.json, not foreign keys
    product_id: Mapped[UUID] = mapped_column(index=True)
    offer_id: Mapped[UUID] = mapped_column(index=True)
    #: Retained so existing rows stay readable, but **no longer used**. An item is
    #: one product on a shortlist rather than a number of units, so nothing reads
    #: this any more; a new row gets the default. Dropping the column is a migration
    #: and was left out of scope rather than left half-done.
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    #: server-written price of the chosen catalogue offer; the source of every total
    unit_price: Mapped[int] = mapped_column(Integer, default=0)
    role: Mapped[str] = mapped_column(String(60), default="item")
    origin: Mapped[ItemOrigin] = mapped_column(
        Enum(ItemOrigin, name="item_origin_enum"), default=ItemOrigin.MANUAL
    )
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    reason_fa: Mapped[str | None] = mapped_column(String(300), nullable=True)
    replaced_item_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("basket_items.id", ondelete="SET NULL"), nullable=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    basket: Mapped[Basket] = relationship(back_populates="items")

    @property
    def units(self) -> int:
        """
        How many of this the selection holds: always one.

        Asked by the optimiser, which used to multiply savings by the stored count.
        Reading a constant rather than the legacy column means a row written before
        the change cannot make the optimiser miscount.
        """
        return 1

    @property
    def line_total(self) -> int:
        """The price of the product. One selection is one product."""
        return int(self.unit_price)
