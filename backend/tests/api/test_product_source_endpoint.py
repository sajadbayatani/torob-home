"""
The product-search endpoint answers from whichever source is configured.

These are integration-level: the request goes through the real router, the real
projection and the real response schema, and only the source is substituted. The
point is the one the task turns on — the endpoint does not know or care which
source answered, so a Torob product is returned in the same shape as a file
product, and a source failure becomes a source failure rather than an empty page.

The MCP client is mocked; no test here reaches the network.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.catalog.sources import TOROB_SEARCH_TOOL


@pytest.fixture(autouse=True)
def _no_settings_leak():
    """
    `Settings` is cached, and `monkeypatch.setenv` only restores the environment.

    Without this the cache keeps a `PRODUCT_SOURCE` that has been un-set, and the
    next test in the session silently reads a Torob source with no MCP client
    patched — a failure that looks like a bug in the endpoint rather than in the
    fixture that caused it.
    """
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()

ENRICHED = Path(__file__).resolve().parents[3] / "data" / "catalog" / "products_70_enriched.json"
MCP_URL = "https://torob-mcp.example.test/mcp"

#: Taken from a live call to the server, not invented.
MCP_RESULTS = [
    {
        "name": "ماشین لباسشویی پاکشوما مدل L9 ظرفیت ۹ کیلوگرم",
        "price_toman": 101745521,
        "price_text": "۱۰۱٫۷۴۵٬۵۲۱ تومان",
        "shops": "در ۹۱ فروشگاه",
        "url": "https://torob.com/p/ccc5992e-82ac-40af-b674-9434f0389fce/",
        "prk": "ccc5992e-82ac-40af-b674-9434f0389fce",
        "search_id": "01a0f0f9128d75a3a2f994d19fc60c22",
    },
    {
        "name": "ماشین لباسشویی ایکس ویژن مدل TG72",
        "price_toman": 64000000,
        "price_text": "از ۶۴٬۰۰۰٬۰۰۰ تومان",
        "shops": "در ۳۲ فروشگاه",
        "url": "https://torob.com/p/7c7acd1a-b518-4a26-bb52-ec6247ae12db/",
        "prk": "7c7acd1a-b518-4a26-bb52-ec6247ae12db",
        "search_id": "01a0f0f9128d75a3a2f994d19fc60c22",
    },
]


@pytest.fixture
def enriched(monkeypatch):
    from app.catalog.store import reset_cache
    from app.core.config import get_settings

    previous = os.environ.get("CATALOG_PATH")
    monkeypatch.setenv("CATALOG_PATH", str(ENRICHED))
    get_settings.cache_clear()
    reset_cache()
    yield
    if previous is None:
        os.environ.pop("CATALOG_PATH", None)
    else:
        os.environ["CATALOG_PATH"] = previous
    get_settings.cache_clear()
    reset_cache()


@pytest.fixture
def fake_mcp(monkeypatch):
    """
    Replace the MCP client, recording the call.

    ``fail`` makes the transport raise, which is the case that matters: it must
    not turn into an empty result set.
    """
    state: dict[str, Any] = {"calls": [], "opened": [], "results": MCP_RESULTS, "fail": None}

    import mcp
    import mcp.client.streamable_http as transport

    class FakeSession:
        def __init__(self, *_streams: Any, **_kw: Any) -> None:
            # the real class is constructed as ClientSession(read, write); a fake
            # that does not accept them fails for a reason unrelated to this code
            self.streams = _streams

        async def __aenter__(self) -> FakeSession:
            return self

        async def __aexit__(self, *_e: Any) -> None:
            return None

        async def initialize(self) -> None:
            return None

        async def call_tool(self, name: str, arguments: dict) -> Any:
            state["calls"].append((name, arguments))
            if state["fail"] is not None:
                raise state["fail"]
            return SimpleNamespace(
                isError=False,
                content=[
                    SimpleNamespace(
                        type="text", text=json.dumps({"results": state["results"]})
                    )
                ],
            )

    def fake_transport(url: str, **_kw: Any):
        state["opened"].append(url)

        class _Ctx:
            async def __aenter__(self_inner):
                return (object(), object())

            async def __aexit__(self_inner, *_e: Any) -> None:
                return None

        return _Ctx()

    monkeypatch.setattr(mcp, "ClientSession", FakeSession)
    monkeypatch.setattr(transport, "streamable_http_client", fake_transport)
    return state


def configure(monkeypatch, source: str, url: str = MCP_URL) -> None:
    from app.core.config import get_settings

    monkeypatch.setenv("PRODUCT_SOURCE", source)
    monkeypatch.setenv("TOROB_MCP_URL", url)
    get_settings.cache_clear()


# --------------------------------------------------------------------------- #
# local — unchanged
# --------------------------------------------------------------------------- #
class TestLocalIsUnchanged:
    def test_it_answers_from_the_enriched_file(
        self, client: TestClient, session, enriched, monkeypatch
    ) -> None:
        configure(monkeypatch, "local")
        body = client.get("/api/v1/products/search", params={"q": "ماشین لباسشویی"}).json()
        assert body["total"] >= 1
        subcategories = {item["product"]["subcategory"] for item in body["items"]}
        assert subcategories == {"washing-machine"}
        # the enriched metadata-driven answers are all still there
        assert body["detected_category"] == "washing-machine"
        assert body["detected_domain"] == "appliance"
        assert body["facets"]["categories"]

    def test_a_query_asking_for_a_fixture_product_still_behaves(
        self, client: TestClient, session, monkeypatch
    ) -> None:
        """The session fixture catalog, untouched: same answers as before."""
        before = client.get("/api/v1/products/search", params={"q": "شیر روشویی"}).json()
        configure(monkeypatch, "local")
        after = client.get("/api/v1/products/search", params={"q": "شیر روشویی"}).json()
        assert before["total"] == after["total"] == 3


# --------------------------------------------------------------------------- #
# torob_mcp
# --------------------------------------------------------------------------- #
class TestTheEndpointThroughTorobMcp:
    def test_it_reaches_the_configured_mcp_source(
        self, client: TestClient, session, fake_mcp, monkeypatch
    ) -> None:
        configure(monkeypatch, "torob_mcp", url="https://configured.test/mcp")
        body = client.get(
            "/api/v1/products/search", params={"q": "ماشین لباسشویی"}
        ).json()

        assert fake_mcp["opened"] == ["https://configured.test/mcp"]
        assert [name for name, _ in fake_mcp["calls"]] == [TOROB_SEARCH_TOOL]
        assert fake_mcp["calls"][0][1]["query"] == "ماشین لباسشویی"
        assert body["total"] == 2

    def test_torob_products_come_back_in_the_normal_response_shape(
        self, client: TestClient, session, fake_mcp, monkeypatch
    ) -> None:
        """
        The same ``ProductOut`` the file path returns.

        This is what "do not expose MCP-specific structures" has to mean: the
        response is the application's own shape, and nothing about the transport is
        visible in it.
        """
        configure(monkeypatch, "torob_mcp")
        body = client.get("/api/v1/products/search", params={"q": "ماشین لباسشویی"}).json()

        first = body["items"][0]["product"]
        assert first["name"] == MCP_RESULTS[0]["name"]
        assert first["min_price"] == 101745521
        assert first["id"] == "ccc5992e-82ac-40af-b674-9434f0389fce"
        assert first["slug"] == first["id"]
        assert first["image_url"] is None, "absent, not invented"
        assert first["offers"] == [], "no offers were claimed"
        assert first["source_url"].startswith("https://torob.com/")
        # the same keys a file product has
        assert {"id", "name", "category", "offers", "min_price", "subcategory"} <= set(first)

    def test_the_facets_describe_the_products_that_answered(
        self, client: TestClient, session, fake_mcp, monkeypatch
    ) -> None:
        """
        Not the local file's catalogue.

        Reporting the file's 70 products as facets next to two Torob results would
        offer filters for things this response does not contain.
        """
        configure(monkeypatch, "torob_mcp")
        body = client.get("/api/v1/products/search", params={"q": "ماشین لباسشویی"}).json()
        facet_counts = {f["value"] for f in body["facets"]["categories"]}
        assert facet_counts <= {"unstated"}, facet_counts
        assert sum(f["count"] for f in body["facets"]["categories"]) == 2

    def test_an_empty_result_is_an_empty_page_not_an_error(
        self, client: TestClient, session, fake_mcp, monkeypatch
    ) -> None:
        fake_mcp["results"] = []
        configure(monkeypatch, "torob_mcp")
        response = client.get("/api/v1/products/search", params={"q": "چیزی نیست"})
        assert response.status_code == 200
        assert response.json()["total"] == 0
        assert response.json()["items"] == []

    def test_a_source_failure_is_a_source_failure(
        self, client: TestClient, session, fake_mcp, monkeypatch
    ) -> None:
        """
        Never an empty page, and never the local file.

        Both would be lies: an empty page says the site has nothing, and the local
        file would serve 70 demo products for a Torob search without saying so.
        """
        fake_mcp["fail"] = ConnectionError("connection refused")
        configure(monkeypatch, "torob_mcp")
        response = client.get("/api/v1/products/search", params={"q": "ماشین لباسشویی"})
        assert response.status_code == 502
        assert "منبع محصول" in response.json()["detail"]
        assert "connection refused" in response.json()["detail"]

    def test_a_per_request_override_selects_the_source(
        self, client: TestClient, session, fake_mcp, monkeypatch
    ) -> None:
        """Configuration stands, but one request may ask for the other."""
        configure(monkeypatch, "local")
        body = client.get(
            "/api/v1/products/search",
            params={"q": "ماشین لباسشویی", "product_source": "torob_mcp"},
        ).json()
        assert body["total"] == 2
        assert fake_mcp["calls"], "the request went to the MCP source"

    def test_an_unknown_override_is_refused(
        self, client: TestClient, session, enriched, monkeypatch
    ) -> None:
        configure(monkeypatch, "local")
        response = client.get(
            "/api/v1/products/search", params={"q": "یخچال", "product_source": "nope"}
        )
        assert response.status_code == 400
        assert "local" in response.json()["detail"]


# --------------------------------------------------------------------------- #
# The endpoint does not branch on which source it got
# --------------------------------------------------------------------------- #
class TestTheShapeIsSourceAgnostic:
    def _shape(self, body: dict) -> set[str]:
        return set(body) if body["items"] == [] else set(body["items"][0]["product"])

    def test_both_sources_produce_the_same_response_keys(
        self, client: TestClient, session, fake_mcp, enriched, monkeypatch
    ) -> None:
        """
        Compared structurally, not field by field.

        If the MCP path needed its own response shape, this would differ — and a
        caller would have to know which source was in use to read the answer.
        """
        configure(monkeypatch, "local")
        local = client.get(
            "/api/v1/products/search", params={"q": "ماشین لباسشویی"}
        ).json()
        configure(monkeypatch, "torob_mcp")
        remote = client.get(
            "/api/v1/products/search", params={"q": "ماشین لباسشویی"}
        ).json()

        assert set(local) == set(remote), "the response shape is the same"
        assert self._shape(local) == self._shape(remote)
        assert local["items"][0].keys() == remote["items"][0].keys()


class TestInterpretStillReachesTheModel:
    def test_asking_for_an_explanation_costs_one_call(
        self, client: TestClient, llm, session, catalog_file
    ) -> None:
        """
        The regression this module nearly shipped.

        The endpoint became async so a remote source can be awaited, and the
        interpretation helper was still calling ``asyncio.run`` — which cannot run
        inside a running loop. It raised, the helper's broad ``except`` caught it,
        and the search answered normally with no explanation and no model call at
        all. A 200 that looks fine and is quietly missing the thing that was asked
        for, which is why the helper now logs when it swallows.
        """
        llm.answer(
            intent="product_search", search={"text": "شیر توالت", "terms": ["شیر", "توالت"]}
        )
        response = client.get(
            "/api/v1/products/search", params={"q": "شیر توالت", "interpret": "true"}
        )
        assert response.status_code == 200
        assert len(llm.calls) == 1, "the model is asked when it is asked for"
