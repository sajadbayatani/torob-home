"""Unit tests for the complementary-products pipeline.

The property under test: **the model chooses, the catalogue decides.** A model
reply can only ever become products that exist in the catalogue and were offered
to it as candidates. Anything it invents is dropped and counted, never surfaced.

The LLM is stubbed, so these tests need no key and make no network calls.
"""

from __future__ import annotations

import pytest

from app.catalog.complementary import (
    COMPLEMENTS,
    Candidate,
    build_candidate_pool,
    complementary_products,
)
from app.catalog.projections import to_complementary
from app.catalog.store import CatalogIndex, build_index, similar
from app.llm import LLMUnavailable
from tests.fixtures import CATALOG

# ids from tests/fixtures.py
KASA_FAUCET = "11111111-1111-4111-8111-111111111111"  # sink-faucet, کاسا
QAHRMAN_FAUCET = "22222222-2222-4222-8222-222222222222"  # sink-faucet, قهرمان
MORVARID_FAUCET = "66666666-6666-4666-8666-666666666666"  # sink-faucet, مروارید
GOLCHIN_TOILET = "33333333-3333-4333-8333-333333333333"  # toilet
HOOD = "44444444-4444-4444-8444-444444444444"  # kitchen-hood, alone in its category
SINK = "77777777-7777-4777-8777-777777777777"  # sink, پارس سرام
MIRROR = "88888888-8888-4888-8888-888888888888"  # bathroom-mirror, دلفین
GHOST = "deadbeef-0000-4000-8000-000000000000"  # valid uuid, no such product


@pytest.fixture
def index() -> CatalogIndex:
    return build_index(CATALOG, source=None)


@pytest.fixture
def llm(monkeypatch: pytest.MonkeyPatch):
    """Stub the OpenRouter call; returns the list of prompts it received."""

    def install(payload):
        seen: list[dict] = []

        def fake_chat_json(*, system: str, user: str, **_: object):
            seen.append({"system": system, "user": user})
            if isinstance(payload, Exception):
                raise payload
            return payload

        monkeypatch.setattr("app.catalog.complementary.chat_json", fake_chat_json)
        monkeypatch.setattr("app.catalog.complementary.is_configured", lambda: True)
        return seen

    return install


def product(index: CatalogIndex, product_id: str):
    found = index.get(product_id)
    assert found is not None, f"{product_id} missing from the fixture"
    return found


# --------------------------------------------------------------------------- #
# the candidate pool
# --------------------------------------------------------------------------- #
class TestCandidatePool:
    def test_excludes_the_product_itself(self, index: CatalogIndex) -> None:
        pool = build_candidate_pool(index, product(index, KASA_FAUCET), 24)
        assert KASA_FAUCET not in {c.id for c in pool}

    def test_excludes_same_subcategory_from_the_complement_group(
        self, index: CatalogIndex
    ) -> None:
        """Same-kind products belong in "similar", not in "complementary"."""
        pool = build_candidate_pool(index, product(index, KASA_FAUCET), 24)
        complements = [c for c in pool if c.group == "complement"]
        assert complements
        assert all(c.subcategory != "sink-faucet" for c in complements)

    def test_starts_with_the_catalogue_pairings(self, index: CatalogIndex) -> None:
        pool = build_candidate_pool(index, product(index, KASA_FAUCET), 24)
        assert [c.subcategory for c in pool[:2]] == ["sink", "bathroom-mirror"]
        assert all(c.group == "complement" for c in pool[:2])

    def test_pairings_are_ordered_by_the_rules_table(self, index: CatalogIndex) -> None:
        rules = COMPLEMENTS["sink-faucet"]
        pool = [c for c in build_candidate_pool(index, product(index, KASA_FAUCET), 24)
                if c.group == "complement"]
        seen = [c.subcategory for c in pool]
        assert seen == [sub for sub in rules if sub in seen]

    def test_is_bounded(self, index: CatalogIndex) -> None:
        faucet = product(index, KASA_FAUCET)
        assert len(build_candidate_pool(index, faucet, 2)) == 2
        assert len(build_candidate_pool(index, faucet, 1)) == 1
        # a huge width cannot exceed the catalogue itself
        assert len(build_candidate_pool(index, faucet, 10_000)) <= len(index.products)

    def test_every_candidate_is_a_real_priced_product(self, index: CatalogIndex) -> None:
        for candidate in build_candidate_pool(index, product(index, KASA_FAUCET), 24):
            assert isinstance(candidate, Candidate)
            assert index.get(candidate.id) is not None
            assert candidate.name.strip()
            assert candidate.min_price > 0
            assert candidate.subcategory_fa.strip()

    def test_a_lone_product_has_an_empty_pool(self, index: CatalogIndex) -> None:
        """The hood is the only kitchen product in the fixture, so nothing pairs."""
        assert build_candidate_pool(index, product(index, HOOD), 24) == []

    def test_toilets_pair_with_a_sink(self, index: CatalogIndex) -> None:
        pool = build_candidate_pool(index, product(index, GOLCHIN_TOILET), 24)
        assert [c.subcategory for c in pool if c.group == "complement"] == ["sink"]


