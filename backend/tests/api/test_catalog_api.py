"""API tests: the catalogue endpoints, served from `products.json`.

These assert the contract the frontend depends on: the products are the ones in
the catalogue file, the seller records are preserved, nothing the file does not
carry is invented, and an unknown id is a 404 rather than a fabricated product.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from tests.fixtures import (
    CHEAPER_FAUCET_ID,
    CHEAPER_TOILET_ID,
    MIRROR_ID,
    SINK_ID,
    FAUCET_ID,
    FAUCET_QAHRMAN_ID,
    HOOD_ID,
    TOILET_ID,
)

FAUCET_QUERY = "شیر روشویی"


def _product_by_id(client: TestClient, product_id: str) -> dict:
    return client.get(f"/api/v1/products/{product_id}").json()


def test_search_returns_catalogue_products(client: TestClient) -> None:
    response = client.get("/api/v1/products/search", params={"q": FAUCET_QUERY})
    assert response.status_code == 200
    body = response.json()

    # The query names a subcategory the file spells exactly, so it is a hard
    # constraint and only that subcategory can appear. This used to return four
    # products: the three faucets, plus the washbasin, which shares the word
    # «روشویی» with the query. A person who asked for a *faucet* was shown a
    # washbasin, ranked last as though ranking could substitute for relevance —
    # the category is now resolved first and the washbasin cannot enter at all.
    assert body["total"] == 3
    assert {item["product"]["id"] for item in body["items"]} == {
        FAUCET_ID,
        FAUCET_QAHRMAN_ID,
        CHEAPER_FAUCET_ID,
    }
    assert SINK_ID not in {item["product"]["id"] for item in body["items"]}
    assert body["detected_category"] == "sink-faucet"
    assert all(len(item["matched_terms"]) == 2 for item in body["items"])
    assert all(item["reasons"] for item in body["items"])

    product = _product_by_id(client, FAUCET_ID)
    assert {
        "id",
        "name",
        "category",
        "attributes",
        "offers",
        "brand",
        "quality",
        "min_price",
    } <= set(product)
    assert product["name"] == "شیر روشویی کاسا مدل K-100"
    assert product["brand"]["name"] == "کاسا"
    assert product["category"]["slug"] == "sink-faucet"
    assert product["category"]["name"] == "شیر روشویی"
    assert product["model"] == "K-100"
    assert product["subcategory"] == "sink-faucet"
    assert product["image_url"].startswith("https://")
    assert {attribute["key"] for attribute in product["attributes"]} == {"color", "installation"}


def test_products_are_not_demo_data(client: TestClient) -> None:
    product = _product_by_id(client, FAUCET_ID)
    assert product["is_demo"] is False
    for offer in product["offers"]:
        assert offer["seller"]["is_demo"] is False


def test_fields_the_catalogue_lacks_are_null_not_zero(client: TestClient) -> None:
    product = _product_by_id(client, FAUCET_ID)
    # the catalogue records none of these, so nothing may be invented
    assert product["quality"] is None
    assert product["quality_fa"] is None
    assert product["style"] is None
    assert product["warranty_months"] is None
    assert product["rating"] is None
    assert product["unit"] is None
    offer = product["offers"][0]
    assert offer["stock_count"] is None
    assert offer["delivery_days"] is None
    assert offer["warranty_months"] is None
    assert offer["original_price"] is None
    # but the fields it does carry are real
    assert offer["price"] > 0
    assert offer["url"].startswith("https://torob.com/")


def test_seller_records_are_preserved_exactly(client: TestClient) -> None:
    offers = _product_by_id(client, FAUCET_ID)["offers"]
    assert [offer["id"] for offer in offers] == [
        "aaaaaaaa-0000-4000-8000-000000000001",
        "aaaaaaaa-0000-4000-8000-000000000002",
    ]
    assert offers[0]["seller"]["name"] == "بازار ساختمان"
    assert offers[0]["seller"]["city"] == "تهران"
    assert offers[0]["seller"]["id"] == "101"
    assert offers[0]["price"] == 5_900_000
    assert offers[0]["availability"] == "in_stock"
    assert offers[0]["available"] is True
    assert offers[0]["price_updated_at"] == "۴ روز پیش"


def test_offers_are_sorted_cheapest_first(client: TestClient) -> None:
    product = _product_by_id(client, FAUCET_ID)
    prices = [offer["price"] for offer in product["offers"]]
    assert prices == sorted(prices)
    assert product["min_price"] == min(prices)
    assert product["offers_count"] == len(product["offers"])
    assert product["available_offers_count"] == len(product["offers"])


def test_an_unavailable_seller_is_not_an_offer(client: TestClient) -> None:
    product = _product_by_id(client, TOILET_ID)
    # the catalogue's second seller record is "ناموجود" with price 0
    assert product["offers_count"] == 1
    assert product["offers"][0]["seller"]["name"] == "لوله‌باز"


def test_an_unreliable_price_is_kept_but_ranked_last(client: TestClient) -> None:
    product = _product_by_id(client, HOOD_ID)
    assert product["offers"][0]["is_price_unreliable"] is True


def test_a_product_without_a_brand_has_none(client: TestClient) -> None:
    assert _product_by_id(client, TOILET_ID)["brand"] is None


def test_search_filters_by_subcategory_and_brand(client: TestClient) -> None:
    everything = client.get("/api/v1/products/search", params={"q": FAUCET_QUERY}).json()
    assert everything["total"] == 3

    by_brand = client.get(
        "/api/v1/products/search", params={"q": FAUCET_QUERY, "brand": "قهرمان"}
    ).json()
    assert by_brand["total"] == 1
    assert by_brand["items"][0]["product"]["id"] == FAUCET_QAHRMAN_ID
    # the brand filter is exact, not a fuzzy match
    assert client.get(
        "/api/v1/products/search", params={"q": FAUCET_QUERY, "brand": "کاس"}
    ).json()["total"] == 0

    by_category = client.get(
        "/api/v1/products/search", params={"q": FAUCET_QUERY, "category": "toilet"}
    ).json()
    assert by_category["total"] == 0


def test_ranking_still_orders_partial_matches_last(client: TestClient) -> None:
    """
    Ranking survives, for the queries that leave something to rank.

    «شیر روشویی» now resolves a subcategory, so there is nothing to rank: the
    answer is that subcategory. This query names no subcategory the file spells
    out — it names a kind of thing and a brand — so text decides, and a product
    matching both words outranks one matching only the kind.
    """
    body = client.get("/api/v1/products/search", params={"q": "شیر قهرمان"}).json()
    assert body["detected_category"] is None, "no subcategory is named, so none is assumed"
    assert body["total"] == 3

    best = body["items"][0]
    assert best["product"]["id"] == FAUCET_QAHRMAN_ID
    assert set(best["matched_terms"]) == {"شیر", "قهرمان"}
    for item in body["items"][1:]:
        assert set(item["matched_terms"]) == {"شیر"}, "a partial match ranks below a full one"


def test_search_facets_come_from_the_catalogue(client: TestClient) -> None:
    facets = client.get("/api/v1/products/facets").json()
    assert {facet["value"] for facet in facets["subcategories"]} == {
        "sink-faucet",
        "sink",
        "bathroom-mirror",
        "toilet",
        "kitchen-hood",
        "bed",
        "wardrobe",
    }
    assert {facet["value"] for facet in facets["brands"]} == {
        "کاسا",
        "قهرمان",
        "اخوان",
        "آریا",
        "مروارید",
        "پارس سرام",
        "دلفین",
    }
    assert {facet["value"] for facet in facets["categories"]} == {
        "bathroom",
        "kitchen",
        "furniture",
    }
    # counted from the file, so the counts must add up to the catalogue
    assert sum(facet["count"] for facet in facets["subcategories"]) == 10


def test_search_explanations_cannot_be_false(client: TestClient) -> None:
    body = client.get("/api/v1/products/search", params={"q": FAUCET_QUERY}).json()
    assert any("10 محصول کاتالوگ" in line for line in body["explanations"])
    # a phrase the catalogue genuinely does not contain
    empty = client.get("/api/v1/products/search", params={"q": "اسکیت زمستانی"}).json()
    assert empty["total"] == 0
    assert empty["items"] == []
    assert any("تطبیق نداشت" in line for line in empty["explanations"])


def test_a_too_short_query_returns_nothing(client: TestClient) -> None:
    body = client.get("/api/v1/products/search", params={"q": "ش"}).json()
    assert body["total"] == 0
    assert body["items"] == []


def test_persian_spelling_variants_still_match(client: TestClient) -> None:
    # Arabic yeh and kaf, and a different ZWNJ style
    # Arabic yeh/kaf fold to Persian, so the same three faucets match; the
    # washbasin only matched "روشویی" before and still does not match this phrase
    body = client.get("/api/v1/products/search", params={"q": "شير روميزي"}).json()
    assert body["total"] == 3
    assert {item["product"]["id"] for item in body["items"]} == {
        FAUCET_ID,
        FAUCET_QAHRMAN_ID,
        CHEAPER_FAUCET_ID,
    }


def test_product_detail(client: TestClient) -> None:
    response = client.get(f"/api/v1/products/{FAUCET_ID}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == FAUCET_ID
    assert body["name"] == "شیر روشویی کاسا مدل K-100"
    assert body["description"] is None
    assert body["reference_price"] == 5_900_000
    assert len(body["offers"]) == 2


def test_unknown_product_is_404_not_invented(client: TestClient) -> None:
    missing = "00000000-0000-4000-8000-000000000000"
    assert client.get(f"/api/v1/products/{missing}").status_code == 404


def test_a_malformed_id_is_rejected(client: TestClient) -> None:
    assert client.get("/api/v1/products/not-a-uuid").status_code == 422


def test_categories_and_brands_come_from_the_catalogue(client: TestClient) -> None:
    categories = client.get("/api/v1/categories").json()
    assert {entry["slug"] for entry in categories} == {
        "sink-faucet",
        "sink",
        "bathroom-mirror",
        "toilet",
        "kitchen-hood",
        "bed",
        "wardrobe",
    }
    counts = {entry["slug"]: entry["product_count"] for entry in categories}
    assert counts["sink-faucet"] == 3
    assert counts["toilet"] == 2

    brands = client.get("/api/v1/brands").json()
    assert {entry["name"] for entry in brands} == {
        "کاسا",
        "قهرمان",
        "اخوان",
        "آریا",
        "مروارید",
        "پارس سرام",
        "دلفین",
    }


def test_sellers_are_projected_from_the_catalogue(client: TestClient) -> None:
    sellers = client.get("/api/v1/sellers").json()
    assert {seller["id"] for seller in sellers} == {
        "101", "102", "103", "104", "106", "107", "108", "109", "110",
    }
    assert all(seller["is_demo"] is False for seller in sellers)

    detail = client.get("/api/v1/sellers/101").json()
    assert detail["name"] == "بازار ساختمان"
    assert detail["offer_count"] == 1
    assert detail["products"][0]["name"] == "شیر روشویی کاسا مدل K-100"
    assert client.get("/api/v1/sellers/999999").status_code == 404


def test_seller_offers_search(client: TestClient) -> None:
    offers = client.get("/api/v1/sellers/offers/search", params={"product_id": FAUCET_ID}).json()
    assert [offer["price"] for offer in offers] == [5_900_000, 6_667_000]
    available = client.get(
        "/api/v1/sellers/offers/search", params={"only_available": True}
    ).json()
    assert all(offer["available"] for offer in available)


def test_catalogue_meta_reports_skipped_records(client: TestClient) -> None:
    body = client.get("/api/v1/products/meta").json()
    assert body["products"] == 10
    assert body["skipped"] == [
        {"name": "بدون شناسه", "reason": "missing_id"},
        {"name": "بدون قیمت", "reason": "missing_or_invalid_price"},
    ]


def test_the_catalogue_is_the_only_source(client: TestClient) -> None:
    """No seeded product may reappear alongside the catalogue."""
    file_ids = {entry["id"] for entry in json.loads(client.get("/api/v1/products/meta").text and "[]")}
    assert file_ids == set()
    ids = set()
    for query in ["شیر", "توالت", "هود", "یخچال", "ماشین"]:
        body = client.get("/api/v1/products/search", params={"q": query, "limit": 100}).json()
        ids.update(item["product"]["id"] for item in body["items"])
    # only ids that exist in the catalogue file
    assert ids <= {
        FAUCET_ID,
        FAUCET_QAHRMAN_ID,
        CHEAPER_FAUCET_ID,
        TOILET_ID,
        HOOD_ID,
        SINK_ID,
        MIRROR_ID,
        CHEAPER_TOILET_ID,
    }


# --------------------------------------------------------------------------- #
# similar products
# --------------------------------------------------------------------------- #
class TestSimilarEndpoint:
    def test_returns_catalogue_products_with_reasons(self, client: TestClient) -> None:
        response = client.get(f"/api/v1/products/{FAUCET_ID}/similar")
        assert response.status_code == 200
        items = response.json()

        assert items
        for item in items:
            assert item["product"]["id"] != FAUCET_ID
            assert item["match_type"] in {"same_subcategory", "same_brand", "same_category"}
            assert item["reason"]
            # every id resolves against the catalogue
            assert client.get(f"/api/v1/products/{item['product']['id']}").status_code == 200

    def test_same_subcategory_comes_first(self, client: TestClient) -> None:
        items = client.get(f"/api/v1/products/{FAUCET_ID}/similar").json()
        assert items[0]["match_type"] == "same_subcategory"
        assert items[0]["product"]["subcategory"] == "sink-faucet"

    def test_is_deterministic(self, client: TestClient) -> None:
        first = client.get(f"/api/v1/products/{FAUCET_ID}/similar").json()
        second = client.get(f"/api/v1/products/{FAUCET_ID}/similar").json()
        assert [i["product"]["id"] for i in first] == [i["product"]["id"] for i in second]

    def test_limit_is_respected(self, client: TestClient) -> None:
        for limit in (1, 2, 3):
            items = client.get(
                f"/api/v1/products/{FAUCET_ID}/similar", params={"limit": limit}
            ).json()
            assert len(items) <= limit

    def test_a_product_with_no_neighbours_returns_an_empty_list(
        self, client: TestClient
    ) -> None:
        assert client.get(f"/api/v1/products/{HOOD_ID}/similar").json() == []

    def test_unknown_product_is_404(self, client: TestClient) -> None:
        response = client.get("/api/v1/products/deadbeef-0000-4000-8000-000000000000/similar")
        assert response.status_code == 404


# --------------------------------------------------------------------------- #
# complementary products
# --------------------------------------------------------------------------- #
class TestComplementaryEndpoint:
    def test_never_returns_a_product_outside_the_catalogue(
        self, client: TestClient, monkeypatch
    ) -> None:
        """The guarantee the frontend depends on: ids are validated server-side."""

        def reply(**_):
            return {
                "items": [
                    {"id": "deadbeef-0000-4000-8000-000000000000", "reason": "ساختگی"},
                    {"id": SINK_ID, "reason": "کنار روشویی نصب می‌شود."},
                ]
            }

        monkeypatch.setattr("app.catalog.complementary.chat_json", reply)
        monkeypatch.setattr("app.catalog.complementary.is_configured", lambda: True)

        body = client.get(f"/api/v1/products/{FAUCET_ID}/complementary").json()

        assert [item["product_id"] for item in body["items"]] == [SINK_ID]
        assert body["discarded_ids"] == ["deadbeef-0000-4000-8000-000000000000"]
        for item in body["items"]:
            assert item["product_id"] == item["product"]["id"]
            assert client.get(f"/api/v1/products/{item['product_id']}").status_code == 200

    def test_says_when_the_model_is_unavailable(self, client: TestClient, monkeypatch) -> None:
        monkeypatch.setattr("app.catalog.complementary.is_configured", lambda: False)
        body = client.get(f"/api/v1/products/{FAUCET_ID}/complementary").json()

        assert body["llm_available"] is False
        assert body["note"]
        # the catalogue pairings are still offered, and are labelled as such
        assert body["items"]
        assert all(item["source"] == "heuristic" for item in body["items"])

    def test_reports_the_candidate_pool(self, client: TestClient, monkeypatch) -> None:
        def reply(**_):
            return {"items": []}

        monkeypatch.setattr("app.catalog.complementary.chat_json", reply)
        monkeypatch.setattr("app.catalog.complementary.is_configured", lambda: True)

        body = client.get(f"/api/v1/products/{FAUCET_ID}/complementary").json()
        assert body["llm_available"] is True
        assert body["candidate_count"] > 0
        assert body["items"] == []
        assert body["note"]

    def test_a_malformed_model_reply_is_not_a_crash(
        self, client: TestClient, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            "app.catalog.complementary.chat_json", lambda **_: ["not", "an", "object"]
        )
        monkeypatch.setattr("app.catalog.complementary.is_configured", lambda: True)

        response = client.get(f"/api/v1/products/{FAUCET_ID}/complementary")
        assert response.status_code == 200
        assert response.json()["items"] == []

    def test_a_model_failure_still_serves_the_catalogue(
        self, client: TestClient, monkeypatch
    ) -> None:
        from app.llm import LLMUnavailable

        def boom(**_):
            raise LLMUnavailable("no network")

        monkeypatch.setattr("app.catalog.complementary.chat_json", boom)
        monkeypatch.setattr("app.catalog.complementary.is_configured", lambda: True)

        body = client.get(f"/api/v1/products/{FAUCET_ID}/complementary").json()
        assert body["llm_available"] is False
        assert body["items"]
        assert all(item["source"] == "heuristic" for item in body["items"])

    def test_a_lone_product_reports_no_complements(self, client: TestClient) -> None:
        body = client.get(f"/api/v1/products/{HOOD_ID}/complementary").json()
        assert body["items"] == []
        assert body["candidate_count"] == 0
        assert body["note"]

    def test_unknown_product_is_404(self, client: TestClient) -> None:
        response = client.get(
            "/api/v1/products/deadbeef-0000-4000-8000-000000000000/complementary"
        )
        assert response.status_code == 404
