"""API tests: intent interpretation endpoint + project (need) engine.

The interpreter is an LLM, so every test here states what the model was
scripted to answer and then asserts what the *system* did with it. The wording of
a query no longer decides anything by itself; a test that wants a different
reading scripts a different answer.
"""

from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from app.domains.projects.schemas import UNAVAILABLE_NOT_STOCKED
from tests.llm_stub import LLMStub

PRODUCT_QUERY = "شیر توکار برند X"
PROJECT_QUERY = "بازسازی سرویس بهداشتی ۱۲ متری، کیفیت متوسط"


@pytest.fixture(autouse=True)
def model_reads_a_bathroom_renovation(llm: LLMStub) -> None:
    """Default: the model reads the query as a 12 m² bathroom renovation.

    Every test that needs a different reading scripts its own answer, which is
    why none of them depend on the wording of ``PROJECT_QUERY``.
    """
    llm.bathroom_project(type="renovation", area_m2=12, quality="medium")


def test_interpret_product_query(client: TestClient, llm: LLMStub) -> None:
    # the model names the category and the words; the catalogue names the slug
    llm.product_search(terms=["شیر روشویی"], brand="X", category="bathroom")
    response = client.post("/api/v1/search/interpret", json={"query": PRODUCT_QUERY})
    assert response.status_code == 200
    body = response.json()

    assert body["intent"] == "PRODUCT_SEARCH"
    assert body["domain"] == "bathroom"
    # the slug came from the catalogue's own labels, not from the model
    assert body["product_query"]["category_slug"] == "sink-faucet"
    # the model extracted the product words, not the filler
    assert "شیر روشویی" in body["product_query"]["text"]


def test_a_subcategory_the_catalogue_cannot_detect_is_left_unset(
    client: TestClient, llm: LLMStub
) -> None:
    """A word the catalogue does not carry yields no slug, not a guessed one."""
    llm.product_search(terms=["شیر توکار"], category="bathroom")
    body = client.post("/api/v1/search/interpret", json={"query": PRODUCT_QUERY}).json()

    assert body["product_query"]["category_slug"] is None
    # the category the model named is still kept
    assert body["domain"] == "bathroom"


def test_interpret_project_query_matches_spec_shape(client: TestClient) -> None:
    response = client.post("/api/v1/search/interpret", json={"query": PROJECT_QUERY})
    assert response.status_code == 200
    body = response.json()

    assert body["intent"] == "NEED_SEARCH"
    assert body["domain"] == "bathroom"
    assert body["project_type"] == "renovation"
    assert body["requirements"]["area_m2"] == 12
    assert body["requirements"]["quality"] == "medium"
    assert body["template_slug"] == "bathroom_renovation"


def test_interpret_never_returns_catalogue_data(client: TestClient, llm: LLMStub) -> None:
    llm.product_search(terms=["شیر روشویی"], brand="نوجود")
    body = client.post(
        "/api/v1/search/interpret", json={"query": "شیر روشویی برند نوجود"}
    ).json()

    # the interpreter has no field a product could arrive in
    assert "products" not in body
    assert "offers" not in body
    assert "prices" not in body
    # the unknown brand is reported, not invented
    assert body["product_query"]["brand_name"] is None
    assert body["product_query"]["raw_brand"] == "نوجود"


def test_interpret_budget_constraint(client: TestClient, llm: LLMStub) -> None:
    # a bare constraint is neither a product nor a project
    llm.constraint_only(kind="BUDGET", budget=55_000_000)
    body = client.post("/api/v1/search/interpret", json={"query": "بودجه من ۵۵ میلیون است"}).json()
    assert body["requirements"]["budget"] == 55_000_000
    assert body["constraint_kind"] == "BUDGET"


def test_interpret_rejects_empty_query(client: TestClient) -> None:
    assert client.post("/api/v1/search/interpret", json={"query": "x"}).status_code == 422
    assert client.post("/api/v1/search/interpret", json={"query": ""}).status_code == 422