# --------------------------------------------------------------------------- #
# the LLM contract
# --------------------------------------------------------------------------- #
class TestLLMSelection:
    def test_valid_ids_come_back_with_their_reason(
        self, index: CatalogIndex, llm
    ) -> None:
        seen = llm(
            {"items": [{"id": SINK, "reason": "کنار روشویی نصب می‌شود."}]}
        )
        result = complementary_products(index, product(index, KASA_FAUCET))

        assert result.available is True
        assert [str(i.product.id) for i in result.items] == [SINK]
        assert result.items[0].reason == "کنار روشویی نصب می‌شود."
        assert result.items[0].source == "llm"
        assert result.note is None
        assert len(seen) == 1

    def test_an_invented_id_is_discarded_and_counted(
        self, index: CatalogIndex, llm
    ) -> None:
        """The central guarantee: a made-up id never becomes a recommendation."""
        llm(
            {
                "items": [
                    {"id": GHOST, "reason": "به نظر می‌رسد لازم باشد."},
                    {"id": SINK, "reason": "کنار روشویی نصب می‌شود."},
                ]
            }
        )
        result = complementary_products(index, product(index, KASA_FAUCET))

        assert [str(i.product.id) for i in result.items] == [SINK]
        assert GHOST in result.discarded_ids

    def test_a_real_product_outside_the_pool_is_still_discarded(
        self, index: CatalogIndex, llm
    ) -> None:
        """Existing in the catalogue, but never offered as a candidate."""
        hood = str(product(index, HOOD).id)
        llm({"items": [{"id": hood, "reason": "مربوط نیست."}]})
        result = complementary_products(index, product(index, KASA_FAUCET))

        assert result.items == ()
        assert result.discarded_ids == (hood,)
        assert "مطمئنی" in (result.note or "")

    def test_a_same_room_candidate_may_also_be_chosen(
        self, index: CatalogIndex, llm
    ) -> None:
        """The pool offers real pairings first and the rest of the room after.

        A same-subcategory product is in the pool for that reason, so the model
        is allowed to pick it; it is still validated against the catalogue.
        """
        llm({"items": [{"id": QAHRMAN_FAUCET, "reason": "با هم ست می‌شوند."}]})
        result = complementary_products(index, product(index, KASA_FAUCET))

        assert [str(i.product.id) for i in result.items] == [QAHRMAN_FAUCET]
        assert result.items[0].source == "llm"
        assert index.get(QAHRMAN_FAUCET) is not None

    def test_duplicate_ids_are_returned_once(self, index: CatalogIndex, llm) -> None:
        llm(
            {
                "items": [
                    {"id": SINK, "reason": "اول"},
                    {"id": SINK, "reason": "دوم"},
                ]
            }
        )
        result = complementary_products(index, product(index, KASA_FAUCET))
        assert len(result.items) == 1
        assert result.items[0].reason == "اول"

    def test_uppercase_ids_are_accepted(self, index: CatalogIndex, llm) -> None:
        llm({"items": [{"id": SINK.upper(), "reason": "کنار روشویی."}]})
        result = complementary_products(index, product(index, KASA_FAUCET))
        assert [str(i.product.id) for i in result.items] == [SINK]
        assert result.discarded_ids == ()

    def test_an_item_without_a_reason_is_discarded(
        self, index: CatalogIndex, llm
    ) -> None:
        """No reason means no claim we can make, so it is not recommended."""
        for reason in (None, "", "   "):
            llm({"items": [{"id": SINK, "reason": reason}]})
            result = complementary_products(index, product(index, KASA_FAUCET))
            assert result.items == ()
            assert SINK in result.discarded_ids

    def test_a_long_reason_is_truncated(self, index: CatalogIndex, llm) -> None:
        llm({"items": [{"id": SINK, "reason": "ا" * 400}]})
        result = complementary_products(index, product(index, KASA_FAUCET))
        assert len(result.items[0].reason) <= 160

    def test_a_malformed_reply_yields_nothing(self, index: CatalogIndex, llm) -> None:
        for payload in ({"items": "not a list"}, {"items": {"id": SINK}}, {}, []):
            llm(payload)
            result = complementary_products(index, product(index, KASA_FAUCET))
            assert result.items == ()

    def test_junk_entries_are_skipped_without_losing_good_ones(
        self, index: CatalogIndex, llm
    ) -> None:
        llm(
            {
                "items": [
                    "not an object",
                    {"nope": 1},
                    {"id": "", "reason": "بدون شناسه"},
                    {"id": 12, "reason": "شناسه عددی"},
                    {"id": SINK, "reason": "کنار روشویی."},
                ]
            }
        )
        result = complementary_products(index, product(index, KASA_FAUCET))
        assert [str(i.product.id) for i in result.items] == [SINK]

    def test_the_reply_is_capped(self, index: CatalogIndex, llm) -> None:
        pool = build_candidate_pool(index, product(index, KASA_FAUCET), 24)
        llm({"items": [{"id": c.id, "reason": "مکمل"} for c in pool]})
        result = complementary_products(index, product(index, KASA_FAUCET))

        from app.core.config import get_settings

        assert len(result.items) <= get_settings().complementary_max_results

    def test_the_model_only_sees_bounded_candidates(
        self, index: CatalogIndex, llm
    ) -> None:
        """The catalogue at large must never be sent."""
        seen = llm({"items": []})
        faucet = product(index, KASA_FAUCET)
        complementary_products(index, faucet)

        prompt = seen[0]["user"]
        pool = build_candidate_pool(index, faucet, 24)
        for candidate in pool:
            assert candidate.name in prompt
        # the subject product is listed once, then each candidate once
        assert prompt.count("- id:") == len(pool) + 1
        assert f"نامزدها ({len(pool)} مورد)" in prompt

    def test_the_prompt_names_the_product_and_forbids_invention(
        self, index: CatalogIndex, llm
    ) -> None:
        seen = llm({"items": []})
        faucet = product(index, KASA_FAUCET)
        complementary_products(index, faucet)

        system, user = seen[0]["system"], seen[0]["user"]
        assert faucet.name in user and faucet.subcategory_name in user
        assert "id" in system
        assert "هرگز محصولی خارج از این فهرست نساز" in system
        assert "کمتر بهتر است" in system

    def test_a_failed_call_falls_back_to_catalogue_pairings(
        self, index: CatalogIndex, llm
    ) -> None:
        llm(LLMUnavailable("network down"))
        result = complementary_products(index, product(index, KASA_FAUCET))

        assert result.available is False
        assert result.note
        assert result.items, "the catalogue pairings remain available"
        assert all(i.source == "heuristic" for i in result.items)
        for item in result.items:
            assert index.get(str(item.product.id)) is not None


