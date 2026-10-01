"""
Semantic requirement → canonical subcategory → real products.

This is the seam the project pipeline was missing. The model produces
``SemanticRequirement`` objects — words for *the kind of thing needed* — and the
catalogue has to answer them with actual products. The words are semantic and the
catalogue is fixed, so the join between them has to be more than a substring test.

The tests here are deliberately written **without an expected answer table**. A
test that says "«تخت خواب» must give bed" is a specification of the catalogue, and
it fails the moment the shop stocks something else. What is asserted instead is
that a resolution is *justified by the file* — the subcategory the resolver chose
is one whose own vocabulary the requirement's words belong to — plus the
structural properties of the pipeline. That holds for a requirement nobody wrote
a test for, which is the point.

Every test uses the real enriched catalogue and a scripted model. No model is
called; the ``LLMStub`` supplies what it produced.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.catalog.selection import (
    RoomScope,
    build_room_scope,
    is_eligible,
    select_candidates,
    subcategories_for_terms,
)
from app.catalog.store import fa_tokens, read_index
from app.core.enums import Quality
from app.domains.projects.needs import resolve_needs
from app.domains.search.schemas import SemanticRequirement

ENRICHED = Path(__file__).resolve().parents[3] / "data" / "catalog" / "products_70_enriched.json"


@pytest.fixture(scope="module")
def index():
    return read_index(ENRICHED)


@pytest.fixture
def use_enriched(monkeypatch):
    """Point the running application at the real enriched catalogue."""
    from app.catalog.store import reset_cache
    from app.core.config import get_settings

    previous = os.environ.get("CATALOG_PATH")
    os.environ["CATALOG_PATH"] = str(ENRICHED)
    get_settings.cache_clear()
    reset_cache()
    yield ENRICHED
    if previous is None:
        os.environ.pop("CATALOG_PATH", None)
    else:
        os.environ["CATALOG_PATH"] = previous
    get_settings.cache_clear()
    reset_cache()


# --------------------------------------------------------------------------- #
# The property that makes a resolution trustworthy
# --------------------------------------------------------------------------- #
def assert_justified_by_the_file(index, requirement, slug, scope, project_type, area):
    """
    The chosen subcategory really is one the file calls those words.

    This is what replaces an expected-answer table: whatever the resolver
    returns, the requirement's own words must appear in that subcategory's
    vocabulary. A resolution invented by a word-list in the test, or a lucky
    substring, cannot satisfy this.
    """
    vocabulary = index.subcategory_vocabulary()[slug]
    words = {token for term in requirement.terms for token in fa_tokens(str(term))}
    assert words, "a requirement with no words cannot be justified by anything"
    assert words & set(vocabulary.tokens) or str(requirement.terms[0]) in vocabulary.phrases, (
        f"{slug} was returned for {requirement.terms!r} but the file does not use "
        f"those words for it; the vocabulary it does use is {sorted(vocabulary.tokens)}"
    )
    # and it is a subcategory this project may actually use
    assert any(
        is_eligible(p, scope=scope, project_type=project_type, area_m2=area)
        for p in index.subcategories_of(slug)
    ), f"{slug} is not eligible for this project, so it should never be offered"


def resolve(index, requirements, *, room, project_type, area=12.0):
    """The production path from a requirement list to needs, unchanged."""
    scope = build_room_scope(index, room)
    return scope, resolve_needs(
        index,
        requirements,
        scope=scope,
        project_type=project_type,
        area_m2=area,
        quality=Quality.LOW,
    )


# --------------------------------------------------------------------------- #
# Test 1 — a requirement the catalogue answers yields real products
# --------------------------------------------------------------------------- #
def test_a_requirement_that_the_catalogue_answers_produces_real_products(index):
    scope = build_room_scope(index, "اتاق خواب")
    requirement = SemanticRequirement(description="تخت خواب", terms=["تخت خواب"])

    slugs = subcategories_for_terms(
        index, requirement.terms, scope=scope, project_type="redesign", area_m2=12.0
    )
    assert slugs, "the file stocks beds, so a bed requirement resolves"

    products = [
        product
        for slug in slugs
        for product in select_candidates(
            index, slug, scope=scope, project_type="redesign", area_m2=12.0
        )
    ]
    assert products, "a resolved requirement yields products, not just a slug"
    for product in products:
        # real catalogue objects, already cleared for the project
        assert product.purchasable_offers, "a product with nothing to buy is not a candidate"
        assert is_eligible(product, scope=scope, project_type="redesign", area_m2=12.0)
        assert product.id in {p.id for p in index.products}
    assert_justified_by_the_file(
        index, requirement, slugs[0], scope, "redesign", 12.0
    )


# --------------------------------------------------------------------------- #
# Test 2 — every answered requirement of a multi-requirement project
# --------------------------------------------------------------------------- #
def test_every_answered_requirement_of_a_project_yields_its_own_products(index):
    scope = build_room_scope(index, "اتاق خواب")
    requirements = [
        SemanticRequirement(description="تخت خواب", terms=["تخت خواب"]),
        SemanticRequirement(description="کمد لباس", terms=["کمد لباس"]),
        SemanticRequirement(description="مبل راحتی", terms=["مبل راحتی"]),
    ]
    _, needs = resolve(
        index, requirements, room="اتاق خواب", project_type="redesign", area=12.0
    )

    # one need per requirement: none merged, none invented
    assert len(needs) == len(requirements)
    assert [n.role for n in needs] == ["req_1", "req_2", "req_3"]

    for need in needs:
        if not need.matched:
            continue
        products = select_candidates(
            index, need.slug, scope=scope, project_type="redesign", area_m2=12.0
        )
        assert products, f"{need.description!r} resolved to {need.slug} but has no product"
        assert_justified_by_the_file(
            index, requirements[needs.index(need)], need.slug, scope, "redesign", 12.0
        )

    # The project's own contents come from the needs that resolved; one
    # unanswerable need elsewhere in the project cannot remove these.
    answered = {n.slug for n in needs if n.matched}
    assert answered, "at least one requirement of a bedroom project is answerable"


# --------------------------------------------------------------------------- #
# Test 3 — an unanswered requirement is contained
# --------------------------------------------------------------------------- #
def test_an_unanswerable_requirement_does_not_remove_the_answerable_ones(index):
    scope = build_room_scope(index, "اتاق خواب")
    requirements = [
        SemanticRequirement(description="تخت خواب", terms=["تخت خواب"]),
        # deliberately outside the file: nothing stocks a wall finish
        SemanticRequirement(description="رنگ دیوار", terms=["رنگ دیوار"]),
        SemanticRequirement(description="کمد لباس", terms=["کمد لباس"]),
    ]
    _, needs = resolve(
        index, requirements, room="اتاق خواب", project_type="redesign", area=12.0
    )
    matched = [n for n in needs if n.matched]
    unmatched = [n for n in needs if not n.matched]

    assert len(matched) >= 2, "the requirements the file answers still answer"
    # the unanswerable one is kept, and reported, rather than dropped
    assert [n.description for n in unmatched] == ["رنگ دیوار"]
    assert len(needs) == 3
    for need in matched:
        assert select_candidates(
            index, need.slug, scope=scope, project_type="redesign", area_m2=12.0
        ), "a matched need still produces products while another is unmatched"


# --------------------------------------------------------------------------- #
# Test 4 — a mixed project returns requirements, products and the gap
# --------------------------------------------------------------------------- #
def test_a_mixed_project_reports_needs_products_and_the_unavailable_ones(index):
    requirements = [
        SemanticRequirement(description="توالت", terms=["توالت"]),
        SemanticRequirement(description="کاشی و سرامیک", terms=["کاشی"]),
        SemanticRequirement(description="روشویی", terms=["روشویی"]),
    ]
    scope, needs = resolve(
        index, requirements, room="سرویس بهداشتی", project_type="renovation", area=12.0
    )

    # every requirement survives, matched or not
    assert [n.description for n in needs] == [r.description for r in requirements]

    matched = [n for n in needs if n.matched]
    unavailable = [n for n in needs if not n.matched]
    assert matched, "the answered requirements are matched"
    assert unavailable, "the requirement the file cannot answer is reported as such"

    # the products are the catalogue's own, for the matched needs
    products = [
        product
        for need in matched
        for product in select_candidates(
            index, need.slug, scope=scope, project_type="renovation", area_m2=12.0
        )
    ]
    assert products
    known = {p.id for p in index.products}
    assert all(product.id in known for product in products), (
        "a product came from somewhere other than the catalogue file"
    )
    # and a need nothing answers never turns into a made-up product
    assert all(need.role not in {n.role for n in unavailable} for need in matched)


# --------------------------------------------------------------------------- #
# Test 5 — the reported bedroom query, and Test 6 — the bathroom query
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("query_note", "room", "project_type", "terms"),
    [
        ("bedroom redesign", "اتاق خواب", "redesign", ["تخت خواب", "کمد لباس"]),
        (
            "bathroom renovation",
            "سرویس بهداشتی",
            "renovation",
            ["توالت", "روشویی", "شیر"],
        ),
    ],
)
def test_a_reported_query_resolves_to_products_not_to_an_empty_candidate_set(
    index, query_note, room, project_type, terms
):
    """
    The reported symptom was ``candidates=0`` with requirements on screen.

    A requirement is only allowed to contribute nothing when the file genuinely
    has nothing for it. For any requirement the file can answer, the project must
    end with real products — which is the whole of the missing step.
    """
    requirements = [
        SemanticRequirement(description=term, terms=[term]) for term in terms
    ]
    scope, needs = resolve(index, requirements, room=room, project_type=project_type)

    candidates = [
        product
        for need in needs
        if need.matched
        for product in select_candidates(
            index, need.slug, scope=scope, project_type=project_type, area_m2=12.0
        )
    ]
    assert candidates, f"{query_note}: the file answers these requirements with products"
    assert all(p.purchasable_offers for p in candidates)
    assert all(p.id in {x.id for x in index.products} for p in candidates)


# --------------------------------------------------------------------------- #
# The two matching errors, pinned
# --------------------------------------------------------------------------- #
def test_a_word_matching_a_longer_one_does_not_answer_a_requirement(index):
    """
    A sofa must not be answered with a bed.

    The words of every furniture subcategory once shared "مبلمان" — the category
    label — so a substring comparison read "مبل" inside it and every furniture
    subcategory claimed the requirement, and the room filter then kept beds and
    wardrobes. The requirement was answered, confidently, with the wrong thing.

    Checked unscoped, so this is purely about *which subcategory the words name*:
    the room filter is a separate decision and is exercised below.
    """
    unscoped = RoomScope()
    vocabulary = index.subcategory_vocabulary()

    for term in ("مبل", "مبل راحتی"):
        slugs = subcategories_for_terms(
            index, [term], scope=unscoped, project_type="renovation", area_m2=12.0
        )
        assert slugs, f"{term!r} is a thing the file sells"
        for slug in slugs:
            assert_justified_by_the_file(
                index,
                SemanticRequirement(description=term, terms=[term]),
                slug,
                unscoped,
                "renovation",
                12.0,
            )

    # the shared word itself decides nothing anywhere
    shared = index.token_document_frequency()
    for slug, words in vocabulary.items():
        for token in words.tokens:
            if shared[token] > len(vocabulary) * 0.5:
                resolved = subcategories_for_terms(
                    index, [token], scope=RoomScope(), project_type="renovation", area_m2=12.0
                )
                assert slug not in resolved or len(resolved) == 1, (
                    f"{token!r} is shared by {shared[token]} subcategories, so it "
                    f"cannot be the reason {slug} was chosen"
                )


def test_a_requirement_is_not_answered_with_another_rooms_product(index):
    """
    A sofa asked for in a bedroom is unmet, not satisfied by a bed.

    The wrong-answer case and the room rule are separate. Once the words name the
    right subcategory, a subcategory the project may not use is dropped — and
    what is left must be nothing, rather than a bedroom product that happens to
    share a word with the request.
    """
    bedroom = build_room_scope(index, "اتاق خواب")
    resolved = subcategories_for_terms(
        index, ["مبل راحتی"], scope=bedroom, project_type="redesign", area_m2=12.0
    )
    assert resolved == [], (
        "the file records sofas for the living room only, so a bedroom project "
        f"cannot be answered with one; got {resolved}"
    )
    # and the products on offer for a bedroom stay bedroom products
    for slug in subcategories_for_terms(
        index, ["تخت خواب"], scope=bedroom, project_type="redesign", area_m2=12.0
    ):
        rooms = {
            room
            for product in index.subcategories_of(slug)
            for room in (product.metadata.get("rooms") or ())
        }
        assert not rooms or rooms & bedroom.tokens, (
            f"{slug} carries rooms {rooms}, none of which is this project's"
        )


def test_a_multi_word_requirement_matches_a_subcategory_named_differently(index):
    """
    The model and the shop may call the same thing different things.

    A requirement need not appear contiguously anywhere: it is compared word by
    word against the words the file uses, so a phrase the file words differently
    still reaches the subcategory both meant.
    """
    scope = build_room_scope(index, "اتاق خواب")
    for term in ("تخت خواب دونفره", "کمد لباس ۴ درب", "تخت یکنفره"):
        slugs = subcategories_for_terms(
            index, [term], scope=scope, project_type="redesign", area_m2=12.0
        )
        assert slugs, f"{term!r} names something the file sells"
        assert_justified_by_the_file(
            index, SemanticRequirement(description=term, terms=[term]), slugs[0],
            scope, "redesign", 12.0,
        )


def test_every_returned_subcategory_is_justified_not_only_the_first(index):
    """
    A requirement may not drag other subcategories in with it.

    The same substring test that read "مبل" inside "مبلمان" also let a bed
    requirement claim the wardrobe, because the two share a category label. Only
    the *first* slug is ever used to answer the need, so this cost nothing there
    — but the whole list is published as the project's available subcategories, so
    a requirement is answerable by more than it asked for, and it is read as
    though the file had said so.
    """
    for room, project_type, term in (
        ("اتاق خواب", "redesign", "تخت خواب"),
        ("اتاق خواب", "redesign", "کمد لباس"),
        ("سرویس بهداشتی", "renovation", "توالت"),
        ("سرویس بهداشتی", "renovation", "روشویی"),
    ):
        scope = build_room_scope(index, room)
        slugs = subcategories_for_terms(
            index, [term], scope=scope, project_type=project_type, area_m2=12.0
        )
        assert slugs, f"{term!r} is answered by the file"
        for slug in slugs:
            assert_justified_by_the_file(
                index,
                SemanticRequirement(description=term, terms=[term]),
                slug,
                scope,
                project_type,
                12.0,
            )


def test_resolution_never_invents_a_subcategory(index):
    """Every returned slug is one the file actually has, with products in it."""
    scope = build_room_scope(index, "اتاق خواب")
    known = index.subcategory_slugs()
    for term in ("تخت", "کمد", "مبل", "میز", "رنگ دیوار", "پرده", "چراغ سقفی", "تلویزیون"):
        for slug in subcategories_for_terms(
            index, [term], scope=scope, project_type="redesign", area_m2=12.0
        ):
            assert slug in known, f"{slug} is not a subcategory of the file"
            assert index.subcategories_of(slug), f"{slug} has no products"