def test_project_requirements_come_from_the_interpretation(
    client: TestClient, llm: LLMStub
) -> None:
    """
    The project's needs are the interpreter's, in the interpreter's order.

    This test used to assert that a bathroom renovation produced the seven roles
    ``bathroom_renovation`` happens to contain. That was the architecture under
    test rather than the contract: the requirement list came from the template,
    and the model's own reading of the sentence had no say in it. It is rewritten
    to state the requirements up front, the way a model would, and check that
    exactly those come back.
    """
    llm.bathroom_project(
        area_m2=12.0,
        requirements=[
            {"description": "توالت فرنگی", "terms": ["توالت"]},
            {"description": "روشویی و کابینت", "terms": ["روشویی"]},
            {"description": "آینه سرویس", "terms": ["آینه"]},
            {"description": "شیر ظرفت", "terms": ["شیر"]},
            {"description": "کاشی و سرامیک", "terms": ["کاشی"]},
        ]
    )
    response = client.post("/api/v1/projects/analyze", json={"query": PROJECT_QUERY})
    assert response.status_code == 200, response.text
    analysis = response.json()["analysis"]

    assert analysis["area_m2"] == 12
    assert analysis["quality"] == "medium"

    # exactly the needs that were stated, in order, keyed by the backend
    labels = [c["label"] for c in analysis["categories"]]
    assert labels == [
        "توالت فرنگی",
        "روشویی و کابینت",
        "آینه سرویس",
        "شیر ظرفت",
        "کاشی و سرامیک",
    ]
    assert [c["role"] for c in analysis["categories"]] == [
        "req_1", "req_2", "req_3", "req_4", "req_5",
    ]

    # what the catalogue covers is still decided by the catalogue
    covered = {c["role"] for c in analysis["candidates"]}
    assert covered == {"req_1", "req_2", "req_3", "req_4"}
    assert [c["role"] for c in analysis["missing_categories"]] == ["req_5"]

    # a need nothing satisfies stays a need, and says which kind of absence it is
    explanations = " ".join(analysis["explanations"])
    assert "کاشی و سرامیک" in explanations


def test_a_project_needs_nothing_from_a_template(client: TestClient, llm: LLMStub) -> None:
    """No template, no refusal.

    A project whose requirements came from a rulebook had to match a rulebook,
    and one that did not was either refused or handed whatever the database
    returned first — which is how a hall ended up 80 m² of refrigerator. The
    requirement list is the model's now, so a project is a project because the
    model said what was needed.
    """
    llm.answer(
        intent="project_search",
        category=None,
        project={
            "type": None,
            "room": "هال",
            "room_token": None,
            "area_m2": None,
            "goal": "گیم بازی کنم",
            "constraints": [],
            "requirements": [
                {"description": "فضایی برای گیم بازی", "terms": ["میز", "صندلی"]},
            ],
        },
        confidence=0.9,
    )
    response = client.post(
        "/api/v1/projects/analyze",
        json={"query": "میخوام یه قسمت به گوشه ی هال خونه اضافه کنم که اونجا گیم بازی کنم"},
    )
    assert response.status_code == 200, response.text
    analysis = response.json()["analysis"]

    # no rulebook was found, and that is not an error
    assert analysis["template_slug"] is None
    assert analysis["area_m2"] is None, "nobody stated an area"
    assert [c["label"] for c in analysis["categories"]] == ["فضایی برای گیم بازی"]
    # and certainly not another project's needs
    assert not {c["role"] for c in analysis["categories"]} & {
        "refrigerator", "washing_machine", "dishwasher", "television", "tiles", "bed",
    }


def test_a_recommendation_is_never_put_in_the_basket(client: TestClient) -> None:
    """A recommendation is advice; the basket is the user's own.

    This used to assert one item per covered requirement. Recommendations are no
    longer added to the basket: the user adds the items they want, from the
    project result. The estimate is still reported, and it is built from the
    catalogue's own prices.
    """
    body = client.post("/api/v1/projects/analyze", json={"query": PROJECT_QUERY}).json()
    basket = body["basket"]
    analysis = body["analysis"]

    assert basket["items_count"] == 0, "nothing may be recommended into a basket"
    assert basket["total"] == 0
    assert analysis["candidates"], "the project should still recommend something"
    assert analysis["estimated_total"] > 0
    for candidate in analysis["candidates"]:
        assert candidate["product"]["id"]
        assert candidate["offer"]["seller"]["name"]
        assert candidate["quantity"] >= 1
        assert candidate["unit_price"] > 0
        assert candidate["line_total"] == candidate["unit_price"] * candidate["quantity"]
        assert candidate["reason"]  # the model's own words, or a deterministic one

    assert analysis["estimated_total"] == sum(
        c["line_total"] for c in analysis["candidates"]
    )


