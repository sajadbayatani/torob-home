"""
Structured product constraints outrank free text.

A query that says what it wants must not be answered with things that merely
share a word with it. The reported case was
«دنبال یه ماشین لباسشویی تا ۳۰ تومن میگردم», which returned fourteen products:
four washing machines, four dishwashers that matched on «ماشین» alone, and six
more — a television, two sinks, a kitchen sink, a dining chair and a desk — that
matched on the filler words «تا» and «یه» happening to sit inside their names.

Three separate things were wrong, and each has its own test below:

* the category was **detected and then ignored** — it was computed after the
  search and only written into the response;
* there was no price filter at all, so a stated ceiling was decoration;
* matching was by substring, so a two-letter filler word was evidence.

These run against the real enriched catalogue, because the legacy fixture file
carries no ``search_terms`` and therefore cannot express the distinction between
«ماشین لباسشویی» and «ماشین ظرفشویی» at all.

The assertions are structural: a resolved category must be a hard constraint, a
ceiling must be respected, and a filler word must never be the reason a product
appears. No expected product list is written down, so these hold as the file
changes.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ENRICHED = Path(__file__).resolve().parents[3] / "data" / "catalog" / "products_70_enriched.json"

REPORTED = "دنبال یه ماشین لباسشویی تا ۳۰ تومن میگردم"
CEILING = 30_000_000


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


def search(client: TestClient, q: str, **params) -> dict:
    response = client.get("/api/v1/products/search", params={"q": q, "limit": 100, **params})
    assert response.status_code == 200, response.text
    return response.json()


def subcategories_of(body: dict) -> set[str]:
    return {item["product"]["category"]["id"] for item in body["items"]}


# --------------------------------------------------------------------------- #
# The reported query
# --------------------------------------------------------------------------- #
def test_the_reported_query_returns_only_washing_machines(
    client: TestClient, session, real_catalog
):
    body = search(client, REPORTED)

    # the category is not merely reported, it is enforced
    assert body["detected_category"] == "washing-machine"
    assert body["total"] >= 1
    assert subcategories_of(body) == {"washing-machine"}, (
        "a resolved category is a hard constraint: nothing outside it may appear"
    )
    # nothing a filler word reached either
    for item in body["items"]:
        assert set(item["matched_terms"]) <= {"ماشین", "لباسشویی"}, (
            f"{item['product']['name']!r} was matched on {item['matched_terms']}"
        )


def test_the_reported_query_honours_the_ceiling_it_states(
    client: TestClient, session, real_catalog
):
    """«تا ۳۰ تومن» is a budget, and it was being read as no budget at all."""
    body = search(client, REPORTED)
    assert body["total"] >= 1, "the cheapest machine is inside the ceiling"
    for item in body["items"]:
        buyable = min(
            offer["price"]
            for offer in item["product"]["offers"]
            if offer.get("available")
        )
        assert buyable <= CEILING, (
            f"{item['product']['name']!r} costs {buyable:,}, above the stated {CEILING:,}"
        )

    # and the ceiling is what decides: raising it admits the expensive ones
    everything = search(client, "ماشین لباسشویی", max_price=1_000_000_000)
    assert everything["total"] > body["total"], (
        "a machine costs more than the ceiling; it is the ceiling that excluded it"
    )
    assert subcategories_of(everything) == {"washing-machine"}


def test_an_explicit_ceiling_outranks_one_read_from_the_query(
    client: TestClient, session, real_catalog
):
    body = search(client, REPORTED, max_price=1_000_000_000)
    assert body["total"] > 1, "the caller's own budget is not second-guessed"
    assert subcategories_of(body) == {"washing-machine"}


def test_a_product_nothing_buyable_cannot_satisfy_a_ceiling(
    client: TestClient, session, real_catalog
):
    """
    A ceiling excludes what cannot be bought, not only what is too dear.

    "Cheaper than the budget" is a claim about a price someone can pay. A
    product whose only offer is unavailable has no such price, and treating it as
    free would put it in front of everything that is actually for sale.
    """
    body = search(client, "ماشین لباسشویی", max_price=1)
    assert body["total"] == 0, "nothing costs one Toman"
    for item in body["items"]:
        assert any(offer.get("available") for offer in item["product"]["offers"])


# --------------------------------------------------------------------------- #
# A bare category name
# --------------------------------------------------------------------------- #
def test_a_bare_washing_machine_query_returns_washing_machines_only(
    client: TestClient, session, real_catalog
):
    body = search(client, "ماشین لباسشویی")
    assert body["total"] >= 1
    assert subcategories_of(body) == {"washing-machine"}


def test_a_bare_dishwasher_query_returns_dishwashers_only(
    client: TestClient, session, real_catalog
):
    """The two kinds of «ماشین» must not be able to answer for each other."""
    body = search(client, "ماشین ظرفشویی")
    assert body["total"] >= 1
    assert subcategories_of(body) == {"dishwasher"}


def test_the_two_kinds_of_machine_are_separated_by_which_word_said_so(
    client: TestClient, session, real_catalog
):
    laundry = search(client, "ماشین لباسشویی")
    dishes = search(client, "ماشین ظرفشویی")
    assert subcategories_of(laundry).isdisjoint(subcategories_of(dishes)), (
        "one shared word must not let either answer for the other"
    )


def test_an_ambiguous_category_is_not_guessed(
    client: TestClient, session, real_catalog
):
    """
    «ماشین» alone does not say which machine, and must not pick one.

    A guess here is the original bug in miniature: a word shared by two
    subcategories resolves to whichever one came first in the file, and the other
    becomes unreachable. Tied readings are therefore reported as no reading, and
    the text decides among the products that mention the word.
    """
    body = search(client, "ماشین")
    assert body["detected_category"] is None, "a tie is not a decision"
    # whatever comes back, it is not presented as a settled category
    assert subcategories_of(body) <= {"washing-machine", "dishwasher"}
    for item in body["items"]:
        assert "ماشین" in item["matched_terms"]


def test_a_brand_does_not_decide_the_category(
    client: TestClient, session, real_catalog
):
    """
    A maker is not a kind of thing.

    «یخچال دوو» names a fridge and a brand. The file lists brands in the same
    ``search_terms`` as kinds — "پاکشوما" sits beside "ماشین لباسشویی" — so a
    detector that counted both heard a tie between the refrigerator and every
    washing machine the brand makes. A tie is no decision, so the category stopped
    being a hard constraint, and a brand-matched washing machine was returned for
    a fridge query. The fridge is the kind of thing asked for, so it wins.
    """
    from app.catalog.store import read_index

    index = read_index(real_catalog)
    body = search(client, "یخچال دوو")
    assert body["detected_category"] == "refrigerator"
    assert subcategories_of(body) == {"refrigerator"}, (
        "a brand must not widen a resolved category into another subcategory"
    )

    # a brand on its own names no kind, and is therefore not detected at all
    brands = index.brand_tokens()
    assert brands, "the file records brands, which is what makes this decidable"
    for brand in sorted(brands)[:20]:
        if any(ch.isalpha() for ch in brand):
            detected = search(client, brand)
            assert detected["detected_category"] is None, (
                f"{brand!r} is a brand; it cannot identify a kind of product"
            )


def test_a_brand_filter_still_narrows_within_the_category(
    client: TestClient, session, real_catalog
):
    """The hard constraint and an explicit brand compose rather than fight."""
    from app.catalog.store import read_index

    index = read_index(real_catalog)
    a_brand = next(
        product.brand
        for product in index.subcategories_of("refrigerator")
        if product.brand
    )
    body = search(client, "یخچال دوو", brand=a_brand)
    assert body["total"] >= 1
    assert subcategories_of(body) == {"refrigerator"}
    assert {item["product"]["brand"]["name"] for item in body["items"]} == {a_brand}


# --------------------------------------------------------------------------- #
# Filler words are not evidence
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "filler", ["یه", "تا", "دنبال", "میگردم", "لطفا", "میخوام"]
)
def test_filler_words_alone_match_nothing(client: TestClient, session, real_catalog, filler):
    from app.catalog.store import evidence_terms, read_index

    # Two independent reasons a filler word cannot be evidence: the closed list
    # of function words, and — for any word not on it — the fact that the file
    # never uses it. The second needs no list, so a filler word nobody thought of
    # is covered too.
    assert evidence_terms(filler, read_index(real_catalog)) == [], (
        f"{filler!r} names nothing in the shop, so it cannot be evidence"
    )
    body = search(client, filler)
    assert body["total"] == 0, f"{filler!r} alone returned products"


def test_a_filler_word_cannot_reach_a_product_it_sits_inside(
    client: TestClient, session, real_catalog
):
    """
    The exact mechanism of the false positives, pinned.

    «تا» is inside «تانیا», «مروارید»-style model names and «متا»; «یه» is inside
    «پایه». Under a substring test those words matched sinks, a television, a
    dining chair and a desk, and a lone match was enough to return a product.
    """
    from app.catalog.store import read_index, search as store_search, CatalogFilters

    index = read_index(real_catalog)
    for filler in ("تا", "یه", "دنبال"):
        matches, total = store_search(index, filler, CatalogFilters())
        assert total == 0, f"{filler!r} matched {total} products by itself"


def test_matched_terms_are_never_a_substring_of_a_name(
    client: TestClient, session, real_catalog
):
    """Every reported match is a whole word of the product it matched."""
    from app.catalog.store import fa_tokens

    body = search(client, "ماشین لباسشویی")
    for item in body["items"]:
        words = set(fa_tokens(item["product"]["name"])) | set(
            fa_tokens(item["product"]["category"]["name"])
        )
        for term in item["matched_terms"]:
            assert term in words, (
                f"{term!r} was reported as a match but is not a word of "
                f"{item['product']['name']!r}"
            )


# --------------------------------------------------------------------------- #
# One spelling of each category
# --------------------------------------------------------------------------- #
def test_the_appliance_category_has_one_spelling(client: TestClient, session, real_catalog):
    """
    The file says "appliances", the enum says "appliance", and the two were
    compared against each other directly.

    So ``domain=appliance`` — the only value the parameter would accept — matched
    no products at all, and returned an empty page for a category holding twenty-
    two of them.
    """
    body = search(client, "ماشین لباسشویی", domain="appliance")
    assert body["total"] >= 1, "the public spelling of the domain must filter"
    assert body["detected_domain"] == "appliance"
    assert subcategories_of(body) <= {
        "washing-machine", "dishwasher", "refrigerator", "microwave",
        "built-in-oven", "cooktop", "kitchen-hood", "washing-machine",
        "vacuum-cleaner", "television",
    }


def test_facets_and_detected_domain_agree_on_the_spelling(
    client: TestClient, session, real_catalog
):
    from app.core.enums import Domain

    facets = client.get("/api/v1/products/facets").json()
    values = {facet["value"] for facet in facets["categories"]}
    for value in values:
        assert Domain(value), f"{value!r} is a facet value but not a domain"
    assert "appliance" in values and "appliances" not in values, (
        "the plural spelling is the file's, not the API's; it must not leak out"
    )

    body = search(client, "ماشین لباسشویی")
    assert body["detected_domain"] in values, (
        "the domain reported on a search must be a value the facets also offer"
    )


def test_both_spellings_fold_to_one_category():
    from app.catalog.store import canonical_category
    from app.core.enums import domain_from

    assert canonical_category("appliances") == canonical_category("appliance")
    assert domain_from("appliances") is domain_from("appliance")
    # a category the vocabulary does not know is returned as the file has it,
    # rather than dropped
    assert canonical_category("garden") == "garden"
    assert canonical_category(None) is None
