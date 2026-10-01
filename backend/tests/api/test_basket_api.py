"""API tests: basket maths + budget optimisation (spec §13/§14)."""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.basket.models import Basket, BasketItem
from tests.fixtures import CHEAPER_FAUCET_ID, FAUCET_ID
from tests.llm_stub import LLMStub

PRODUCT_QUERY = "شیر روشویی کاسا"
PROJECT_QUERY = "بازسازی سرویس بهداشتی ۱۲ متری، کیفیت متوسط"

#: the Kasa faucet costs 5,900,000 and the Morvarid one 4,100,000, so a budget
#: below the former can be met by swapping within the same subcategory
FAUCET_PRICE = 5_900_000
CHEAPER_PRICE = 4_100_000
TIGHT_BUDGET = 4_500_000


def _first_product(client: TestClient) -> dict:
    return client.get(f"/api/v1/products/{FAUCET_ID}").json()


def _faucet_basket(client: TestClient) -> dict:
    """A basket holding the one product the catalogue can actually optimise."""
    return client.post(
        "/api/v1/baskets", json={"kind": "product", "product_id": FAUCET_ID}
    ).json()


@pytest.fixture(autouse=True)
def model_reads_a_bathroom_project(llm: LLMStub) -> None:
    """The interpreter is an LLM, so the model is scripted for this module too."""
    llm.bathroom_project(type="renovation", area_m2=12, quality="medium")


def _project(client: TestClient, **constraints) -> dict:
    payload: dict = {"query": PROJECT_QUERY}
    if constraints:
        payload["constraints"] = constraints
    return client.post("/api/v1/projects/analyze", json=payload).json()


# --------------------------------------------------------------------------- #
# basket
# --------------------------------------------------------------------------- #
def test_create_basket_with_product_computes_total(client: TestClient) -> None:
    product = _first_product(client)
    response = client.post(
        "/api/v1/baskets",
        json={"kind": "product", "title": "سبد من", "product_id": product["id"]},
    )
    assert response.status_code == 201
    basket = response.json()

    assert basket["items_count"] == 1
    item = basket["items"][0]
    assert "quantity" not in item, "a selection is a product, not a number of units"
    assert item["unit_price"] == product["min_price"]
    assert item["line_total"] == item["unit_price"]
    assert basket["total"] == item["line_total"]
    assert basket["currency"] == "IRT"


def test_basket_totals_are_recalculated_by_the_server(client: TestClient) -> None:
    product = _first_product(client)
    basket = client.post(
        "/api/v1/baskets", json={"product_id": product["id"]}
    ).json()
    basket_id = basket["id"]
    item_id = basket["items"][0]["id"]

    updated = client.patch(
        f"/api/v1/baskets/{basket_id}/items/{item_id}", json={"is_locked": True}
    ).json()
    assert updated["is_locked"] is True
    # one product, so its line total is its price — there is no count to multiply
    assert updated["line_total"] == updated["unit_price"]

    fetched = client.get(f"/api/v1/baskets/{basket_id}").json()
    assert fetched["total"] == updated["line_total"]
    assert "total_quantity" not in fetched
    assert fetched["items_count"] == 1


def test_client_cannot_forge_a_total(client: TestClient) -> None:
    """Only offer/lock/reason/role are accepted; money fields are rejected."""
    product = _first_product(client)
    basket = client.post(
        "/api/v1/baskets", json={"product_id": product["id"]}
    ).json()
    basket_id = basket["id"]
    item_id = basket["items"][0]["id"]

    forged = client.patch(
        f"/api/v1/baskets/{basket_id}/items/{item_id}",
        json={"line_total": 1, "unit_price": 1},
    )
    assert forged.status_code == 422  # extra="forbid" on the command schema

    unchanged = client.get(f"/api/v1/baskets/{basket_id}").json()
    assert unchanged["total"] == product["min_price"]  # nothing was applied
    assert "quantity" not in unchanged["items"][0]


