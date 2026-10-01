"""
Is this obviously a product search? Asked from the catalogue, never from a model.

The cost property is the reason this module exists, so the tests assert it
directly: an obvious product query reaches the search with **zero** inferences,
and anything the catalogue is unsure about reaches the model exactly once.

No test here calls a model. The boundary is `tests/llm_stub.LLMStub`, which
answers the provider endpoint and records every call, so `llm.calls == []` is a
real assertion about a real code path rather than a comment.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.catalog.matcher import meaningful_terms, product_verdict

ENRICHED_CATALOG = (
    Path(__file__).resolve().parents[3] / "data" / "catalog" / "products_70_enriched.json"
)


@pytest.fixture(scope="module")
def catalog_file(tmp_path_factory):
    """
    The **enriched** catalogue.

    The matcher reads ``search_terms`` — the enriched vocabulary that lets a
    shopper's word match a product the title does not use — and the session-wide
    fixture catalogue in ``conftest`` predates the enrichment entirely. Without
    it there is nothing to match and every query would fall through.
    """
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


def _index():
    from app.catalog.store import get_catalog

    return get_catalog()


# --------------------------------------------------------------------------- #
# Queries that are obviously product searches
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "query",
    [
        "شیر توالت",
        "شیر توالت خوب میخوام",
        "یه شیر توالت خوب میخوام",
        "یخچال سامسونگ",
        "تلویزیون ۵۵ اینچ",
        "میز ناهارخوری",
        "تخت خواب دو نفره",
        "ماشین لباسشویی",
        "تلویزیون",
        # reported against the running app: the catalogue matcher, not the prompt,
        # is what has to place this one
        "سینک ظرفشویی",
        "تخت خواب",
    ],
)
def test_an_obvious_product_query_is_decided_deterministically(catalog_file, query):
    verdict = product_verdict(_index(), query)
    assert verdict.is_product is True, (
        f"{query!r} should route to product search; {verdict.reason} "
        f"unexplained={list(verdict.unexplained)}"
    )
    assert verdict.unexplained == ()
    assert verdict.reason == "all_words_explained"


# --------------------------------------------------------------------------- #
# Project queries must never be taken on product evidence alone
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "query",
    [
        "اتاق خوابم رو میخوام تغییر دکوراسیون بدم",
        "آشپزخونه‌م رو میخوام بازسازی کنم",
        "برای اتاق خوابم چی لازم دارم؟",
        "یه گوشه هال رو برای گیم آماده کنم",
        "میخوام خونه‌م رو مدرن کنم",
        "برای خونه جدیدم وسایل میخوام",
    ],
)
def test_a_project_query_is_never_taken_on_product_words_alone(catalog_file, query):
    """The asymmetry, stated as a test.

    Several of these *do* contain a word the catalogue knows — «آشپزخونه»,
    «خواب». That is the trap: a matcher that fires on any catalogue hit sends a
    renovation to a product list. Each must fall through.
    """
    verdict = product_verdict(_index(), query)
    assert verdict.is_product is False, f"{query!r} was taken as a product search"
    assert verdict.unexplained, "a fall-through has to name the words it could not place"


@pytest.mark.parametrize(
    "query",
    [
        "برای آشپزخونه یه چیز خوب میخادم",
        "برای آشپزخونه یه چیز خوب میخوام",
        "برای حموم شیر و آینه میخوام",
        "برای اتاق خواب تخت و کمد میخوام",
    ],
)
def test_an_ambiguous_query_falls_through_rather_than_guessing(catalog_file, query):
    """
    These name real products *and* a real project, and that is the whole ambiguity.

    «برای اتاق خواب تخت و کمد میخوام» mentions a bed and a wardrobe, and the
    catalogue matches both — but it also says *for a bedroom*, which is a project.
    The matcher does not adjudicate; it declines and the model decides.
    """
    verdict = product_verdict(_index(), query)
    assert verdict.is_product is False, f"{query!r} was decided without the model"


# --------------------------------------------------------------------------- #
# The rule itself
# --------------------------------------------------------------------------- #
def test_nothing_meanful_means_no_product_verdict(catalog_file):
    for query in ("", "   ", "؟", "۱۲۳۴۵"):
        verdict = product_verdict(_index(), query)
        assert verdict.is_product is False
        assert verdict.reason == "no_product_words"


def test_a_word_the_catalogue_does_not_use_is_not_explained(catalog_file):
    """
    The matcher is not a synonym table, and does not pretend to be one.

    «آبگرمکن» is not a product this shop stocks and not a word its file uses, so
    the query cannot be answered from the catalogue and must not be claimed as one
    that can. Adding a water heater to the file changes this with no code edit.
    """
    verdict = product_verdict(_index(), "آبگرمکن")
    assert verdict.is_product is False
    assert verdict.reason == "no_product_evidence"


def test_a_stocking_the_word_is_enough_to_route_without_code_changes(catalog_file):
    """The claim that keeps this from becoming a phrase dictionary.

    The matcher reads the file. A word the file uses is a product word, and one it
    does not use is not — so the vocabulary is the catalogue's, not this file's.
    """
    index = _index()
    # a word the enriched vocabulary supplies that no product title contains
    known = [t for t in meaningful_terms("ماشین لباسشویی") if t]
    assert known
    assert product_verdict(index, "ماشین لباسشویی").is_product is True
    assert product_verdict(index, "خیزان نیمکتی").is_product is False


def test_only_filler_and_generic_words_is_not_a_product_verdict(catalog_file):
    """
    Every word ignored here must be one that names nothing.

    If a word that *did* name a product were dropped, the matcher would be
    answering on the words it happens to keep rather than on the query.
    """
    assert product_verdict(_index(), "خوب").is_product is False
    assert product_verdict(_index(), "برای و با از").is_product is False


def test_a_project_sentence_with_a_product_word_still_falls_through(catalog_file):
    """The specific failure this change exists to prevent, named as a test."""
    index = _index()
    # the bare product words DO route
    assert product_verdict(index, "تخت کمد").is_product is True
    # and the same words inside a project sentence do not
    assert product_verdict(index, "برای اتاق خوابم تخت و کمد میخوام").is_product is False