def test_project_estimate_is_built_from_catalogue_prices(
    client: TestClient, llm: LLMStub
) -> None:
    bathroom_project(llm)
    base = client.post("/api/v1/projects/analyze", json={"query": PROJECT_QUERY}).json()
    smaller = client.post(
        "/api/v1/projects/analyze",
        json={"query": PROJECT_QUERY, "constraints": {"area_m2": 6}},
    ).json()

    for body in (base, smaller):
        analysis = body["analysis"]
        # every covered requirement is priced from the catalogue, and the total is
        # their sum — never a stored figure
        assert analysis["estimated_total"] == sum(
            candidate["line_total"] for candidate in analysis["candidates"]
        )
        for candidate in analysis["candidates"]:
            product = client.get(f"/api/v1/products/{candidate['product']['id']}").json()
            assert candidate["unit_price"] == product["offers"][0]["price"]
            assert candidate["line_total"] == candidate["unit_price"] * candidate["quantity"]

    # A need with no quantity rule of its own is one thing whatever the area, so
    # halving the area does not move the covered total. That is reported rather
    # than papered over.
    assert smaller["analysis"]["area_m2"] == 6
    assert smaller["analysis"]["estimated_total"] == base["analysis"]["estimated_total"]
    assert {c["role"] for c in base["analysis"]["missing_categories"]} >= {"req_5"}


def test_project_quality_constraint_is_recorded_but_not_used_for_selection(
    client: TestClient, llm: LLMStub
) -> None:
    """The catalogue states no quality, so it cannot rank anything.

    The request is still recorded and echoed back, and the product chosen is the
    cheapest in the subcategory — not a "low quality" one, because no such thing
    is recorded.
    """
    bathroom_project(llm)
    body = client.post(
        "/api/v1/projects/analyze",
        json={"query": PROJECT_QUERY, "constraints": {"quality": "low"}},
    ).json()
    analysis = body["analysis"]
    assert analysis["quality"] == "low"
    assert {c["quality"] for c in analysis["candidates"]} == {None}
    assert {c["quality_fa"] for c in analysis["candidates"]} == {None}
    # the cheapest catalogue product in the subcategory is the one offered
    # «شیر» resolved to the tap subcategory, and the cheapest tap is offered
    faucet = next(c for c in analysis["candidates"] if c["role"] == "req_4")
    assert faucet["product"]["id"] == "66666666-6666-4666-8666-666666666666"


def test_project_reports_a_quality_floor_it_cannot_check(client: TestClient) -> None:
    """The template still carries a floor, and it is shown to the user.

    Nothing claims the floor was honoured: the catalogue records no quality, so
    the API says the candidate's quality is unknown rather than asserting it
    passes.
    """
    body = client.post("/api/v1/projects/analyze", json={"query": PROJECT_QUERY}).json()
    analysis = body["analysis"]
    categories = {c["role"]: c for c in analysis["categories"]}
    for candidate in analysis["candidates"]:
        assert candidate["quality"] is None
        assert candidate["quality_fa"] is None
        # the requirement's own floor is still a real, reported value
        assert categories[candidate["role"]]["quality_min"] in {
            "low",
            "medium",
            "high",
            "ultra",
        }
    assert any("کیفیت" in e for e in analysis["explanations"])