def test_add_and_delete_items(client: TestClient) -> None:
    product = _first_product(client)
    basket = client.post("/api/v1/baskets", json={"kind": "product"}).json()
    basket_id = basket["id"]

    similar = client.get(f"/api/v1/products/{product['id']}/similar").json()
    for entry in similar[:2]:
        response = client.post(
            f"/api/v1/baskets/{basket_id}/items",
            json={
                "product_id": entry["product"]["id"],
                "role": entry["match_type"],
                "reason": entry["reason"],
                "origin": "search",
            },
        )
        assert response.status_code == 201

    full = client.get(f"/api/v1/baskets/{basket_id}").json()
    assert full["items_count"] == 2
    assert full["items"][0]["origin"] == "search"
    assert full["items"][0]["reason"]

    first_id = full["items"][0]["id"]
    assert client.delete(f"/api/v1/baskets/{basket_id}/items/{first_id}").status_code == 204
    after = client.get(f"/api/v1/baskets/{basket_id}").json()
    assert after["items_count"] == 1
    assert after["total"] == after["items"][0]["line_total"]


def test_adding_the_same_role_twice_is_the_same_selection(client: TestClient) -> None:
    """Selecting a product again does not make a second, larger selection."""
    product = _first_product(client)
    basket = client.post(
        "/api/v1/baskets", json={"product_id": product["id"]}
    ).json()
    basket_id = basket["id"]
    client.post(
        f"/api/v1/baskets/{basket_id}/items",
        json={"product_id": product["id"], "role": basket["items"][0]["role"]},
    )
    refreshed = client.get(f"/api/v1/baskets/{basket_id}").json()
    assert refreshed["items_count"] == 1
    assert refreshed["total"] == refreshed["items"][0]["unit_price"]


def test_unknown_product_cannot_be_added_to_a_basket(client: TestClient) -> None:
    response = client.post(
        "/api/v1/baskets",
        json={"product_id": "11111111-2222-3333-4444-555555555555"},
    )
    assert response.status_code == 404
    assert "پیدا نشد" in response.json()["detail"]


def test_missing_basket_returns_404(client: TestClient) -> None:
    assert client.get("/api/v1/baskets/99999999-9999-9999-9999-999999999999").status_code == 404


# --------------------------------------------------------------------------- #
# budget optimisation
# --------------------------------------------------------------------------- #
def test_budget_optimization_never_increases_the_total(client: TestClient) -> None:
    basket = _faucet_basket(client)
    before = basket["total"]
    assert before == FAUCET_PRICE

    result = client.post(
        f"/api/v1/baskets/{basket['id']}/optimize",
        json={"target_budget": TIGHT_BUDGET, "apply": True},
    )
    assert result.status_code == 200
    body = result.json()

    assert body["original_total"] == before
    assert body["optimized_total"] <= body["original_total"]
    assert body["optimized_total"] <= TIGHT_BUDGET
    assert body["saved"] == body["original_total"] - body["optimized_total"]
    assert body["within_budget"] is True
    assert body["unfilled_gap"] == 0
    assert body["changes"]
    # the swap stays inside the same subcategory and never costs more
    change = body["changes"][0]
    assert change["to_product_id"] == CHEAPER_FAUCET_ID
    assert change["to_price"] == CHEAPER_PRICE < change["from_price"]


def test_optimization_changes_are_explainable(client: TestClient) -> None:
    created = _project(client)
    basket_id = created["basket"]["id"]
    body = client.post(
        f"/api/v1/baskets/{basket_id}/optimize",
        json={"query": "بودجه من ۵۵ میلیون است", "target_budget": 55_000_000},
    ).json()

    assert body["target_budget"] == 55_000_000
    for change in body["changes"]:
        assert change["item"]
        assert change["from_product"] and change["to_product"]
        assert change["saving"] > 0
        assert "کاهش هزینه" in change["reason"]
        assert change["from_price"] > change["to_price"]
    assert body["explanation"]
    assert body["trade_offs"]