class TestNoLLMConfigured:
    def test_uses_catalogue_pairings_and_says_so(
        self, index: CatalogIndex, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("app.catalog.complementary.is_configured", lambda: False)
        result = complementary_products(index, product(index, KASA_FAUCET))

        assert result.available is False
        assert "OpenRouter" in (result.note or "")
        assert result.items
        assert all(i.source == "heuristic" for i in result.items)

    def test_never_offers_something_outside_the_pool(
        self, index: CatalogIndex, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("app.catalog.complementary.is_configured", lambda: False)
        faucet = product(index, KASA_FAUCET)
        pool = {c.id for c in build_candidate_pool(index, faucet, 24)}
        result = complementary_products(index, faucet)
        assert {str(i.product.id) for i in result.items} <= pool

    def test_a_lone_product_returns_nothing(
        self, index: CatalogIndex, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("app.catalog.complementary.is_configured", lambda: False)
        result = complementary_products(index, product(index, HOOD))
        assert result.items == ()
        assert result.candidate_count == 0
        assert "مکملی" in (result.note or "")


# --------------------------------------------------------------------------- #
# the API response
# --------------------------------------------------------------------------- #
class TestComplementaryResponse:
    def test_carries_only_validated_ids(self, index: CatalogIndex, llm) -> None:
        llm(
            {
                "items": [
                    {"id": SINK, "reason": "با روشویی نصب می‌شود."},
                    {"id": GHOST, "reason": "ساختگی"},
                ]
            }
        )
        response = to_complementary(
            complementary_products(index, product(index, KASA_FAUCET))
        )

        assert [str(i.product_id) for i in response.items] == [SINK]
        assert list(response.discarded_ids) == [GHOST]
        for item in response.items:
            assert item.product_id == item.product.id
            assert index.get(str(item.product_id)) is not None
            assert item.product.name.strip()
            assert item.product.min_price > 0

    def test_reports_how_many_candidates_were_offered(
        self, index: CatalogIndex, llm
    ) -> None:
        llm({"items": []})
        faucet = product(index, KASA_FAUCET)
        response = to_complementary(complementary_products(index, faucet))
        assert response.candidate_count == len(build_candidate_pool(index, faucet, 24))
        assert response.llm_available is True

    def test_the_note_reaches_the_client(
        self, index: CatalogIndex, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("app.catalog.complementary.is_configured", lambda: False)
        response = to_complementary(
            complementary_products(index, product(index, KASA_FAUCET))
        )
        assert response.note
        assert response.llm_available is False


# --------------------------------------------------------------------------- #
# similar products: deterministic, catalogue-only
# --------------------------------------------------------------------------- #
class TestSimilar:
    def test_same_subcategory_ranks_first(self, index: CatalogIndex) -> None:
        results = similar(index, product(index, KASA_FAUCET), limit=6)
        assert results
        assert all(m.product.subcategory == "sink-faucet" for m in results[:2])
        assert results[0].score == 300

    def test_scores_never_increase(self, index: CatalogIndex) -> None:
        """A visible ordering rule beats a sort the user has to trust."""
        scores = [m.score for m in similar(index, product(index, GOLCHIN_TOILET), 6)]
        assert scores == sorted(scores, reverse=True)

    def test_never_returns_the_product_itself(self, index: CatalogIndex) -> None:
        for match in similar(index, product(index, KASA_FAUCET), limit=10):
            assert match.product.id != KASA_FAUCET

    def test_is_deterministic(self, index: CatalogIndex) -> None:
        first = [m.product.id for m in similar(index, product(index, KASA_FAUCET), 6)]
        second = [m.product.id for m in similar(index, product(index, KASA_FAUCET), 6)]
        assert first == second

    def test_every_result_is_a_real_catalogue_product(
        self, index: CatalogIndex
    ) -> None:
        for match in similar(index, product(index, KASA_FAUCET), limit=10):
            assert index.get(match.product.id) is not None
            assert match.product.min_price > 0

    def test_every_result_explains_itself(self, index: CatalogIndex) -> None:
        for match in similar(index, product(index, KASA_FAUCET), limit=6):
            assert match.reasons and all(r.strip() for r in match.reasons)

    def test_a_lone_product_has_no_similar(self, index: CatalogIndex) -> None:
        assert similar(index, product(index, HOOD), limit=6) == []

    def test_a_unique_subcategory_falls_back_to_the_category(
        self, index: CatalogIndex
    ) -> None:
        """The only sink, so the list comes from the wider category instead."""
        results = similar(index, product(index, SINK), limit=6)
        assert results
        assert all(m.product.id != SINK for m in results)
        assert all(m.score == 100 for m in results)

    def test_never_returns_more_than_the_limit(self, index: CatalogIndex) -> None:
        assert len(similar(index, product(index, GOLCHIN_TOILET), limit=2)) == 2