def test_reanalyze_reports_an_unreachable_budget_honestly(
    client: TestClient, llm: LLMStub
) -> None:
    """The engine already picked the cheapest product in each subcategory.

    So an aggressive budget cannot be met, and the API must say the budget was
    not reached instead of inventing a swap or quietly dropping items.
    """
    bathroom_project(llm)
    created = client.post("/api/v1/projects/analyze", json={"query": PROJECT_QUERY}).json()
    analysis_id = created["analysis"]["id"]
    original_total = created["analysis"]["estimated_total"]

    response = client.post(
        f"/api/v1/projects/{analysis_id}/reanalyze",
        json={"constraints": {"budget": 1_000_000}},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["analysis"]["estimated_total"] == original_total
    assert body["budget_status"]["within_budget"] is False
    # the shortfall is the gap between the budget and the estimate
    assert body["budget_status"]["gap"] == original_total - 1_000_000
    assert "پیدا نشد" in " ".join(body["analysis"]["explanations"])

    # every candidate is the cheapest the catalogue holds for its subcategory
    for candidate in body["analysis"]["candidates"]:
        products = client.get(
            "/api/v1/products/search",
            params={"q": candidate["product"]["name"], "limit": 100},
        ).json()["items"]
        same = [
            p["product"]
            for p in products
            if p["product"]["subcategory"] == candidate["product"]["subcategory"]
        ]
        assert candidate["unit_price"] == min(p["min_price"] for p in same)


def test_project_templates_are_exposed(client: TestClient) -> None:
    templates = client.get("/api/v1/projects/templates").json()
    slugs = {t["slug"] for t in templates}
    assert {"bathroom_renovation", "kitchen_renovation"} <= slugs
    assert all(t["requirement_count"] > 0 for t in templates)


def test_project_analysis_can_be_reloaded(client: TestClient) -> None:
    created = client.post("/api/v1/projects/analyze", json={"query": PROJECT_QUERY}).json()
    analysis_id = created["analysis"]["id"]

    reloaded = client.get(f"/api/v1/projects/{analysis_id}")
    assert reloaded.status_code == 200
    body = reloaded.json()
    assert body["estimated_total"] == created["analysis"]["estimated_total"]
    assert body["basket_id"] == created["basket"]["id"]


@pytest.fixture
def enriched_catalog():
    """Run one test against the real enriched catalogue.

    Choosing a rulebook from a room is entirely metadata-driven, and the
    session-wide fixture catalogue predates the enrichment — no product in it
    carries ``rooms``. This test used to pass against that file, but only because
    the engine had a last-resort branch that handed back an arbitrary template
    when no room could be placed, so it was asserting the bug rather than the
    contract it names. It now reads a catalogue that can express rooms.
    """
    import os
    from pathlib import Path

    from app.catalog.store import reset_cache
    from app.core.config import get_settings

    path = (
        Path(__file__).resolve().parents[3] / "data" / "catalog" / "products_70_enriched.json"
    )
    previous = os.environ.get("CATALOG_PATH")
    os.environ["CATALOG_PATH"] = str(path)
    get_settings.cache_clear()
    reset_cache()
    yield path
    if previous is None:
        os.environ.pop("CATALOG_PATH", None)
    else:
        os.environ["CATALOG_PATH"] = previous
    get_settings.cache_clear()
    reset_cache()


def test_a_project_without_a_category_is_still_a_project(
    client: TestClient, llm: LLMStub, enriched_catalog
) -> None:
    """A missing category is a gap in naming, not a reason to refuse.

    The model names a room and a job but no catalogue category. That used to be a
    422, which sent a real project back as an error. It is now an ordinary
    project: the room and the job are enough, and whatever the catalogue can
    cover is found from the file's own metadata.
    """
    llm.answer(
        intent="project_search",
        project={
            "type": "redesign",
            "room": "پذیرایی",
            "room_token": "living_room",
            "area_m2": None,
            "goal": "تغییر دکور",
            "constraints": [],
            "requirements": [{"description": "مبل راحتی", "terms": ["مبل"]}],
        },
    )
    response = client.post(
        "/api/v1/projects/analyze", json={"query": "دکور پذیرایی رو تغییر بدم"}
    )
    assert response.status_code == 200, response.text
    body = response.json()["analysis"]

    assert body["categories"], "a project without a category still gets needs"
    for entry in body["categories"]:
        assert entry["project_need"] is True
        assert isinstance(entry["catalog_match"], bool)

    # The strong contract, which the room-less fixture catalogue used to make
    # untestable. It used to be "the room chose its own rulebook"; a rulebook no
    # longer defines a project, so the contract is that the need is the
    # interpreter's and the room narrowed what could answer it.
    assert [row["label"] for row in body["categories"]] == ["مبل راحتی"]
    assert body["candidates"], "the enriched catalogue stocks a living-room sofa"
    slugs = {c["slug"] for c in body["available_categories"]}
    assert slugs == {"sofa"}, f"only the sofa answers a living-room sofa, got {slugs}"
    # and it borrowed nothing from a rulebook
    assert body["template_slug"] in (None, "furniture_redesign")


@pytest.fixture(params=["", "   ", "x" * 600])
def bad(request: pytest.FixtureRequest) -> str:
    """A query the endpoint must refuse: empty, whitespace, or over the limit."""
    return str(request.param)


def test_project_query_validation(client: TestClient, bad: str) -> None:
    assert client.post("/api/v1/projects/analyze", json={"query": bad}).status_code == 422


def test_user_facing_copy_uses_persian_digits(client: TestClient, llm: LLMStub) -> None:
    """Every number a user reads must already be Persian in the API payload.

    Backend explanations are rendered verbatim by the UI, so Latin digits here
    would show up as Latin digits on screen.
    """
    latin = re.compile(r"[0-9]")
    created = client.post("/api/v1/projects/analyze", json={"query": PROJECT_QUERY}).json()
    analysis = created["analysis"]

    for line in analysis["explanations"]:
        assert not latin.search(line), line
    for candidate in analysis["candidates"]:
        assert not latin.search(candidate["reason"]), candidate["reason"]

    # The budget is passed, not recovered from the query. This used to send
    # `query` and rely on the endpoint re-interpreting it to find the ceiling —
    # which was the bug that made optimizing a list spend an interpretation call.
    # `query` is still accepted and ignored; the ceiling comes from the request or
    # from the project that produced the list.
    optimized = client.post(
        f"/api/v1/baskets/{created['basket']['id']}/optimize",
        json={"target_budget": 55_000_000, "apply": True},
    ).json()

    assert not latin.search(optimized["explanation"]), optimized["explanation"]
    for line in optimized["trade_offs"]:
        assert not latin.search(line), line
    assert "٬" in optimized["explanation"]  # Persian thousands separator
    for change in optimized["changes"]:
        assert not latin.search(change["reason"]), change["reason"]


def test_interpret_explanations_use_persian_digits(client: TestClient) -> None:
    body = client.post("/api/v1/search/interpret", json={"query": PROJECT_QUERY}).json()
    for line in body["explanations"]:
        assert not re.search(r"[0-9]", line), line


# --------------------------------------------------------------------------- #
# the catalogue boundary
# --------------------------------------------------------------------------- #
class TestProjectCatalogueBoundary:
    def test_available_categories_come_from_the_catalogue(
        self, client: TestClient, llm: LLMStub
    ) -> None:
        """Only subcategories the catalogue really carries are offered."""
        bathroom_project(llm)
        body = client.post("/api/v1/projects/analyze", json={"query": PROJECT_QUERY}).json()
        slugs = {c["slug"] for c in body["analysis"]["available_categories"]}

        assert slugs, "the fixture catalogue covers part of this template"
        # exactly the subcategories tests/fixtures.py carries for this template
        assert slugs <= {"toilet", "sink-faucet", "bathroom-mirror"}
        for category in body["analysis"]["available_categories"]:
            assert category["product_count"] > 0
            # and each one really resolves through the products endpoint
            found = client.get(
                "/api/v1/products/search",
                params={"q": category["name"], "category": category["slug"]},
            ).json()
            assert found["total"] > 0

    def test_missing_categories_carry_the_fixed_note(
        self, client: TestClient, llm: LLMStub
    ) -> None:
        """One wording, so the user is never told two different things."""
        bathroom_project(llm)
        body = client.post("/api/v1/projects/analyze", json={"query": PROJECT_QUERY}).json()
        missing = body["analysis"]["missing_categories"]

        assert missing
        for entry in missing:
            assert entry["in_catalog"] is False
            assert entry["note"] == UNAVAILABLE_NOT_STOCKED
            # The note asserts the need and states the unavailability. It used
            # to speculate ("ممکن است ... موردنیاز باشد"), which read as doubt
            # about a requirement the project genuinely has.
            assert entry["project_need"] is True
            assert entry["catalog_match"] is False

    def test_covered_categories_are_not_listed_as_missing(
        self, client: TestClient, llm: LLMStub
    ) -> None:
        bathroom_project(llm)
        body = client.post("/api/v1/projects/analyze", json={"query": PROJECT_QUERY}).json()
        analysis = body["analysis"]

        covered = {c["role"] for c in analysis["candidates"]}
        missing = {c["role"] for c in analysis["missing_categories"]}
        assert covered and missing
        assert not (covered & missing), "a role cannot be both offered and missing"
        for entry in analysis["missing_categories"]:
            assert entry["note"] == UNAVAILABLE_NOT_STOCKED

    def test_a_missing_category_gets_no_candidate(
        self, client: TestClient, llm: LLMStub
    ) -> None:
        """Nothing may be invented to fill a gap."""
        bathroom_project(llm)
        body = client.post("/api/v1/projects/analyze", json={"query": PROJECT_QUERY}).json()
        analysis = body["analysis"]

        missing = {c["role"] for c in analysis["missing_categories"]}
        assert {c["role"] for c in analysis["candidates"]} & missing == set()
        for candidate in analysis["candidates"]:
            assert client.get(f"/api/v1/products/{candidate['product']['id']}").status_code == 200
            assert candidate["product"]["id"]
            assert candidate["reason"]

    def test_the_titles_word_absence_rather_than_blame(
        self, client: TestClient, llm: LLMStub
    ) -> None:
        bathroom_project(llm)
        body = client.post("/api/v1/projects/analyze", json={"query": PROJECT_QUERY}).json()
        explanations = " ".join(body["analysis"]["explanations"])
        # it says what is missing, not that the project is impossible
        assert "موجود نیست" in explanations or "پیدا نشد" in explanations
        assert "نمی‌توان" not in explanations


# --------------------------------------------------------------------------- #
# complementary products for a whole project
# --------------------------------------------------------------------------- #
class TestProjectComplementary:
    """
    **These tests are failing, and were failing before this change.**

    They exercise ``app.catalog.complementary``, a separate LLM feature that was
    removed: the complementary suggestions a project page offered are now decided
    by the project's own needs and the catalogue's declared relationships, inside
    the project pipeline, with no second model and no second prompt. The
    monkeypatch targets below no longer exist, and the response shape these assert
    is not the one the endpoint returns.

    They are left in place, failing, rather than deleted: the complementary
    behaviour is still wanted, and deciding whether it comes back as part of the
    two-stage pipeline or as its own feature is a product call, not a side effect
    of moving requirements from templates to the interpreter. What was fixed here
    is only that they now fail for *that* reason and not because the project
    happened to have a single need.
    """

    def _analysis(self, client: TestClient, llm: LLMStub) -> dict:
        bathroom_project(llm)
        return client.post(
            "/api/v1/projects/analyze", json={"query": PROJECT_QUERY}
        ).json()["analysis"]

    def test_returns_only_catalogue_products(self, client: TestClient, llm: LLMStub) -> None:
        analysis_id = self._analysis(client, llm)["id"]
        response = client.get(f"/api/v1/projects/{analysis_id}/complementary")
        assert response.status_code == 200
        body = response.json()

        for item in body["items"]:
            assert client.get(f"/api/v1/products/{item['product_id']}").status_code == 200
            assert item["product_id"] == item["product"]["id"]
            assert item["reason"]

    def test_never_offers_something_the_project_already_has(self, client: TestClient, llm: LLMStub) -> None:
        """The fixture catalogue is small enough that a bathroom project exhausts it.

        There is then nothing left to add, and the honest answer is an empty list
        with an explanation — not a duplicate of a product already chosen.
        """
        analysis_id = self._analysis(client, llm)["id"]
        body = client.get(f"/api/v1/projects/{analysis_id}/complementary").json()

        chosen = {
            item["product"]["id"]
            for item in client.get(f"/api/v1/baskets/{self._basket_id(client, analysis_id)}").json()["items"]
        }
        assert not ({i["product_id"] for i in body["items"]} & chosen)
        if not body["items"]:
            assert body["note"], "an empty answer must say why"

    @staticmethod
    def _basket_id(client: TestClient, analysis_id: str) -> str:
        return client.get(f"/api/v1/projects/{analysis_id}").json()["basket_id"]

    def test_never_repeats_a_product_already_in_the_project(self, client: TestClient, llm: LLMStub) -> None:
        analysis = self._analysis(client, llm)
        chosen = {c["product"]["id"] for c in analysis["candidates"]}

        body = client.get(f"/api/v1/projects/{analysis['id']}/complementary").json()
        assert not ({i["product_id"] for i in body["items"]} & chosen)

    def test_never_repeats_itself(self, client: TestClient, llm: LLMStub) -> None:
        analysis = self._analysis(client, llm)
        body = client.get(f"/api/v1/projects/{analysis['id']}/complementary").json()
        ids = [i["product_id"] for i in body["items"]]
        assert len(ids) == len(set(ids))

    def test_uses_at_most_one_model_call(
        self, client: TestClient, llm: LLMStub, monkeypatch
    ) -> None:
        """A project has several products; the model is still asked once."""
        calls: list[dict] = []

        def reply(*, system: str, user: str, **_):
            calls.append({"system": system, "user": user})
            return {"items": []}

        monkeypatch.setattr("app.catalog.complementary.chat_json", reply)
        monkeypatch.setattr("app.catalog.complementary.is_configured", lambda: True)

        analysis = self._analysis(client, llm)
        assert len(analysis["candidates"]) > 1, "the fixture must cover several roles"
        client.get(f"/api/v1/projects/{analysis['id']}/complementary")

        # exactly one call for the whole project, not one per chosen product
        assert len(calls) == 1
        assert "پروژه" in calls[0]["system"]
        for candidate in analysis["candidates"]:
            assert candidate["product"]["name"] in calls[0]["user"]
        # every chosen product is named, so the model sees the whole project
        for candidate in analysis["candidates"]:
            assert candidate["product"]["name"] in calls[0]["user"]

    def test_an_invented_id_never_reaches_the_client(
        self, client: TestClient, llm: LLMStub, monkeypatch
    ) -> None:
        def reply(**_):
            return {
                "items": [
                    {"id": "deadbeef-0000-4000-8000-000000000000", "reason": "ساختگی"},
                ]
            }

        monkeypatch.setattr("app.catalog.complementary.chat_json", reply)
        monkeypatch.setattr("app.catalog.complementary.is_configured", lambda: True)

        analysis = self._analysis(client, llm)
        body = client.get(f"/api/v1/projects/{analysis['id']}/complementary").json()

        assert body["items"] == []
        assert body["discarded_ids"] == ["deadbeef-0000-4000-8000-000000000000"]
        assert body["note"]

    def test_says_when_the_model_is_unavailable(
        self, client: TestClient, llm: LLMStub, monkeypatch
    ) -> None:
        monkeypatch.setattr("app.catalog.complementary.is_configured", lambda: False)
        analysis = self._analysis(client, llm)
        body = client.get(f"/api/v1/projects/{analysis['id']}/complementary").json()

        assert body["llm_available"] is False
        assert "OpenRouter" in body["note"]
        # the fallback is labelled, never presented as a model choice
        assert all(item["source"] == "heuristic" for item in body["items"])

    def test_limit_is_respected(self, client: TestClient, llm: LLMStub) -> None:
        analysis = self._analysis(client, llm)
        for limit in (0, 1, 2):
            body = client.get(
                f"/api/v1/projects/{analysis['id']}/complementary",
                params={"limit": limit},
            ).json()
            assert len(body["items"]) <= limit

    def test_unknown_analysis_is_404(self, client: TestClient, llm: LLMStub) -> None:
        response = client.get(
            "/api/v1/projects/deadbeef-0000-4000-8000-000000000000/complementary"
        )
        assert response.status_code == 404


class TestReasoningStatusIsReported:
    """A 200 must not be mistaken for a successful analysis."""

    def _analyze(self, client: TestClient) -> dict:
        return client.post(
            "/api/v1/projects/analyze", json={"query": PROJECT_QUERY}
        ).json()["analysis"]

    @staticmethod
    def _chooses_the_first_candidate(call: dict) -> str:
        """Answer the reasoning call the way the model should: pick from the
        candidates it was offered, and nothing else.

        Built from the prompt itself, so the test keeps working when the
        candidate set changes instead of hard-coding ids that will rot.
        """
        payload = json.loads(call["user"])
        selections = [
            {
                "requirement_role": group["requirement_role"],
                "product_id": group["candidates"][0]["product_id"],
                "reason": "مناسب‌ترین گزینه برای این پروژه",
            }
            for group in payload["candidates"]
            if group.get("candidates")
        ]
        return json.dumps({
            "selections": selections,
            "complementary": [],
            "basket_actions": [],
            "budget_assessment": {"status": "no_budget", "reason": "بودجه‌ای مشخص نشده"},
            "explanations": [],
        }, ensure_ascii=False)

    def test_a_successful_analysis_says_ok(self, client: TestClient, llm) -> None:
        llm.script = [json.dumps(llm.reply, ensure_ascii=False), self._chooses_the_first_candidate]

        analysis = self._analyze(client)
        assert analysis["reasoning_status"] == "ok"
        # and the stored row agrees with the response, so a later reload does not
        # tell a different story
        again = client.get(f"/api/v1/projects/{analysis['id']}").json()
        assert again["reasoning_status"] == "ok"

    def test_a_failing_reasoning_call_is_visible_in_the_response(
        self, client: TestClient, llm
    ) -> None:
        """The endpoint still answers 200 — so the status has to tell the truth."""
        llm.script = [
            json.dumps(llm.reply, ensure_ascii=False),
            RuntimeError("connection refused by 10.0.0.1:443"),
        ]

        response = client.post("/api/v1/projects/analyze", json={"query": PROJECT_QUERY})
        assert response.status_code == 200
        body = response.json()["analysis"]
        assert body["reasoning_status"] == "failed"
        # the project is still usable: the deterministic candidates are there
        assert body["categories"], "a failed reasoning must not empty the project"
        # but the failure is never dressed up as a considered result
        blob = json.dumps(body, ensure_ascii=False)
        assert "10.0.0.1" not in blob and "connection refused" not in blob
        assert "مدل" in blob, "the user is told the model did not answer"


#: The needs a model states for a bathroom renovation.
#:
#: Supplied explicitly, because a project's requirements are the interpreter's
#: output now. A test that needs a project with one covered need and one the
#: catalogue does not carry now says which is which, instead of relying on
#: whatever a rulebook happened to list.
BATHROOM_NEEDS = [
    {"description": "توالت", "terms": ["توالت"]},
    {"description": "روشویی", "terms": ["روشویی"]},
    {"description": "آینه سرویس", "terms": ["آینه"]},
    {"description": "شیر", "terms": ["شیر"]},
    {"description": "کاشی و سرامیک", "terms": ["کاشی"]},
]


def bathroom_project(llm, **kwargs) -> None:
    """Script the model as answering with :data:`BATHROOM_NEEDS`."""
    llm.bathroom_project(area_m2=12.0, requirements=BATHROOM_NEEDS, **kwargs)


#: The interpretation the runtime log reported, verbatim in substance: a hall the
#: catalogue has no word for, and nothing said about size, quality or budget.
#: Supplying it means the model is never asked, so this test is deterministic.
HALL_INTERPRETATION = {
    "intent": "NEED_SEARCH",
    "project_type": None,
    "room": "هال",
    "room_token": None,
    "goal": "گیم بازی کنم",
    "product_query": None,
    "matched_subcategories": [],
    "requirements": {
        "quality": None,
        "budget": None,
        "area_m2": None,
        "style": None,
    },
    "constraint_kind": "NONE",
    "confidence": 0.9,
    "explanations": [],
}


def test_the_reported_hall_query_borrows_nothing(
    client: TestClient, llm: LLMStub, session
) -> None:
    """«میخوام یه قسمت به گوشه ی هال خونه اضافه کنم که اونجا گیم بازی کنم».

    The interpretation is what the interpreter produced: a hall the catalogue has
    no word for, and nothing said about size, quality or budget. There is no
    template for it and no canonical room token, and under the old architecture
    that combination was fatal in one of two ways — refused, or handed whichever
    template the database returned first, which arrived carrying 80 m², medium
    quality and a refrigerator, a washing machine, a television and a dishwasher.

    Neither may happen now. The requirements are the model's, so a project with
    none is a project with no needs: a 200, nothing borrowed, and the gap stated.
    """
    response = client.post(
        "/api/v1/projects/analyze",
        json={
            "query": "میخوام یه قسمت به گوشه ی هال خونه اضافه کنم که اونجا گیم بازی کنم",
            "interpretation": HALL_INTERPRETATION,
        },
    )

    assert response.status_code == 200, response.text
    analysis = response.json()["analysis"]

    # No rulebook, and no rulebook's opinion about the project
    assert analysis["template_slug"] is None
    assert analysis["area_m2"] is None, "nobody stated an area"
    assert analysis["quality"] == "medium", "a neutral floor, not a template's default"
    assert analysis["project_type"] is None

    # And none of the stranger's requirements, in any form
    blob = json.dumps(response.json(), ensure_ascii=False)
    for role in ("refrigerator", "washing_machine", "dishwasher", "tiles", "vanity"):
        assert role not in blob, f"{role} belongs to another project"
    assert analysis["candidates"] == []

    # The gap is reported rather than hidden, and no model was asked
    assert "نیاز مشخصی" in " ".join(analysis["explanations"])
    assert llm.calls == []

    from sqlalchemy import select

    from app.domains.projects.models import ProjectAnalysis

    stored = session.scalars(select(ProjectAnalysis)).all()
    assert len(stored) == 1
    assert stored[0].template_id is None
    assert stored[0].needs == []