def test_optimization_is_applied_to_the_basket(client: TestClient) -> None:
    basket = _faucet_basket(client)
    basket_id = basket["id"]
    body = client.post(
        f"/api/v1/baskets/{basket_id}/optimize",
        json={"target_budget": TIGHT_BUDGET, "apply": True},
    ).json()

    assert body["applied"] is True
    assert body["basket"]["total"] == body["optimized_total"]
    # the basket on disk reflects the optimisation
    refetched = client.get(f"/api/v1/baskets/{basket_id}").json()
    assert refetched["total"] == body["optimized_total"]
    assert refetched["target_budget"] == TIGHT_BUDGET
    assert refetched["within_budget"] is True
    # and the item now points at the cheaper catalogue product
    assert refetched["items"][0]["product"]["id"] == CHEAPER_FAUCET_ID
    assert refetched["items"][0]["unit_price"] == CHEAPER_PRICE


def test_dry_run_does_not_change_the_basket(client: TestClient) -> None:
    created = _project(client)
    basket_id = created["basket"]["id"]
    before = created["basket"]["total"]

    body = client.post(
        f"/api/v1/baskets/{basket_id}/optimize",
        json={"target_budget": 55_000_000, "apply": False},
    ).json()
    assert body["applied"] is False
    assert client.get(f"/api/v1/baskets/{basket_id}").json()["total"] == before


def test_optimization_without_changes_when_already_within_budget(client: TestClient) -> None:
    created = _project(client)
    body = client.post(
        f"/api/v1/baskets/{created['basket']['id']}/optimize",
        json={"target_budget": 500_000_000},
    ).json()
    assert body["changes"] == []
    assert body["optimized_total"] == body["original_total"]
    assert "نیازی به تغییر نیست" in body["explanation"]


def test_locked_item_is_never_replaced(client: TestClient) -> None:
    basket = _faucet_basket(client)
    basket_id = basket["id"]
    item = basket["items"][0]
    client.patch(f"/api/v1/baskets/{basket_id}/items/{item['id']}", json={"is_locked": True})

    body = client.post(f"/api/v1/baskets/{basket_id}/optimize", json={"target_budget": 1}).json()
    assert body["changes"] == []
    assert body["optimized_total"] == body["original_total"]

    refetched = client.get(f"/api/v1/baskets/{basket_id}").json()
    assert refetched["items"][0]["product"]["id"] == FAUCET_ID
    assert refetched["items"][0]["unit_price"] == FAUCET_PRICE


def test_optimization_reports_honestly_when_nothing_cheaper_exists(
    client: TestClient,
) -> None:
    """A basket with no cheaper alternative must say so, not invent a swap."""
    # the washbasin is the only one in its subcategory, so nothing is cheaper
    sink = client.post(
        "/api/v1/baskets",
        json={"kind": "product", "product_id": "77777777-7777-4777-8777-777777777777"},
    ).json()
    body = client.post(
        f"/api/v1/baskets/{sink['id']}/optimize", json={"target_budget": 1}
    ).json()
    assert body["changes"] == []
    assert body["within_budget"] is False
    assert body["unfilled_gap"] > 0
    assert "پیدا نشد" in body["explanation"]


def test_optimize_without_a_budget_answers_instead_of_refusing(client: TestClient) -> None:
    """No ceiling is a real answer, not a failure.

    Most projects state no budget. The action used to be refused with a 422,
    which left the button permanently unavailable for exactly those projects. It
    now reports that there is nothing to optimise against and leaves the basket
    untouched.
    """
    basket = client.post("/api/v1/baskets", json={"kind": "project"}).json()
    body = client.post(f"/api/v1/baskets/{basket['id']}/optimize", json={}).json()

    assert body["can_optimize"] is False
    assert body["target_budget"] is None
    assert body["changes"] == []
    assert body["applied"] is False
    assert "بودجه" in body["explanation"]
    # the basket is exactly as it was
    assert body["basket"]["total"] == basket["total"]

