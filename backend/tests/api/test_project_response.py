"""
The project's response carries products, not only requirement labels.

The reported symptom was a project page showing the requirements and nothing
else, because ``candidates`` came back empty. These tests pin the **response
contract** rather than which products appear, so they hold whatever the file
stocks: a requirement the catalogue answers contributes real products, one it
cannot is still reported, and neither outcome removes the other.

They run against the real enriched catalogue, because the bug lived in the
metadata-driven resolution and the session-wide fixture file predates the
enrichment — it carries no ``rooms`` and no ``search_terms`` at all.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ENRICHED = Path(__file__).resolve().parents[3] / "data" / "catalog" / "products_70_enriched.json"

ANSWERABLE = [
    {"description": "تخت خواب", "terms": ["تخت خواب"]},
    {"description": "کمد لباس", "terms": ["کمد لباس"]},
]
#: Two needs the 70-product file genuinely has nothing for: it stocks no wall
#: finish and no curtains. Listed here so the test states which kind of need it
#: is exercising — the file, not the resolver, decides this.
UNANSWERABLE = [
    {"description": "رنگ دیوار", "terms": ["رنگ دیوار"]},
    {"description": "پرده", "terms": ["پرده"]},
]


@pytest.fixture
def real_catalog(monkeypatch):
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


def analyze(client: TestClient, llm, requirements, *, room, room_token, goal) -> dict:
    llm.answer(
        intent="project_search",
        category="furniture",
        project={
            "type": "redesign",
            "room": room,
            "room_token": room_token,
            "area_m2": 12.0,
            "goal": goal,
            "constraints": [],
            "requirements": requirements,
        },
        constraints={"quality": None, "budget": None, "notes": []},
        confidence=0.9,
        explanations=["کاربر یک کار در خانه توصیف کرده است."],
    )
    response = client.post(
        "/api/v1/projects/analyze", json={"query": goal}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_a_mixed_project_returns_requirements_products_and_the_gap(
    client: TestClient, llm, session, real_catalog
):
    """
    Test 4 at the response boundary, and the thing the report was really about.

    All four requirements come back, the two the file can answer come back as
    products with an offer and a price, and the two it cannot are reported as
    unavailable — with the need still stated, because an unsupplied need is not
    a need that was never wanted.
    """
    body = analyze(
        client,
        llm,
        ANSWERABLE + UNANSWERABLE,
        room="اتاق خواب",
        room_token="bedroom",
        goal="تغییر دکوراسیون اتاق خواب",
    )
    analysis = body["analysis"]

    # 1. the semantic requirements survive, in the model's own words
    requirements = analysis["interpretation"]["project_requirements"]
    assert [r["description"] for r in requirements] == [
        r["description"] for r in ANSWERABLE + UNANSWERABLE
    ]

    # 2. and so do the project's own needs, the union of matched and unmatched
    needs = analysis["categories"]
    assert {n["label"] for n in needs} == {
        r["description"] for r in ANSWERABLE + UNANSWERABLE
    }
    assert all(n["project_need"] for n in needs), "a need is never withdrawn"

    # 3. the answered ones produced products, not labels
    candidates = analysis["candidates"]
    assert candidates, "the requirements the file answers must yield products"
    labels = {c["label"] for c in candidates}
    assert labels <= {r["description"] for r in ANSWERABLE}
    for candidate in candidates:
        product, offer = candidate["product"], candidate["offer"]
        assert product["id"] and product["name"], "a candidate is a real product"
        assert offer["id"] and offer["seller"]["name"], (
            "with the offer it is bought from"
        )
        assert candidate["unit_price"] > 0 and candidate["seller_name"]
        assert candidate["line_total"] > 0
        assert product["slug"] or product["id"], "it can be opened"

    # 4. the unanswered ones are reported as unavailable, with a reason, and are
    #    not quietly dropped
    missing = analysis["missing_categories"]
    assert {m["label"] for m in missing} == {r["description"] for r in UNANSWERABLE}
    for entry in missing:
        assert entry["project_need"] is True
        assert entry["catalog_match"] is False
        assert entry["note"], "an unavailable need says why"
        assert entry["reason"]

    # 5. and the estimate reflects the products, not the requirement labels
    assert analysis["estimated_total"] == sum(c["line_total"] for c in candidates)

    # 6. a project recommendation is not the user's selection list
    assert body["basket"]["items"] == [] or not body["basket"].get("items")
    assert analysis["basket_id"] is not None, "a project has its own list, unfilled"


def test_an_unanswerable_requirement_alone_still_reports_the_project(
    client: TestClient, llm, session, real_catalog
):
    """
    Nothing to sell is not a failure, and not a reason to answer with nonsense.

    The project is still created, still states every need, and still explains
    the gap — rather than 404-ing, or matching a requirement to whatever the file
    happens to stock.
    """
    body = analyze(
        client,
        llm,
        UNANSWERABLE,
        room="اتاق خواب",
        room_token="bedroom",
        goal="تغییر دکوراسیون اتاق خواب",
    )
    analysis = body["analysis"]
    assert analysis["candidates"] == [], "the file stocks neither"
    assert len(analysis["missing_categories"]) == len(UNANSWERABLE)
    assert analysis["estimated_total"] == 0
    # the needs are the answer here, and they are stated plainly
    assert analysis["explanations"]
    assert any("موجود نیست" in line for line in analysis["explanations"])


def test_candidates_are_the_files_products_not_new_ones(
    client: TestClient, llm, session, real_catalog
):
    """
    A requirement must never turn into a made-up product.

    Every product in the response has to be a row of the canonical file, and
    every requirement is either answered from it or reported as unanswerable.
    """
    from app.catalog.store import read_index

    index = read_index(real_catalog)
    known = {str(product.id) for product in index.products}
    by_label = {product.name: product for product in index.products}

    body = analyze(
        client,
        llm,
        ANSWERABLE + UNANSWERABLE,
        room="اتاق خواب",
        room_token="bedroom",
        goal="تغییر دکوراسیون اتاق خواب",
    )
    analysis = body["analysis"]

    for candidate in analysis["candidates"]:
        product = candidate["product"]
        assert str(product["id"]) in known, f"{product['name']!r} is not in the file"
        assert product["name"] in by_label, "the name came from the file too"
        source = by_label[product["name"]]
        assert source.subcategory == product["subcategory"]
        assert source.purchasable_offers, "offered only if it can be bought"

    # the response accounts for every requirement exactly once
    accounted = {c["label"] for c in analysis["candidates"]} | {
        m["label"] for m in analysis["missing_categories"]
    }
    assert accounted == {
        r["description"] for r in ANSWERABLE + UNANSWERABLE
    }, "a requirement was dropped, or both answered and reported missing"
