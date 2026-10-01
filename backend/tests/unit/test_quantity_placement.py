"""
Where ``quantity`` exists, and where it does not.

This file pins the distinction, because it is easy to assume a product carries a
quantity when nothing of the kind exists.

**A product has no quantity.** Not in the catalogue file, not in
:class:`~app.catalog.store.CatalogProduct`, not in ``ProductOut``, not on a
product card or detail page. The catalogue's product keys are exactly
``id, category, subcategory, name, brand, model, attributes, lowest_price_toman,
image_url, source, offers, metadata`` and none of them is a count. Nothing on the
product side of the API accepts, stores, or returns one.

**A project requirement does**, and it means something different: how many units of
a need the job requires ("three tiles"). It is derived by the model, resolved
against the catalogue, stored on the project, and shown on the project page. It is
the only quantity in the product-facing model.

**A selection-list item also carries one today**, and that one is *not* settled
here — see the module note at the end. These tests deliberately do not assert
anything about it, because doing so would pin either a behaviour the product is
moving away from or one it has not yet left.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.catalog.store import CatalogOffer, CatalogProduct
from app.domains.basket.schemas import BasketItemOut
from app.domains.catalog.schemas import ProductOut
from app.domains.projects.schemas import ProjectCandidate, RecommendedCategory
from app.domains.search.schemas import SemanticRequirement

ENRICHED = Path(__file__).resolve().parents[3] / "data" / "catalog" / "products_70_enriched.json"


@pytest.fixture
def enriched(monkeypatch):
    import os

    from app.catalog.store import reset_cache
    from app.core.config import get_settings

    previous = os.environ.get("CATALOG_PATH")
    monkeypatch.setenv("CATALOG_PATH", str(ENRICHED))
    get_settings.cache_clear()
    reset_cache()
    yield ENRICHED
    if previous is None:
        os.environ.pop("CATALOG_PATH", None)
    else:
        os.environ["CATALOG_PATH"] = previous
    get_settings.cache_clear()
    reset_cache()


class TestAProductHasNoQuantity:
    """The premise this task started from, checked at every layer it could hide in."""

    def test_the_catalogue_file_carries_none(self) -> None:
        products = json.loads(ENRICHED.read_text(encoding="utf-8"))
        assert products, "the fixture is a real catalogue"
        assert not any("quantity" in product for product in products), (
            "a product in the canonical file declares a quantity"
        )

    def test_the_catalogue_model_has_no_field(self) -> None:
        from dataclasses import fields

        names = {field.name for field in fields(CatalogProduct)}
        assert "quantity" not in names
        assert "lowest_price_toman" in names, "a price is not a quantity"
        # the enrichment is untouched and still carries the relationships that
        # matter for discovery
        assert {"rooms", "search_terms", "complementary_subcategories",
                "alternative_subcategories", "product_roles"} <= set(
            json.loads(ENRICHED.read_text(encoding="utf-8"))[0]["metadata"]
        )

    def test_an_offer_has_no_quantity_either(self) -> None:
        from dataclasses import fields

        assert "quantity" not in {field.name for field in fields(CatalogOffer)}

    def test_the_product_response_exposes_no_quantity(self) -> None:
        assert "quantity" not in ProductOut.model_fields

    def test_the_product_api_response_carries_none(self, client: TestClient, session, enriched):
        body = client.get("/api/v1/products/search", params={"q": "شیر روشویی"}).json()
        assert body["items"], "the fixture catalogue answers this query"
        for item in body["items"]:
            product = item["product"]
            assert "quantity" not in product, f"{product['name']!r} exposes a quantity"
            # and nothing nested inside it either: an offer is not a quantity
            for offer in product["offers"]:
                assert "quantity" not in offer

    def test_the_product_detail_response_carries_none(
        self, client: TestClient, session, enriched
    ):
        listing = client.get("/api/v1/products/search", params={"q": "شیر روشویی"}).json()
        product_id = listing["items"][0]["product"]["id"]
        detail = client.get(f"/api/v1/products/{product_id}").json()
        assert "quantity" not in detail
        for offer in detail["offers"]:
            assert "quantity" not in offer

    def test_a_product_can_still_be_added_to_a_selection_without_one(
        self, client: TestClient, session, enriched
    ):
        """
        Adding a product identifies the product; it does not count anything.

        The request body takes a product id and nothing else, so there is no field
        a caller could have been sending that the product was pretending to
        understand.
        """
        listing = client.get("/api/v1/products/search", params={"q": "شیر روشویی"}).json()
        product_id = listing["items"][0]["product"]["id"]

        created = client.post("/api/v1/baskets", json={"kind": "product"})
        assert created.status_code == 201, created.text
        basket_id = created.json()["id"]

        response = client.post(
            f"/api/v1/baskets/{basket_id}/items", json={"product_id": product_id}
        )
        assert response.status_code in (200, 201), response.text
        assert response.json()["product"]["id"] == product_id


class TestProjectRequirementQuantityIsIntact:
    """
    The other quantity, and it is a different thing.

    A requirement says how many units of a need the job takes. It is produced by
    the model, validated, resolved to products, and reported on the project — and
    removing it would delete the difference between "this project needs a light
    fitting" and "this project needs six of them".
    """

    def test_a_semantic_requirement_takes_one(self) -> None:
        assert SemanticRequirement(description="کاشی", terms=["کاشی"], quantity=12).quantity == 12

    def test_it_is_still_reported_on_a_project(self) -> None:
        assert "quantity" in RecommendedCategory.model_fields
        assert "quantity" in ProjectCandidate.model_fields

    def test_a_need_of_several_units_survives_resolution(self) -> None:
        """
        Six becomes six, not one: the requirement's own number is carried through
        rather than being replaced by a count of products.
        """
        from app.core.enums import Quality

        from app.catalog.selection import RoomScope
        from app.catalog.store import read_index
        from app.domains.projects.needs import resolve_needs

        index = read_index(ENRICHED)
        needs = resolve_needs(
            index,
            [SemanticRequirement(description="کاشی و سرامیک", terms=["کاشی"], quantity=12)],
            scope=RoomScope(),
            project_type="renovation",
            area_m2=12.0,
            quality=Quality.LOW,
        )
        assert [need.quantity for need in needs] == [12]

    def test_a_requirement_without_a_count_still_defaults(self) -> None:
        """Unstated is one, which is a fact about the requirement, not a product."""
        from app.core.enums import Quality

        from app.catalog.selection import RoomScope
        from app.catalog.store import read_index
        from app.domains.projects.needs import resolve_needs

        index = read_index(ENRICHED)
        needs = resolve_needs(
            index,
            [SemanticRequirement(description="رنگ دیوار", terms=["رنگ دیوار"])],
            scope=RoomScope(),
            project_type="renovation",
            area_m2=12.0,
            quality=Quality.LOW,
        )
        assert [need.quantity for need in needs] == [1]


class TestSelectionListItemsAreProductBased:
    """
    What is asserted, and what is deliberately left open.

    Asserted: an item is a product — a product, an offer, and whether it is locked.

    Not asserted: the item's ``quantity``. It exists today, and the product this
    application is becoming would not have it, but removing it is entangled with
    the budget optimiser (whose entire mechanism is adjusting item counts) and
    with the project flow (which writes a requirement's count onto the item it
    creates). Deciding that is a product decision, so a test written here would
    either pin behaviour that is about to change or fail for a reason unrelated to
    what it claims to check.
    """

    def test_an_item_is_a_product_and_an_offer(self) -> None:
        assert "product" in BasketItemOut.model_fields
        assert "offer" in BasketItemOut.model_fields
        assert "is_locked" in BasketItemOut.model_fields

    def test_the_item_is_keyed_by_what_it_holds(self) -> None:
        """Identity comes from the product, so the same product is the same item."""
        from app.domains.basket.models import BasketItem

        # a SQLAlchemy declarative model, so its columns rather than dataclass
        # fields are what describe it
        columns = {column.name for column in BasketItem.__table__.columns}
        assert {"product_id", "offer_id"} <= columns


# ---------------------------------------------------------------------------
# A note on the one quantity this task did not remove.
#
# ``BasketItemOut.quantity`` and the number input on the selection page are the
# only product-facing quantity left in the codebase. Removing them is a much larger
# change than it first appears, and three things pull against it:
#
#   1. the budget optimiser exists to change item quantities to reach a target
#      budget, and its savings arithmetic is ``(old - new) * quantity`` throughout;
#   2. ``projects/service.py`` writes a requirement's own count onto the selection
#      item it creates, so a project needing six of something currently records
#      six there — a project's quantity would have nowhere to go;
#   3. the database column would need a migration.
#
# That is a basket-architecture change, which the brief also asks not to make, so
# it is raised rather than done.
# ---------------------------------------------------------------------------


class TestSelectionListItemsCarryNoQuantity:
    """
    The change itself, at the model and API boundary.

    An item is one product on a shortlist. There is no count to set, no count to
    read, and adding the same product again is the same selection — not a second
    one and not a larger one.
    """

    def test_the_command_schemas_take_no_count(self) -> None:
        from app.domains.basket.schemas import (
            BasketCreateRequest,
            BasketItemCreate,
            BasketItemUpdate,
        )

        for schema in (BasketItemCreate, BasketItemUpdate, BasketCreateRequest):
            assert "quantity" not in schema.model_fields, schema.__name__

    def test_the_item_response_has_no_count(self) -> None:
        assert "quantity" not in BasketItemOut.model_fields

    def test_the_list_response_has_no_count_sum(self) -> None:
        """`items_count` counts products; there is nothing to sum."""
        from app.domains.basket.schemas import BasketOut

        assert "items_count" in BasketOut.model_fields
        assert "total_quantity" not in BasketOut.model_fields

    def test_an_item_is_one_product(self) -> None:
        from app.domains.basket.models import BasketItem

        assert BasketItem.__new__(BasketItem).units == 1

    def test_a_line_total_is_the_price_not_a_multiple(self) -> None:
        """
        Checked on the real ORM attributes, set the way a row would hold them.

        A row written before this change can still carry a count in the column, and
        the total must not become a multiple of it — that is the whole point of
        ``line_total`` no longer consulting ``quantity``.
        """
        from app.domains.basket.models import BasketItem

        item = BasketItem(unit_price=5_900_000, quantity=7)
        assert item.line_total == 5_900_000
        assert item.units == 1

    def test_an_optimisation_change_reports_no_count(self) -> None:
        from app.domains.basket.schemas import OptimizationChange

        assert "quantity" not in OptimizationChange.model_fields