def test_a_real_catalogue_product_can_be_added_to_a_basket(client: TestClient) -> None:
    """The regression this fixes: a catalogue id used to be a 404.

    Basket items carry the catalogue's own `random_key` and are validated against
    the catalogue file, with no product row in the database.
    """
    response = client.post(
        "/api/v1/baskets", json={"kind": "product", "product_id": FAUCET_ID}
    )
    assert response.status_code == 201
    basket = response.json()
    item = basket["items"][0]

    assert item["product"]["id"] == FAUCET_ID
    assert item["product"]["name"] == "شیر روشویی کاسا مدل K-100"
    # priced from the catalogue's own offer, not from a database row
    assert item["offer"]["id"] == "aaaaaaaa-0000-4000-8000-000000000001"
    assert item["offer"]["seller"]["name"] == "بازار ساختمان"
    assert item["unit_price"] == 5_900_000
    # one product is one line, so the line total is the price rather than a
    # multiple of it
    assert item["line_total"] == 5_900_000
    assert basket["total"] == 5_900_000
    # this *is* the cheapest of the product's own sellers
    assert item["is_best_price"] is True
    assert item["best_price"] == 5_900_000
    # and the alternative hint points at the cheaper product of the same kind
    assert item["alternative_count"] >= 1
    assert item["alternative_min_price"] == 4_100_000


def test_adding_a_product_by_its_catalogue_id_through_the_items_endpoint(
    client: TestClient,
) -> None:
    basket = client.post("/api/v1/baskets", json={"kind": "product"}).json()
    response = client.post(
        f"/api/v1/baskets/{basket['id']}/items",
        json={"product_id": FAUCET_ID},
    )
    assert response.status_code == 201
    assert response.json()["product"]["id"] == FAUCET_ID


def test_an_id_outside_the_catalogue_is_refused(client: TestClient) -> None:
    """No seeded product may be resurrected, and no id may be invented."""
    basket = client.post("/api/v1/baskets", json={"kind": "product"}).json()
    unknown = "00000000-0000-4000-8000-000000000000"
    response = client.post(
        f"/api/v1/baskets/{basket['id']}/items", json={"product_id": unknown}
    )
    assert response.status_code == 404
    assert "کاتالوگ" in response.json()["detail"]
    # and the basket is unchanged
    assert client.get(f"/api/v1/baskets/{basket['id']}").json()["items_count"] == 0


def test_a_specific_catalogue_offer_can_be_chosen(client: TestClient) -> None:
    basket = client.post("/api/v1/baskets", json={"kind": "product"}).json()
    response = client.post(
        f"/api/v1/baskets/{basket['id']}/items",
        json={
            "product_id": FAUCET_ID,
            "offer_id": "aaaaaaaa-0000-4000-8000-000000000002",
        },
    )
    assert response.status_code == 201
    item = response.json()
    # the pricier seller was chosen on purpose, and the total follows it
    assert item["offer"]["price"] == 6_667_000
    assert item["unit_price"] == 6_667_000
    assert item["is_best_price"] is False
    assert item["best_price"] == 5_900_000


def test_an_offer_from_another_product_is_refused(client: TestClient) -> None:
    basket = client.post("/api/v1/baskets", json={"kind": "product"}).json()
    response = client.post(
        f"/api/v1/baskets/{basket['id']}/items",
        json={
            "product_id": FAUCET_ID,
            "offer_id": "cccccccc-0000-4000-8000-000000000001",  # a toilet's offer
        },
    )
    assert response.status_code == 400
    assert "معتبر نیست" in response.json()["detail"]


def test_adding_the_same_product_twice_is_idempotent(client: TestClient) -> None:
    """The product is selected, once, at its own price."""
    basket = client.post(
        "/api/v1/baskets", json={"kind": "product", "product_id": FAUCET_ID}
    ).json()
    item = client.post(
        f"/api/v1/baskets/{basket['id']}/items", json={"product_id": FAUCET_ID}
    ).json()
    assert "quantity" not in item
    refetched = client.get(f"/api/v1/baskets/{basket['id']}").json()
    assert refetched["items_count"] == 1, "not two lines and not one of double size"
    assert refetched["total"] == 5_900_000


