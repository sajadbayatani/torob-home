"""
One regression, from a runtime log.

«بازسازی سرویس بهداشتی ۱۲ متری، کیفیت متوسط» came back with the mirror answering
five unrelated requirements: plumbing, faucets, lighting, paint. The room words
were doing it.

``آینه سرویس بهداشتی`` is the only bathroom subcategory label that spells the room
out; the rest are bare — ``روشویی``, ``شیر روشویی``, ``توالت``. So ``سرویس`` and
``بهداشتی`` were vocabulary for that one subcategory at the highest weight there
is, and being rare in the file their document frequency was 1, which is exactly
what :data:`~app.catalog.selection.MAX_SHARED_FRACTION` needs in order to ignore
them. A requirement that mentions the room at all — which a requirement about a
bathroom nearly always does — therefore resolved to the mirror, and a requirement
that mentioned *only* the room resolved to the mirror and nothing else.

These tests pin the room as not being evidence. They use the enriched file, so
nothing here is a table written to make a test pass: the mirror wins or loses
because of what the shop calls things.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.catalog.selection import (
    build_room_scope,
    subcategories_for_terms,
)

ENRICHED = (
    Path(__file__).resolve().parents[3] / "data" / "catalog" / "products_70_enriched.json"
)


@pytest.fixture(scope="module")
def catalog(tmp_path_factory):
    from app.catalog.store import reset_cache, get_catalog
    from app.core.config import get_settings

    path = tmp_path_factory.mktemp("catalog-enriched") / "products.json"
    path.write_text(ENRICHED.read_text(encoding="utf-8"), encoding="utf-8")
    previous = os.environ.get("CATALOG_PATH")
    os.environ["CATALOG_PATH"] = str(path)
    get_settings.cache_clear()
    reset_cache()
    yield get_catalog()
    if previous is None:
        os.environ.pop("CATALOG_PATH", None)
    else:
        os.environ["CATALOG_PATH"] = previous
    get_settings.cache_clear()
    reset_cache()


@pytest.fixture(scope="module")
def bathroom(catalog):
    return build_room_scope(catalog, "سرویس بهداشتی")


def _slugs(catalog, scope, terms):
    return subcategories_for_terms(
        catalog, terms, scope=scope, project_type="renovation", area_m2=12
    )


class TestTheRoomIsNotEvidence:
    def test_a_requirement_that_only_names_the_room_resolves_to_nothing(self, catalog, bathroom):
        """Honest answer: we stock nothing called "a bathroom"."""
        assert _slugs(catalog, bathroom, ["سرویس بهداشتی"]) == []
        assert _slugs(catalog, bathroom, ["تهویه سرویس بهداشتی", "روشنایی"]) == []

    def test_the_room_qualified_subcategory_is_not_the_answer_to_a_room(self, catalog, bathroom):
        slugs = _slugs(catalog, bathroom, ["لوله‌کشی و لوازم بهداشتی سرویس بهداشتی"])
        assert "bathroom-mirror" not in slugs

    def test_a_product_word_still_wins_with_the_room_spelled_out(self, catalog, bathroom):
        """The fix must not throw the room away — only stop it choosing."""
        slugs = _slugs(catalog, bathroom, ["شیر", "سرویس بهداشتی"])
        assert slugs
        assert "bathroom-mirror" not in slugs
        assert set(slugs) & {"sink-faucet", "toilet-faucet"}

    def test_the_mirror_is_still_the_answer_to_a_mirror(self, catalog, bathroom):
        """Without the room words, the room-qualified label decides as it should."""
        assert "bathroom-mirror" in _slugs(catalog, bathroom, ["آینه"])

    def test_the_room_word_does_not_dilute_the_product_word(self, catalog, bathroom):
        """
        A product word is not a weaker match for appearing beside the room.

        The score divides by how much of the requirement a match accounts for, so
        counting the room words in that denominator halved every real match and
        let a rare room word outrank it.
        """
        assert _slugs(catalog, bathroom, ["شیر سرویس بهداشتی"]) == _slugs(
            catalog, bathroom, ["شیر"]
        )


class TestOtherRoomsAreUnaffected:
    def test_a_project_with_no_room_is_not_narrowed(self, catalog):
        from app.catalog.selection import RoomScope

        unscoped = RoomScope()
        # nothing said about the room, so the room words cannot be dropped
        assert _slugs(catalog, unscoped, ["سرویس بهداشتی"])
        assert "bathroom-mirror" in _slugs(catalog, unscoped, ["سرویس بهداشتی"])

    def test_a_room_the_catalogue_does_not_name_removes_no_words(self):
        """
        A room with no label contributes nothing, rather than guessed at.

        Whether such a project then matches anything is the eligibility filter's
        business — an unknown room narrows it to nothing on its own — and is not
        what this is about. What matters here is that an unlabelled room cannot
        take words out of a requirement.
        """
        from app.catalog.selection import RoomScope, _room_words

        assert _room_words(RoomScope(tokens=frozenset({"no_such_room"}))) == frozenset()
        assert _room_words(RoomScope()) == frozenset()

    def test_a_labelled_room_removes_exactly_its_own_words(self):
        from app.catalog.selection import RoomScope, _room_words

        assert _room_words(RoomScope(tokens=frozenset({"bathroom"}))) == frozenset(
            {"سرویس", "بهداشتی"}
        )
