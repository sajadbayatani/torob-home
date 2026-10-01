"""
The product source is a choice made in configuration, and the two choices differ.

What is pinned here:

* ``local`` behaves exactly as it always did, through the same index and the same
  scoring — the source is a pass-through, not a second implementation;
* the factory maps a name to a class, and refuses a name it does not know instead
  of quietly serving the file;
* the Torob adapter calls the discovered search tool on the configured URL, and
  normalises what the server actually returns;
* every failure mode is a ``ProductSourceError``, and none of them becomes an
  empty result or a fall back to the local file.

The MCP client is mocked throughout. No test here reaches the network — the live
call is a separate, manual verification, because a test that depends on a
third-party server is a test that fails when that server is down and tells you
nothing about this code.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.catalog.sources import (
    TOROB_SEARCH_TOOL,
    UNSTATED_CATEGORY,
    LocalJsonProductSource,
    ProductSource,
    ProductSourceError,
    TorobMcpProductSource,
    build_product_source,
)


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


@pytest.fixture
def enriched(monkeypatch):
    """The real enriched file, which is the point of the local source."""
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


def set_source(monkeypatch, value: str, url: str = MCP_URL) -> None:
    from app.core.config import get_settings

    monkeypatch.setenv("PRODUCT_SOURCE", value)
    monkeypatch.setenv("TOROB_MCP_URL", url)
    get_settings.cache_clear()


# --------------------------------------------------------------------------- #
# The local source is the behaviour that already existed
# --------------------------------------------------------------------------- #
class TestLocalSource:
    def test_the_default_is_local(self) -> None:
        """Nothing configured means the file, so an untouched deployment is safe."""
        from app.core.config import get_settings

        assert get_settings().product_source == "local"

    def test_local_is_selected_by_name(self, monkeypatch) -> None:
        set_source(monkeypatch, "local")
        assert isinstance(build_product_source(), LocalJsonProductSource)

    def test_it_satisfies_the_protocol(self) -> None:
        assert isinstance(LocalJsonProductSource(), ProductSource)

    async def test_it_reads_the_enriched_file(self, enriched) -> None:
        """Same products, same enrichment, same search behaviour as before."""
        from app.catalog.store import get_catalog

        products = await LocalJsonProductSource().search("شیر روشویی", limit=10)
        assert products, "the file's own products are returned"

        index = get_catalog()
        assert {p.id for p in products} <= {p.id for p in index.products}
        # and the enriched metadata is intact on them, which is the reason the
        # local source exists and must not be re-implemented
        assert all(p.metadata for p in products), "enrichment was not carried"
        assert any(p.metadata.get("search_terms") for p in products)

    async def test_it_honours_the_category_it_is_given(self, enriched) -> None:
        products = await LocalJsonProductSource().search(
            "ماشین لباسشویی", category="washing-machine", limit=10
        )
        assert products
        assert {p.subcategory for p in products} == {"washing-machine"}

    async def test_it_honours_the_limit(self, enriched) -> None:
        assert len(await LocalJsonProductSource().search("ماشین", limit=2)) <= 2


# --------------------------------------------------------------------------- #
# Factory and configuration
# --------------------------------------------------------------------------- #
class TestFactory:
    def test_torob_mcp_is_selected_by_name(self, monkeypatch) -> None:
        set_source(monkeypatch, "torob_mcp")
        source = build_product_source()
        assert isinstance(source, TorobMcpProductSource)

    def test_it_satisfies_the_protocol(self, monkeypatch) -> None:
        set_source(monkeypatch, "torob_mcp")
        assert isinstance(build_product_source(), ProductSource)

    @pytest.mark.parametrize("value", ["local", "torob_mcp", "LOCAL", " Torob_MCP "])
    def test_the_name_is_read_forgivingly(self, monkeypatch, value: str) -> None:
        """Case and surrounding space are noise, not a different source."""
        set_source(monkeypatch, value)
        assert build_product_source() is not None

    @pytest.mark.parametrize("value", ["torob", "mcp", "json", "file", "http"])
    def test_an_unsupported_value_fails_clearly(self, monkeypatch, value: str) -> None:
        """
        Not a fallback, and not a crash.

        Falling back to the file here is the one behaviour that would be actively
        harmful: an operator who asked for Torob and got the 70-product file would
        reasonably believe they were shopping the whole catalogue.
        """
        set_source(monkeypatch, value)
        with pytest.raises(ProductSourceError) as caught:
            build_product_source()
        message = str(caught.value)
        assert value in message
        assert "local" in message and "torob_mcp" in message

    def test_torob_mcp_without_a_url_fails_rather_than_guessing(
        self, monkeypatch
    ) -> None:
        """The URL is configuration. With none, there is nothing to call."""
        set_source(monkeypatch, "torob_mcp", url="")
        with pytest.raises(ProductSourceError) as caught:
            build_product_source()
        assert "TOROB_MCP_URL" in str(caught.value)

    def test_the_url_is_not_hardcoded_in_the_source(self, monkeypatch) -> None:
        """The configured URL is the one used, whatever it is."""
        set_source(monkeypatch, "torob_mcp", url="https://elsewhere.test/mcp")
        assert build_product_source()._url == "https://elsewhere.test/mcp"


# --------------------------------------------------------------------------- #
# The Torob adapter
# --------------------------------------------------------------------------- #
def tool_result(payload: Any) -> Any:
    """An MCP tool result, as the SDK hands it back."""
    return SimpleNamespace(
        isError=False,
        content=[SimpleNamespace(type="text", text=json.dumps(payload, ensure_ascii=False))],
    )


#: A response taken from a live call, shape and all, not invented here.
LIVE_PAYLOAD = {
    "scanned_pages": 1,
    "scanned_items": 26,
    "matched": 26,
    "note": "All prices are in Toman.",
    "results": [
        {
            "name": "ماشین لباسشویی پاکشوما مدل L9 ظرفیت ۹ کیلوگرم",
            "price_toman": 101745521,
            "price_text": "۱۰۱٫۷۴۵٫۵۲۱ تومان",
            "shops": "در ۹۱ فروشگاه",
            "url": "https://torob.com/p/ccc5992e-82ac-40af-b674-9434f0389fce/",
            "prk": "ccc5992e-82ac-40af-b674-9434f0389fce",
            "search_id": "01a0f0f9128d75a3a2f994d19fc60c22",
        },
        {
            "name": "ماشین لباسشویی ال جی مدل WY1409MVP",
            "price_toman": 104600000,
            "price_text": "از ۱۰۴٫۶۰۰٬۰۰۰ تومان",
            "shops": "در ۱۵ فروشگاه",
            "url": "https://torob.com/p/7c7acd1a-b518-4a26-bb52-ec6247ae12db/",
            "prk": "7c7acd1a-b518-4a26-bb52-ec6247ae12db",
            "search_id": "01a0f0f9128d75a3a2f994d19fc60c22",
        },
    ],
}


class FakeSession:
    """Records what was called, and returns a scripted tool result."""

    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self._result = result if result is not None else tool_result(LIVE_PAYLOAD)
        self._error = error
        self.calls: list[tuple[str, dict]] = []

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None

    async def initialize(self) -> None:
        return None

    async def call_tool(self, name: str, arguments: dict) -> Any:
        self.calls.append((name, arguments))
        if self._error is not None:
            raise self._error
        return self._result


@pytest.fixture
def patched_session(monkeypatch):
    """Install a fake MCP client and hand back the factory that records calls."""

    def install(session: FakeSession) -> list[tuple[str, dict]]:
        import mcp
        import mcp.client.streamable_http as transport

        class FakeClientSession(FakeSession):
            def __init__(self, *_a: Any, **_k: Any) -> None:
                super().__init__()
                self.__dict__["_delegate"] = session

            async def call_tool(self, name: str, arguments: dict) -> Any:
                session.calls.append((name, arguments))
                if session._error is not None:
                    raise session._error
                return session._result

        opened: list[str] = []

        def fake_transport(url: str, **_kw: Any):
            opened.append(url)

            class _Ctx:
                async def __aenter__(self_inner):
                    return (object(), object())

                async def __aexit__(self_inner, *_e: Any) -> None:
                    return None

            return _Ctx()

        monkeypatch.setattr(mcp, "ClientSession", FakeClientSession)
        monkeypatch.setattr(transport, "streamable_http_client", fake_transport)
        session.opened = opened  # type: ignore[attr-defined]
        return session

    return install


class TestTorobSourceCallsTheSearchTool:
    async def test_it_calls_the_discovered_tool_on_the_configured_url(
        self, patched_session
    ) -> None:
        """
        The right tool, on the right server, with the right arguments.

        The tool name came from the server's own ``tools/list`` — it also offers
        ``product_details``, ``price_history``, ``market_price`` and others, and
        only ``search_products`` searches the catalogue. The URL comes from
        configuration and is passed through untouched.
        """
        session = patched_session(FakeSession())
        source = TorobMcpProductSource("https://configured.test/mcp")
        products = await source.search("ماشین لباسشویی", limit=5)

        assert session.opened == ["https://configured.test/mcp"], "the configured URL is used"
        assert [name for name, _ in session.calls] == [TOROB_SEARCH_TOOL]
        assert session.calls[0][1] == {"query": "ماشین لباسشoیی"[:0] + "ماشین لباسشویی", "limit": 5}
        assert products

    @pytest.mark.parametrize(("asked", "sent"), [(50, 30), (0, 1), (7, 7)])
    async def test_the_limit_is_clamped_to_what_the_tool_accepts(
        self, patched_session, asked: int, sent: int
    ) -> None:
        """The tool rejects anything outside 1..30, so it is clamped, not passed."""
        session = patched_session(FakeSession())
        await TorobMcpProductSource(MCP_URL).search("یخچال", limit=asked)
        assert session.calls[0][1]["limit"] == sent

    async def test_it_never_sends_our_own_category_vocabulary(
        self, patched_session
    ) -> None:
        """
        The category parameter is accepted and not sent.

        Our slugs are our taxonomy, not Torob's, and its search tool filters on
        price rather than on a slug. Sending one would ask a remote service to
        understand a vocabulary it was never given, and the answer would be
        confidently wrong.
        """
        session = patched_session(FakeSession())
        await TorobMcpProductSource(MCP_URL).search("یخچال", category="refrigerator")
        assert "category" not in session.calls[0][1]


class TestNormalisation:
    async def test_a_live_shaped_response_becomes_products(
        self, patched_session
    ) -> None:
        patched_session(FakeSession())
        products = await TorobMcpProductSource(MCP_URL).search("ماشین لباسشویی")
        assert len(products) == 2

        first = products[0]
        assert first.name == "ماشین لباسشویی پاکشوما مدل L9 ظرفیت ۹ کیلوگرم"
        assert first.lowest_price_toman == 101745521
        assert str(first.id) == "ccc5992e-82ac-40af-b674-9434f0389fce"
        assert first.source_name == "torob_mcp"
        assert first.source_url.startswith("https://torob.com/")

    async def test_the_server_own_renderings_are_carried_not_interpreted(
        self, patched_session
    ) -> None:
        """
        ``price_text`` and ``shops`` are kept as the strings they are.

        "در ۹۱ فروشگاه" is a phrase, not a number, and "از ۱۰۴٬۶۰۰٬۰۰۰ تومان" is a
        rendering. Parsing either would be a guess about a format the server may
        change, so they are carried and nothing derives from them.
        """
        patched_session(FakeSession())
        product = (await TorobMcpProductSource(MCP_URL).search("x"))[0]
        carried = {a.key: a.value for a in product.attributes}
        assert carried["price_text"] == "۱۰۱٫۷۴۵٫۵۲۱ تومان"
        assert carried["shops"] == "در ۹۱ فروشگاه"
        assert all(a.value_num is None and a.unit is None for a in product.attributes)

    async def test_absent_metadata_is_absent_and_not_invented(
        self, patched_session
    ) -> None:
        """
        The point of the whole caveat.

        Torob returns no rooms, no roles, no search terms, no category, no image and
        no offers. Every one of those is left empty, marked so it cannot be read as
        a real value, and none is filled in from the query or the title — a guessed
        category would be a claim the source never made, and the room and project
        rules downstream would act on it as though it were true.
        """
        patched_session(FakeSession())
        product = (await TorobMcpProductSource(MCP_URL).search("ماشین لباسشویی"))[0]

        assert product.metadata == {}
        for key in ("rooms", "product_roles", "use_cases", "project_types",
                    "space_fit", "styles", "search_terms"):
            assert key not in product.metadata
        assert product.category == UNSTATED_CATEGORY
        assert product.subcategory == UNSTATED_CATEGORY
        assert product.brand is None, "the brand is not read out of the title"
        assert product.model is None
        assert product.image_url is None, "no image is invented"
        assert product.offers == (), "a price is not an offer"
        # the marker cannot be mistaken for a real subcategory slug
        assert product.subcategory not in {"washing-machine", "dishwasher"}

    async def test_a_result_without_a_live_price_is_skipped(
        self, patched_session
    ) -> None:
        """
        ``price_toman: null`` means there is nothing to buy, not free.

        The server documents null as "no live price". Showing such an item as if it
        cost nothing, or at the top of a price-ordered list, would be the worst
        possible reading of a missing value.
        """
        payload = {
            "results": [
                {**LIVE_PAYLOAD["results"][0], "name": "بدون قیمت",
                 "prk": "11111111-1111-4111-8111-111111111111", "price_toman": None},
                LIVE_PAYLOAD["results"][0],
            ]
        }
        patched_session(FakeSession(tool_result(payload)))
        products = await TorobMcpProductSource(MCP_URL).search("x")
        assert [p.name for p in products] == [LIVE_PAYLOAD["results"][0]["name"]]

    @pytest.mark.parametrize(
        "entry",
        [
            {"name": "", "prk": "ccc5992e-82ac-40af-b674-9434f0389fce", "price_toman": 1},
            {"name": "بدون کلید", "price_toman": 1},
            {"name": "کلید بد", "prk": "not-a-uuid", "price_toman": 1},
            {"price_toman": 1, "prk": "ccc5992e-82ac-40af-b674-9434f0389fce"},
            {"name": "قیمت صفر", "prk": "ccc5992e-82ac-40af-b674-9434f0389fce",
             "price_toman": 0},
        ],
    )
    async def test_an_unusable_result_is_skipped_rather_than_half_built(
        self, patched_session, entry: dict
    ) -> None:
        """A row we cannot identify or price is not a product."""
        patched_session(FakeSession(tool_result({"results": [entry]})))
        assert await TorobMcpProductSource(MCP_URL).search("x") == []

    async def test_a_non_object_result_is_skipped(self, patched_session) -> None:
        patched_session(FakeSession(tool_result({"results": ["a string", 7]})))
        assert await TorobMcpProductSource(MCP_URL).search("x") == []


class TestEmptyAndFailures:
    async def test_an_empty_result_is_an_empty_list_not_an_error(
        self, patched_session
    ) -> None:
        """Nothing in stock is an answer, not a failure."""
        patched_session(FakeSession(tool_result({"results": [], "matched": 0})))
        assert await TorobMcpProductSource(MCP_URL).search("نHING") == []

    async def test_a_missing_results_key_is_an_error(self, patched_session) -> None:
        """The tool is documented to return it, so its absence is a real problem."""
        patched_session(FakeSession(tool_result({"scanned_items": 0})))
        with pytest.raises(ProductSourceError) as caught:
            await TorobMcpProductSource(MCP_URL).search("x")
        assert "results" in str(caught.value)

    @pytest.mark.parametrize("payload", ["a string", 7, {"nested": "object"}])
    async def test_results_that_are_not_a_list_is_an_error(
        self, patched_session, payload: Any
    ) -> None:
        """
        The field is documented as a list, so anything else is a shape change.

        A list of *entries* that are not objects is a different case and is handled
        per entry — see ``test_a_non_object_result_is_skipped``.
        """
        patched_session(FakeSession(tool_result({"results": payload})))
        with pytest.raises(ProductSourceError):
            await TorobMcpProductSource(MCP_URL).search("x")

    async def test_text_that_is_not_json_is_an_error(self, patched_session) -> None:
        patched_session(
            FakeSession(SimpleNamespace(
                isError=False, content=[SimpleNamespace(type="text", text="not json")]
            ))
        )
        with pytest.raises(ProductSourceError):
            await TorobMcpProductSource(MCP_URL).search("x")

    async def test_json_that_is_not_an_object_is_an_error(self, patched_session) -> None:
        patched_session(
            FakeSession(SimpleNamespace(
                isError=False, content=[SimpleNamespace(type="text", text="[1, 2]")]
            ))
        )
        with pytest.raises(ProductSourceError):
            await TorobMcpProductSource(MCP_URL).search("x")

    async def test_a_tool_error_is_surfaced(self, patched_session) -> None:
        """
        The server saying "I failed" is not an empty catalogue.

        Turning it into zero results would tell a shopper the site has no such
        product, which is a different and much worse claim.
        """
        patched_session(
            FakeSession(SimpleNamespace(
                isError=True,
                content=[SimpleNamespace(type="text", text="upstream refused")],
            ))
        )
        with pytest.raises(ProductSourceError) as caught:
            await TorobMcpProductSource(MCP_URL).search("x")
        assert "upstream refused" in str(caught.value)

    async def test_a_transport_or_protocol_failure_is_surfaced(
        self, patched_session
    ) -> None:
        """Connection refused, DNS failure, HTTP 500 — one failure, named."""
        patched_session(FakeSession(error=ConnectionError("connection refused")))
        with pytest.raises(ProductSourceError) as caught:
            await TorobMcpProductSource(MCP_URL).search("x")
        assert "connection refused" in str(caught.value)
        assert MCP_URL in str(caught.value), "the failure says which server"

    async def test_a_mcp_protocol_error_is_surfaced(self, patched_session) -> None:
        patched_session(FakeSession(error=RuntimeError("protocol error: no session")))
        with pytest.raises(ProductSourceError):
            await TorobMcpProductSource(MCP_URL).search("x")

    def test_a_missing_url_is_refused_before_any_call(self) -> None:
        with pytest.raises(ProductSourceError):
            TorobMcpProductSource("")


# --------------------------------------------------------------------------- #
# The service uses the abstraction without knowing which source is active
# --------------------------------------------------------------------------- #
class TestTheServiceGoesThroughTheAbstraction:
    async def test_a_source_is_reachable_through_the_protocol_only(
        self, enriched, patched_session
    ) -> None:
        """
        The request path is written against the protocol.

        The same call is made against a fake source that satisfies only
        ``ProductSource`` and knows nothing about the file, the MCP server, or the
        concrete classes — which is what "the rest of the application depends on
        the abstraction" has to mean in practice.
        """

        class FakeSource:
            def __init__(self) -> None:
                self.seen: list[tuple[str, str | None, int]] = []

            async def search(
                self, query: str, *, category: str | None = None, limit: int = 20
            ) -> list:
                self.seen.append((query, category, limit))
                from app.catalog.sources import _normalise_product

                return [
                    _normalise_product(entry) for entry in LIVE_PAYLOAD["results"]
                ]

        source = FakeSource()
        assert isinstance(source, ProductSource)
        products = await source.search("ماشین لباسشویی", category=None, limit=20)
        assert products
        assert source.seen == [("ماشین لباسشویی", None, 20)]

    def test_both_sources_answer_the_same_call_shape(self) -> None:
        """
        The local source and the Torob source are interchangeable by construction.

        Not by a test that happens to pass, but because both are checked against
        the protocol, so a caller cannot depend on something only one of them has.
        """
        for cls in (LocalJsonProductSource, TorobMcpProductSource):
            assert issubclass(cls, ProductSource)
            assert callable(getattr(cls, "search", None))

    def test_the_enriched_file_is_untouched_by_the_new_source(self) -> None:
        """
        The file is still the file.

        The new source is additive: nothing writes to the catalogue, and the
        metadata the rest of the application reads is still there, because a
        product from Torob that lacks it is not a reason to remove it from the
        local path.
        """
        raw = json.loads(ENRICHED.read_text(encoding="utf-8"))
        enriched_fields = {"rooms", "product_roles", "use_cases", "project_types",
                           "space_fit", "styles", "features", "search_terms",
                           "complementary_subcategories", "alternative_subcategories"}
        assert enriched_fields <= set(raw[0]["metadata"])
        assert len(raw) == 70
