"""
Where products come from, as one thing the rest of the application can ask.

The product data used to be *the file*: `data/catalog/products_70_enriched.json`,
read once and indexed. This module keeps that as one implementation of the idea and
adds a second, so a deployment can choose between them from configuration:

* :class:`LocalJsonProductSource` — the enriched file, through the existing
  ``app.catalog.store`` index. No second loader, and the enriched metadata the
  rest of the application depends on is untouched.
* :class:`TorobMcpProductSource` — Torob's own MCP server, over Streamable HTTP.

**The source is a data source and nothing else.** It obtains products. It does not
interpret a query, decide an intent, rank, choose, price, or reason — all of that
stays where it is, upstream. The Torob server is called for one thing, the product
search tool, and its answer is normalised into the same
:class:`~app.catalog.store.CatalogProduct` the file produces, so the filtering and
ranking downstream are the same code either way. Nothing MCP-shaped escapes this
module.

Two limits follow from the file and the server being genuinely different, and both
are reported rather than papered over:

* **Torob does not return the enriched metadata.** No ``rooms``, ``product_roles``,
  ``search_terms``, nothing. Those are absent, not guessed, so the rules that read
  them — room scope, space fit, project-type eligibility — have nothing to read for
  a Torob product. Enriching them at runtime would mean a second model and a second
  source of truth, so it is not done.
* **Torob does not return offers.** A search result is a name, a lowest price and a
  URL. The offer list arrives from a second tool, which this source deliberately
  does not call, because the brief is a product source and not a second crawl of
  the site. A product with no offers is not purchasable, so product *search* works
  and project *candidate* generation does not.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol, runtime_checkable

from app.catalog.store import CatalogProduct
from app.core.config import get_settings

logger = logging.getLogger(__name__)

#: The MCP tool that returns products. Discovered from the server's own
#: ``tools/list``, not assumed: the server also offers ``product_details``,
#: ``price_history``, ``compare_products``, ``find_best_value``, ``market_price``
#: and ``special_offers``, and only this one searches the catalogue.
TOROB_SEARCH_TOOL = "search_products"

#: MCP protocol version requested at initialisation. The server reported
#: "2025-06-18" when asked, and is asked for the same back.
MCP_PROTOCOL_VERSION = "2025-06-18"

#: What ``category``/``subcategory`` hold when the source did not state one.
#:
#: ``CatalogProduct`` requires a category, and every value in the file is a real
#: one. Torob returns no category at all, and the two obvious options are both
#: wrong: inventing one from the query would be a claim the source never made, and
#: leaving it empty would break every consumer that reads the field. This is an
#: explicit marker meaning "not stated", it is checked for wherever a category is
#: consumed, and it deliberately looks like nothing the catalogue contains so it
#: cannot be mistaken for one.
UNSTATED_CATEGORY = "unstated"


class ProductSourceError(RuntimeError):
    """
    A product source could not answer.

    Raised for a connection failure, an MCP protocol error, a tool response that is
    not what the tool is documented to return, and an unsupported
    ``PRODUCT_SOURCE``.

    It is never turned into an empty result. A deployment that chose ``torob_mcp``
    asked for Torob, and answering from the local file instead — even silently, even
    with stale or thinner data — would be a different product than the one the
    operator chose. The failure stays visible.
    """


@runtime_checkable
class ProductSource(Protocol):
    """The only thing the application asks a product source for."""

    async def search(
        self,
        query: str,
        *,
        category: str | None = None,
        limit: int = 20,
    ) -> list[CatalogProduct]:
        """
        Products for a query, best first.

        ``category`` is a canonical subcategory slug when the caller has one; a
        source that cannot honour it says so rather than ignoring it.
        """
        ...


class LocalJsonProductSource:
    """
    The enriched file, through the index that already exists.

    Deliberately a thin pass-through: :func:`app.catalog.store.search` already
    reads the file, validates it, caches it by mtime, applies the category and
    budget constraints and ranks. Re-implementing any of that here is how the same
    rule ends up in two places and one of them drifts, so this calls it and returns
    what it returns.
    """

    def __init__(self) -> None:
        from app.catalog.store import CatalogFilters, get_catalog, search

        self._index_of = get_catalog
        self._search_of = search
        self._filters_of = CatalogFilters

    async def search(
        self,
        query: str,
        *,
        category: str | None = None,
        limit: int = 20,
    ) -> list[CatalogProduct]:
        # A `CatalogError` from here is the file's own failure and already carries
        # a Persian message and a status code, so it propagates untouched rather
        # than being reworded into a source failure.
        filters = self._filters_of(category=category)
        matches, _total = self._search_of(
            self._index_of(), query, filters, limit=limit, detected_category=category
        )
        return [match.product for match in matches]


class TorobMcpProductSource:
    """
    Torob's MCP server, as a product source.

    One tool is called, :data:`TOROB_SEARCH_TOOL`, and its ``results`` array is
    normalised. The shape this was written against, taken from a live call to the
    server rather than assumed::

        {"results": [
            {"name": str,            # the product title
             "price_toman": int?,   # null when there is no live price
             "price_text": str,     # the server's own rendering, kept as an attribute
             "shops": str,          # a Persian phrase, e.g. "در ۹۱ فروشگاه"
             "url": str,
             "prk": str,            # a uuid, and Torob's stable product key
             "search_id": str}      # needed by product_details; carried, unused
        ]}

    The server answered ``initialize`` without a session header and accepted a
    subsequent ``tools/call`` on the same connection, so it is stateless and one
    short-lived client per search is the correct lifecycle — cheap, and nothing is
    held between requests. Connection reuse would be an optimisation for a
    throughput problem this does not have, and a pooled client is exactly the kind
    of background infrastructure the brief rules out.
    """

    def __init__(self, url: str, *, timeout_seconds: float = 20.0) -> None:
        if not url:
            raise ProductSourceError(
                "PRODUCT_SOURCE=torob_mcp نیاز به TOROB_MCP_URL دارد، اما تنظیم نشده است."
            )
        self._url = url
        self._timeout = timeout_seconds

    async def search(
        self,
        query: str,
        *,
        category: str | None = None,
        limit: int = 20,
    ) -> list[CatalogProduct]:
        """
        Ask Torob for products and normalise what comes back.

        ``category`` is **not** sent. Torob's search tool takes a free-text query
        and filters on price, not on a canonical slug, and this application's
        slugs are its own vocabulary rather than Torob's — sending one would be
        asking a remote service to understand a taxonomy it has never been told
        about, and the results would be silently wrong. The field is accepted so
        the protocol stays uniform, and it is recorded as unused here.
        """
        del category
        raw = await self._call_tool({"query": query, "limit": _clamp_limit(limit)})
        results = raw.get("results")
        if results is None:
            raise ProductSourceError(
                "پاسخ ابزار جستجوی Torob کلید «results» را ندارد؛ "
                f"کلیدهای دریافتی: {sorted(raw)}"
            )
        if not isinstance(results, list):
            raise ProductSourceError("«results» در پاسخ Torob یک فهرست نیست.")

        products: list[CatalogProduct] = []
        for entry in results[:limit]:
            product = _normalise_product(entry)
            if product is not None:
                products.append(product)
        logger.info(
            "torob_mcp search query=%r asked=%s normalised=%s scanned=%s",
            query, len(results), len(products), raw.get("scanned_items"),
        )
        return products

    async def _call_tool(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Initialise, list nothing, call the search tool, return its parsed body."""
        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamable_http_client
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ProductSourceError(
                "برای PRODUCT_SOURCE=torob_mcp بستهٔ «mcp» لازم است."
            ) from exc

        try:
            async with streamable_http_client(self._url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(TOROB_SEARCH_TOOL, arguments)
        except Exception as exc:  # noqa: BLE001 - every failure is one source failure
            # Transport, HTTP, and MCP protocol errors all land here. The cause is
            # kept so the operator can see whether it was the URL, the network, or
            # the server refusing.
            raise ProductSourceError(
                f"ارتباط با سرور MCP توبرب (TOROB_MCP_URL={self._url}) ناموفق بود: {exc}"
            ) from exc

        if getattr(result, "isError", False):
            raise ProductSourceError(
                f"ابزار {TOROB_SEARCH_TOOL} خطا برگرداند: {_first_text(result)[:200]}"
            )
        return _parse_tool_payload(result)


def _parse_tool_payload(result: Any) -> dict[str, Any]:
    """Turn an MCP tool result into the JSON object the tool documents."""
    text = _first_text(result)
    if not text:
        raise ProductSourceError("پاسخ ابزار Torob بدون متن بود.")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        # The server answered with something that is not a tool result. It says so
        # itself when its own upstream misbehaves — "Torob answered HTTP 490" is
        # what a rate-limited upstream looks like from here — so the text is
        # reported verbatim rather than summarised, because that line is the only
        # thing that says *which* upstream failed.
        raise ProductSourceError(
            f"سرور MCP توبرب به‌جای نتیجهٔ ابزار، این متن را برگرداند: {text[:300]!r}"
        ) from exc
    if not isinstance(payload, dict):
        raise ProductSourceError("متن پاسخ ابزار Torob یک شیء JSON نبود.")
    return payload


def _first_text(result: Any) -> str:
    """The first text block of an MCP tool result, or '' when there is none."""
    for block in getattr(result, "content", None) or ():
        text = getattr(block, "text", None)
        if isinstance(text, str) and text.strip():
            return text
    return ""


def _clamp_limit(limit: int) -> int:
    """The tool accepts 1..30, and rejects anything outside it."""
    return max(1, min(int(limit), 30))


def _normalise_product(entry: Any) -> CatalogProduct | None:
    """
    One Torob result as a :class:`CatalogProduct`.

    Only fields the response actually carries are mapped. ``prk`` is Torob's
    stable product key and is a uuid, so it becomes the id the rest of the
    application already uses — which is what lets a Torob product be linked to,
    priced and compared exactly like a file product.

    Everything Torob does not say is left absent: no brand is read out of the
    title, no category is guessed from the query, no image is invented, and no
    offer is synthesised from a price. A result missing a name or a usable id is
    skipped rather than half-built.
    """
    from uuid import UUID

    if not isinstance(entry, dict):
        logger.warning("torob_mcp: skipping a result that is not an object")
        return None
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        logger.warning("torob_mcp: skipping a result with no name")
        return None
    try:
        # prk is a uuid; a url is not, so a url-only result cannot be identified
        # and is skipped rather than given a fabricated id.
        product_id = UUID(str(entry.get("prk", "")).strip())
    except (ValueError, AttributeError, TypeError):
        logger.warning("torob_mcp: skipping %r, no usable prk", name[:60])
        return None

    price = entry.get("price_toman")
    # The server documents price_toman as null — never 0 — when there is no live
    # price. Such a product cannot be bought at any price, so the file's own
    # "a price must be present and positive" rule applies and it is skipped rather
    # than shown as free.
    if not isinstance(price, int) or isinstance(price, bool) or price <= 0:
        logger.info("torob_mcp: skipping %r, no live price", name[:60])
        return None

    attributes = tuple(
        _attribute(key, value)
        for key, value in (
            ("price_text", entry.get("price_text")),
            ("shops", entry.get("shops")),
        )
        if isinstance(value, str) and value.strip()
    )
    return CatalogProduct(
        id=product_id,
        name=name.strip(),
        category=UNSTATED_CATEGORY,
        subcategory=UNSTATED_CATEGORY,
        brand=None,
        model=None,
        # Torob's search result carries no image. Left absent: the projection
        # already treats a missing image as null and the UI omits it.
        image_url=None,
        source_name="torob_mcp",
        source_url=entry.get("url") if isinstance(entry.get("url"), str) else None,
        lowest_price_toman=price,
        attributes=attributes,
        # No offer list: a search result is a price, not a set of sellers. This is
        # why a Torob product is not purchasable, and the limitation is real.
        offers=(),
        metadata={},
    )


def _attribute(key: str, value: str) -> Any:
    """
    One of the server's own renderings, carried as an attribute.

    ``price_text`` and ``shops`` are strings the server produces, not fields the
    application knows anything about, so they are carried the way the file carries
    a string attribute and nothing derives from them. ``value_num`` and ``unit``
    are ``None`` because a rendered price and a shop count are not numbers this
    application should compare.
    """
    from app.catalog.store import CatalogAttribute

    return CatalogAttribute(
        key=key, label=key, value=value, value_num=None, unit=None
    )


def build_product_source() -> ProductSource:
    """
    The source the settings ask for.

    An unrecognised ``PRODUCT_SOURCE`` fails here, loudly, rather than quietly
    falling back to the file: the operator asked for something the application does
    not have, and serving them a different source without saying so is the failure
    mode this whole module exists to avoid.
    """
    settings = get_settings()
    choice = (settings.product_source or "local").strip().lower()

    if choice == "local":
        return LocalJsonProductSource()
    if choice == "torob_mcp":
        return TorobMcpProductSource(settings.torob_mcp_url)
    raise ProductSourceError(
        f"PRODUCT_SOURCE={choice!r} پشتیبانی نمی‌شود. "
        "مقادیر مجاز: local | torob_mcp"
    )


__all__ = [
    "MCP_PROTOCOL_VERSION",
    "TOROB_SEARCH_TOOL",
    "UNSTATED_CATEGORY",
    "LocalJsonProductSource",
    "ProductSource",
    "ProductSourceError",
    "TorobMcpProductSource",
    "build_product_source",
]
