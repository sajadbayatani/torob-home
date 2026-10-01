"""catalog becomes a JSON file owned by the backend

The product catalogue moves out of PostgreSQL and into
``data/catalog/products.json``, which ``app.catalog`` reads. This migration:

* adds the two new ``Domain`` values and the ``SAME_KIND`` relation type;
* adds the ``CATALOG`` data source;
* drops the ``product_id`` / ``offer_id`` foreign keys on ``basket_items`` and
  stores the server-written price in ``unit_price``;
* renames ``project_requirements.category_id`` to ``category_slug``;
* drops the catalogue tables, which no longer have any writer.

Basket and project rows are **kept**: they are application data that references
the catalogue by id, and the ids stay valid because they are the catalogue's own
``random_key`` values.

Revision ID: 0002_catalog_json
Revises: 0001_initial_schema
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_catalog_json"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CATALOGUE_TABLES = (
    "basket_items",
    "product_relations",
    "product_attributes",
    "offers",
    "products",
    "sellers",
    "brands",
    "categories",
)


def _table_exists(name: str) -> bool:
    return bool(
        op.get_bind()
        .execute(
            sa.text("select 1 from information_schema.tables where table_name = :name"),
            {"name": name},
        )
        .scalar()
    )


def _index_exists(name: str) -> bool:
    return bool(op.get_bind().execute(sa.text("select 1 from pg_class where relname = :name"),
                                      {"name": name}).scalar())


def _constraint_exists(table: str, name: str) -> bool:
    return bool(
        op.get_bind()
        .execute(
            sa.text(
                "select 1 from pg_constraint c join pg_class t on t.oid = c.conrelid "
                "where t.relname = :table and c.conname = :name"
            ),
            {"table": table, "name": name},
        )
        .scalar()
    )


def _drop_index(name: str, table: str) -> None:
    if _index_exists(name):
        op.drop_index(name, table_name=table)


def _drop_fk(table: str, name: str) -> None:
    if _constraint_exists(table, name):
        op.drop_constraint(name, table, type_="foreignkey")


def _add_enum_values(enum_name: str, values: list[str]) -> None:
    """Add values to a PostgreSQL enum type, if they are not there yet."""
    bind = op.get_bind()
    exists = bind.execute(
        sa.text("select 1 from pg_type where typname = :name"), {"name": enum_name}
    ).scalar()
    if not exists:
        return
    current = {
        row[0]
        for row in bind.execute(
            sa.text(
                "select e.enumlabel from pg_type t "
                "join pg_enum e on e.enumtypid = t.oid where t.typname = :name"
            ),
            {"name": enum_name},
        )
    }
    for value in values:
        if value in current:
            continue
        op.execute(sa.text(f"alter type {enum_name} add value '{value}'"))


def upgrade() -> None:
    # --- vocabulary ------------------------------------------------------
    _add_enum_values("domain_enum", ["APPLIANCE", "FURNITURE"])
    _add_enum_values("relation_type_enum", ["SAME_KIND"])
    _add_enum_values("data_source_enum", ["CATALOG"])

    # --- basket items stop pointing at catalogue tables -------------------
    _drop_fk("basket_items", "fk_basket_items_offer_id")
    _drop_fk("basket_items", "fk_basket_items_category_id")
    _drop_fk("basket_items", "fk_basket_items_product_id")
    _drop_index("ix_basket_items_category_id", "basket_items")
    op.drop_column("basket_items", "category_id")
    op.drop_column("basket_items", "unit_price_snapshot")
    op.add_column(
        "basket_items",
        sa.Column("unit_price", sa.Integer(), nullable=False, server_default="0"),
    )

    # --- project requirements address the catalogue by slug ---------------
    _drop_fk("project_requirements", "fk_project_requirements_category_id")
    _drop_index("ix_project_requirements_category_id", "project_requirements")
    op.drop_column("project_requirements", "category_id")
    op.add_column("project_requirements", sa.Column("category_slug", sa.String(length=80)))
    op.create_index(
        op.f("ix_project_requirements_category_slug"),
        "project_requirements",
        ["category_slug"],
        unique=False,
    )

    # --- the catalogue tables go away; nothing writes them any more -------
    if _index_exists("products") or _table_exists("products"):
        # basket rows pointing at products that no longer exist cannot be priced
        op.execute("delete from basket_items where product_id not in (select id from products)")
    for table in CATALOGUE_TABLES:
        if table == "basket_items" or not _table_exists(table):
            continue
        op.drop_table(table)


def downgrade() -> None:
    """Recreate the catalogue tables.

    The rows are **not** restored: the catalogue is a file, and the previous
    contents were invented demo data that must not come back silently. Point
    ``CATALOG_PATH`` at a file and re-seed to repopulate.
    """
    op.create_table(
        "categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name_fa", sa.String(length=120), nullable=False),
        sa.Column("domain", sa.Enum("BATHROOM", "KITCHEN", name="domain_enum"), nullable=False),
        sa.Column("kind", sa.Enum("FIXTURE", name="category_kind_enum"), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("search_text", sa.String(length=512), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
    )
    op.create_table(
        "products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("name_fa", sa.String(length=200), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("domain", sa.Enum("BATHROOM", "KITCHEN", name="domain_enum"), nullable=False),
        sa.Column("quality", sa.Enum("LOW", "MEDIUM", "HIGH", "ULTRA", name="quality_enum"), nullable=False),
        sa.Column("unit", sa.String(length=40), nullable=False),
        sa.Column("reference_price", sa.Integer(), nullable=False),
        sa.Column("warranty_months", sa.Integer(), nullable=False),
        sa.Column("search_text", sa.String(length=900), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_products")),
    )
    op.drop_column("basket_items", "unit_price")
    op.add_column("basket_items", sa.Column("unit_price_snapshot", sa.Integer(), nullable=True))
    op.add_column("basket_items", sa.Column("category_id", sa.Uuid(), nullable=True))
    op.drop_column("project_requirements", "category_slug")
    op.add_column("project_requirements", sa.Column("category_id", sa.Uuid(), nullable=False))
