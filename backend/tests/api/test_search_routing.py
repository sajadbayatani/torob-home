"""
The cost property: an obvious product search costs nothing.

Every test here runs against the real endpoints with the provider stubbed, so
``llm.calls`` is an assertion about the number of inferences the request actually
made. Nothing reaches a network.

This is the behaviour the routing change exists for, so it is pinned in the API
rather than only in a unit test: a matcher that is right in isolation and
consulted too late would still cost an inference, and only a request-level count
catches that.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from tests.llm_stub import LLMStub

ENRICHED_CATALOG = (
    Path(__file__).resolve().parents[3] / "data" / "catalog" / "products_70_enriched.json"
)


@pytest.fixture(scope="module")
def catalog_file(tmp_path_factory):
    """The enriched catalogue — the matcher reads ``search_terms``."""
    path = tmp_path_factory.mktemp("catalog-enriched") / "products.json"
    path.write_text(ENRICHED_CATALOG.read_text(encoding="utf-8"), encoding="utf-8")
    previous = os.environ.get("CATALOG_PATH")
    os.environ["CATALOG_PATH"] = str(path)
    from app.catalog.store import reset_cache
    from app.core.config import get_settings

    get_settings.cache_clear()
    reset_cache()
    yield path
    if previous is None:
        os.environ.pop("CATALOG_PATH", None)
    else:
        os.environ["CATALOG_PATH"] = previous
    get_settings.cache_clear()
    reset_cache()


@pytest.fixture
def recording_client():
    """
    A client that records the **inbound** request paths.

    The LLM stub records the outbound provider call, which is a good measure of
    cost but not of the claim that matters here: that the application never
    *invoked* the interpretation endpoint. That is a statement about the request
    path, so it is measured on the request path.
    """
    from app.db.session import reset_engine
    from app.main import app

    seen: list[str] = []

    class _Recorder:
        """Wraps the app and notes the path of every HTTP request through it."""

        def __init__(self, application) -> None:
            self._application = application

        async def __call__(self, scope, receive, send) -> None:
            if scope.get("type") == "http":
                seen.append(scope.get("path", ""))
            await self._application(scope, receive, send)

    reset_engine()
    with TestClient(_Recorder(app)) as test_client:
        yield test_client, seen
    reset_engine()


#: Every one of these must be answered with no inference at all.
OBVIOUS_PRODUCT_QUERIES = [
    # The one the running app reported as still reaching the interpreter.
    "سینک ظرفشویی",
    "تخت خواب",
    "شیر توالت",
    "شیر توالت خوب میخوام",
    "یه شیر توالت خوب میخوام",
    "یخچال سامسونگ",
    "تلویزیون ۵۵ اینچ",
    "میز ناهارخوری",
    "تخت خواب دو نفره",
    "ماشین لباسشویی",
]

#: These must reach the interpreter, which is the point of the asymmetry.
MUST_REACH_THE_MODEL = [
    "اتاق خوابم رو میخوام تغییر دکوراسیون بدم",
    "آشپزخونه‌م رو میخوام بازسازی کنم",
    "برای اتاق خوابم چی لازم دارم؟",
    "یه گوشه هال رو برای گیم آماده کنم",
    "میخوام خونه‌م رو مدرن کنم",
    "برای خونه جدیدم وسایل میخوام",
]

AMBIGUOUS = [
    "برای آشپزخونه یه چیز خوب میخوام",
    "برای آشپزخونه یه چیز خوب میخادم",
    "برای حموم شیر و آینه میخوام",
    "برای اتاق خواب تخت و کمد میخوام",
]


# --------------------------------------------------------------------------- #
# The routing endpoint itself: free, and never asks the model
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("query", OBVIOUS_PRODUCT_QUERIES)
def test_the_router_answers_without_the_model(client: TestClient, llm: LLMStub, query):
    response = client.get("/api/v1/search/route", params={"q": query})
    assert response.status_code == 200
    body = response.json()
    assert body["route"] == "product", f"{query!r} -> {body}"
    assert body["is_product"] is True
    assert body["unexplained"] == []
    assert llm.calls == [], f"routing must not infer: {query!r}"


@pytest.mark.parametrize("query", MUST_REACH_THE_MODEL + AMBIGUOUS)
def test_the_router_defers_to_the_model(client: TestClient, llm: LLMStub, query):
    response = client.get("/api/v1/search/route", params={"q": query})
    assert response.status_code == 200
    body = response.json()
    assert body["route"] == "llm", f"{query!r} was guessed into {body}"
    assert body["is_product"] is False
    assert llm.calls == [], "the router decides by itself or not at all"


# --------------------------------------------------------------------------- #
# The property itself, measured in inferences
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("query", OBVIOUS_PRODUCT_QUERIES)
def test_an_obvious_product_search_makes_zero_llm_calls(
    client: TestClient, llm: LLMStub, catalog_file, query
):
    """
    The whole change, as one assertion.

    A caller consults the router, is told ``product``, and searches. No
    interpretation is requested and none is made.
    """
    decision = client.get("/api/v1/search/route", params={"q": query}).json()
    assert decision["route"] == "product"

    response = client.get("/api/v1/products/search", params={"q": query})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"], f"{query!r} should find something"
    assert body["intent"] == "PRODUCT_SEARCH"

    assert llm.calls == [], f"{query!r} cost {len(llm.calls)} inferences"


def test_a_product_search_does_not_pay_for_its_own_explanation(
    client: TestClient, llm: LLMStub, catalog_file
):
    """
    The search still explains itself, for free.

    It used to attach a model interpretation to every result list. The
    deterministic verdict says the same thing without the inference, and is
    labelled as coming from the catalogue rather than the model.
    """
    response = client.get("/api/v1/products/search", params={"q": "شیر توالت"})
    body = response.json()
    assert body["intent"] == "PRODUCT_SEARCH"
    assert body["explanations"], "a search still says why it did what it did"
    assert llm.calls == []


def test_asking_for_the_model_explanation_still_works(
    client: TestClient, llm: LLMStub, catalog_file
):
    """
    The free path is the default, not the only path.

    A caller that genuinely wants a model explanation can still ask for one, and
    gets one. What changed is that it has to be asked for.
    """
    llm.answer(intent="product_search", search={"text": "شیر توالت", "terms": ["شیر", "توالت"]})
    response = client.get(
        "/api/v1/products/search", params={"q": "شیر توالت", "interpret": "true"}
    )
    assert response.status_code == 200
    assert len(llm.calls) == 1, "an explicit request is honoured, and costs one call"


@pytest.mark.parametrize("query", MUST_REACH_THE_MODEL)
def test_a_project_query_reaches_the_model_exactly_once(
    client: TestClient, llm: LLMStub, query
):
    """
    The uncertain path is unchanged: one interpretation, and the project flow
    continues from there.
    """
    llm.project(requirements=[{"description": "چیزی برای این کار", "terms": ["مبل"]}])
    decision = client.get("/api/v1/search/route", params={"q": query}).json()
    assert decision["route"] == "llm"

    response = client.post("/api/v1/search/interpret", json={"query": query})
    assert response.status_code == 200, response.text
    assert len(llm.calls) == 1, f"{query!r} cost {len(llm.calls)} inferences"


def test_the_router_needs_no_session_and_no_llm_configuration(
    client: TestClient, monkeypatch
):
    """
    Routing must work when there is no model at all.

    If deciding a product search needed a configured provider, the saving would be
    theoretical. It does not: the answer is in the catalogue file.
    """
    import app.llm as llm_module

    def refuse(**_kwargs):
        raise AssertionError("routing must not reach the model")

    monkeypatch.setattr(llm_module, "chat_json", refuse)
    response = client.get("/api/v1/search/route", params={"q": "ماشین لباسشویی"})
    assert response.status_code == 200
    assert response.json()["route"] == "product"


def test_a_blank_query_is_refused_by_the_router(client: TestClient):
    assert client.get("/api/v1/search/route", params={"q": ""}).status_code == 422


# --------------------------------------------------------------------------- #
# The call budget is unchanged for everything that does reach the model
# --------------------------------------------------------------------------- #
def test_a_new_project_query_costs_one_interpretation_plus_reasoning(
    client: TestClient, llm: LLMStub, catalog_file
):
    """
    Routing adds nothing.

    A project query is interpreted once, and the candidate reasoning is a second
    call when there are candidates to reason about. The deterministic router sits
    in front of both and is not a call, so the total is what it always was.
    """
    llm.project(
        room="پذیرایی",
        room_token="living_room",
        requirements=[{"description": "مبل راحتی", "terms": ["مبل"]}],
    )
    query = "دکوراسیون پذیرایی خونه م رو میخوام تغییر بدم"

    decision = client.get("/api/v1/search/route", params={"q": query}).json()
    assert decision["route"] == "llm"

    response = client.post("/api/v1/projects/analyze", json={"query": query})
    assert response.status_code == 200, response.text
    analysis = response.json()["analysis"]
    assert analysis["categories"], "the project has needs, so reasoning had work to do"
    # one interpretation, one candidate reasoning
    assert len(llm.calls) == 2, [c["url"] for c in llm.calls]


def test_a_project_with_no_candidates_costs_only_the_interpretation(
    client: TestClient, llm: LLMStub, catalog_file
):
    """
    With nothing to choose between there is no second call.

    The reasoning stage is skipped rather than run on an empty question — the
    behaviour that existed before routing, and that routing must not disturb.
    """
    llm.project(
        room="هال",
        requirements=[{"description": "چیزی که کاتالوگ ندارد", "terms": ["خیزان"]}],
    )
    query = "برای هالم یه خیزان میخوام"
    assert client.get("/api/v1/search/route", params={"q": query}).json()["route"] == "llm"

    response = client.post("/api/v1/projects/analyze", json={"query": query})
    assert response.status_code == 200, response.text
    assert response.json()["analysis"]["reasoning_status"] == "not_needed"
    assert len(llm.calls) == 1, [c["url"] for c in llm.calls]


# --------------------------------------------------------------------------- #
# The application path, end to end
# --------------------------------------------------------------------------- #
def test_the_application_never_invokes_the_interpretation_endpoint(
    recording_client, llm: LLMStub, catalog_file
):
    """
    The whole point, as a request sequence rather than a unit of logic.

    This is what a search box does: ask the matcher, and if the matcher is sure,
    search. The interpretation endpoint is **not called at all** — not called and
    then declined, not called and answered from a cache. If the routing regressed
    to "interpret first", the assertion on the URL below is what would catch it,
    and the count of inferences would go to one.

    The other half of the test is that the matcher is what decided. It reads the
    catalogue file, so this is a claim about the data, not about a phrase list.
    """
    client, paths = recording_client
    query = "سینک ظرفشویی"

    # 1. the free, deterministic decision
    decision = client.get("/api/v1/search/route", params={"q": query}).json()
    assert decision["route"] == "product", decision

    # 2. the search the application runs next
    response = client.get("/api/v1/products/search", params={"q": query})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"], "a strong product match must actually find something"
    assert body["intent"] == "PRODUCT_SEARCH"

    # 3. and the interpretation endpoint was never involved — not called, not
    # called and declined, not called and served from a cache
    assert paths == [
        "/api/v1/search/route",
        "/api/v1/products/search",
    ], f"unexpected request path: {paths}"
    assert llm.calls == [], f"the product path cost {len(llm.calls)} inferences"


def test_a_project_query_does_invoke_the_interpretation_endpoint(
    recording_client, llm: LLMStub
):
    """
    The other half of the contract, and the reason the first test means anything.

    When the matcher is unsure the application *does* go to the interpreter, and
    the model is asked what the person wants. Silently guessing product search
    here is the failure mode this design exists to avoid.
    """
    client, paths = recording_client
    query = "اتاق خوابم رو میخوام تغییر دکوراسیون بدم"
    llm.project(
        room="اتاق خواب",
        room_token="bedroom",
        requirements=[{"description": "تخت خواب", "terms": ["تخت"]}],
    )

    decision = client.get("/api/v1/search/route", params={"q": query}).json()
    assert decision["route"] == "llm", decision
    assert decision["unexplained"], "a fall-through names what it could not place"

    response = client.post("/api/v1/search/interpret", json={"query": query})
    assert response.status_code == 200, response.text
    # the endpoint was genuinely invoked, and that is what cost the inference
    assert paths == [
        "/api/v1/search/route",
        "/api/v1/search/interpret",
    ], f"unexpected request path: {paths}"
    assert len(llm.calls) == 1


def test_an_ambiguous_query_is_not_guessed_into_a_product_search(
    client: TestClient, llm: LLMStub
):
    """
    «برای آشپزخونه یه چیز خوب میخوام» names no product and asks for something in
    a room. The matcher declines, the model is asked, and the endpoint that is
    called proves the application took the uncertain path.
    """
    query = "برای آشپزخونه یه چیز خوب میخوام"
    llm.answer(
        intent="project_search",
        category=None,
        project={
            "type": "renovation", "room": "آشپزخانه", "room_token": "kitchen",
            "area_m2": None, "goal": "بازسازی", "constraints": [],
            "requirements": [{"description": "کابینت", "terms": ["کابینت"]}],
        },
    )

    assert client.get("/api/v1/search/route", params={"q": query}).json()["route"] == "llm"
    response = client.post("/api/v1/search/interpret", json={"query": query})
    assert response.status_code == 200, response.text
    assert response.json()["intent"] == "NEED_SEARCH"
    assert len(llm.calls) == 1