def test_a_project_basket_is_built_from_catalogue_ids(client: TestClient) -> None:
    created = client.post("/api/v1/projects/analyze", json={"query": PROJECT_QUERY}).json()
    basket = created["basket"]
    analysis = created["analysis"]

    # A project basket starts empty: recommendations are never added to it. What
    # the project *does* recommend has to point at real catalogue products, so
    # this is checked against the recommendations instead of the basket.
    assert basket["items_count"] == 0
    for candidate in analysis["candidates"]:
        detail = client.get(f"/api/v1/products/{candidate['product']['id']}")
        assert detail.status_code == 200, candidate["product"]["id"]
        assert detail.json()["offers"], "a recommendation must point at a real product"


# --------------------------------------------------------------------------- #
# clearing the whole basket
# --------------------------------------------------------------------------- #
class TestClearBasket:
    def _basket_with_two_items(self, client: TestClient) -> str:
        first = _first_product(client)
        basket = client.post(
            "/api/v1/baskets", json={"product_id": first["id"]}
        ).json()
        basket_id = basket["id"]
        similar = client.get(f"/api/v1/products/{first['id']}/similar").json()
        for entry in similar[:1]:
            client.post(
                f"/api/v1/baskets/{basket_id}/items",
                json={"product_id": entry["product"]["id"]},
            )
        assert client.get(f"/api/v1/baskets/{basket_id}").json()["items_count"] == 2
        return basket_id

    def test_empties_the_basket(self, client: TestClient) -> None:
        basket_id = self._basket_with_two_items(client)

        assert client.delete(f"/api/v1/baskets/{basket_id}").status_code == 204
        assert client.get(f"/api/v1/baskets/{basket_id}").status_code == 404

    def test_leaves_no_items_behind(self, client: TestClient, session: Session) -> None:
        """The lines are deleted, not merely hidden by the missing basket."""
        basket_id = self._basket_with_two_items(client)
        client.delete(f"/api/v1/baskets/{basket_id}")

        assert session.get(Basket, UUID(basket_id)) is None
        remaining = session.scalars(
            select(BasketItem).where(BasketItem.basket_id == UUID(basket_id))
        ).all()
        assert list(remaining) == []

    def test_also_removes_the_project_analysis(self, client: TestClient) -> None:
        """A project title and question must not outlive their basket."""
        body = client.post("/api/v1/projects/analyze", json={"query": PROJECT_QUERY}).json()
        analysis_id = body["analysis"]["id"]
        basket_id = body["basket"]["id"]
        assert body["analysis"]["basket_id"] == basket_id
        assert client.get(f"/api/v1/baskets/{basket_id}").status_code == 200
        assert client.get(f"/api/v1/projects/{analysis_id}").status_code == 200

        assert client.delete(f"/api/v1/baskets/{basket_id}").status_code == 204
        assert client.get(f"/api/v1/baskets/{basket_id}").status_code == 404
        # the question and title that were answered from this basket are gone too
        assert client.get(f"/api/v1/projects/{analysis_id}").status_code == 404

    def test_clearing_twice_is_404(self, client: TestClient) -> None:
        basket_id = self._basket_with_two_items(client)
        client.delete(f"/api/v1/baskets/{basket_id}")
        assert client.delete(f"/api/v1/baskets/{basket_id}").status_code == 404

    def test_unknown_basket_is_404(self, client: TestClient) -> None:
        response = client.delete("/api/v1/baskets/deadbeef-0000-4000-8000-000000000000")
        assert response.status_code == 404

    def test_another_users_basket_is_not_reachable(self, client: TestClient) -> None:
        basket_id = self._basket_with_two_items(client)
        # a malformed id must not be read as a wildcard
        assert client.delete("/api/v1/baskets/not-a-uuid").status_code == 422
        assert client.get(f"/api/v1/baskets/{basket_id}").status_code == 200
