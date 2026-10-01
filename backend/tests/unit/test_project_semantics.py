"""
Project requirements are planning, not transcription.

The field this file is about came back empty for years of prompt wording, because
the prompt asked a model to justify every item against "did the user say this?" and
a bedroom redesign names nothing. These tests pin the *properties* a project
search must have, using mocked model replies — no model is called, and no expected
requirement list is written down anywhere, because writing one down is the bug.

The strongest assertion here is `test_two_goals_in_one_room_differ`: a hardcoded
room→requirements table would answer both questions with the same list. A model
that reads the goal would not.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.domains.search.llm_interpreter import LLMInterpreter
from app.domains.search.llm_schema import LLMIntentResponse
from app.domains.search.taxonomy import build_taxonomy

ENRICHED_CATALOG = (
    Path(__file__).resolve().parents[3] / "data" / "catalog" / "products_70_enriched.json"
)

#: Umbrella words name no thing, so a requirement may not be built from one. This
#: is a property of the vocabulary, not a list of expected answers.
UMBRELLA = {
    "تجهیزات", "لوازم", "وسایل", "دکوراسیون", "فضای", "لوازم مورد نیاز",
    "تجهیزات لازم", "وسایل لازم", "لوازم لازم برای", "تجهیزات اتاق",
    "تجهیزات لازم برای ایجاد فضای گیمینگ",
}


@pytest.fixture(scope="module")
def catalog_file(tmp_path_factory):
    """The enriched catalogue, so availability questions have a real answer."""
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


def _requirement(description: str, *terms: str, quantity=None, required=True, quality=None):
    return {
        "description": description,
        "terms": list(terms),
        "quantity": quantity,
        "required": required,
        "quality_min": quality,
    }


def _interpret(query: str, *, project: dict, category: str | None = None,
               quality: str | None = None, budget: int | None = None):
    """Resolve a query from a scripted model answer. No inference happens.

    `quality` and `budget` are model-sourced too, so they are scripted rather than
    assumed: a test that only fills in `project` would silently exercise the
    all-null path.
    """
    payload = {
        "intent": "project_search",
        "category": category,
        "project": project,
        "search": None,
        "constraints": {"quality": quality, "budget": budget, "notes": []},
        "constraint_kind": "NONE",
        "confidence": 0.9,
        "explanations": [],
    }
    return LLMInterpreter().resolve(
        query, LLMIntentResponse.model_validate(payload), build_taxonomy()
    )


# --------------------------------------------------------------------------- #
# A broad but valid project yields usable requirements
# --------------------------------------------------------------------------- #
def _assert_usable_requirements(requirements) -> None:
    """The properties every project requirement must have, whatever the project."""
    assert requirements, "a project described in one sentence has requirements"
    for requirement in requirements:
        assert requirement.terms, f"{requirement.description!r} has no search terms"
        # a short concrete noun, not a clause lifted from the sentence
        for term in requirement.terms:
            assert term.strip(), "an empty term matches nothing"
            assert term not in UMBRELLA, f"{term!r} is an umbrella word, not a thing"
            assert len(term) <= 40, f"{term!r} is a phrase, not a catalogue noun"
        # and the description is short and human-readable
        assert 0 < len(requirement.description) <= 200


def test_a_broad_bedroom_redesign_produces_usable_requirements(catalog_file):
    """The reported failure: a redesign, no products named, and the answer was [].

    Nothing here says *which* items a bedroom needs — that is the model's job and
    is deliberately not written down. What is pinned is that the decomposition is
    non-empty, that its terms are things rather than umbrellas, and that the
    user's stated facts survive.
    """
    intent = _interpret(
        "اتاق خواب ۱۵متری‌ام رو می‌خوام تغییر دکوراسیون بدم",
        project={
            "type": "redesign",
            "room": "اتاق خواب",
            "room_token": "bedroom",
            "area_m2": 15.0,
            "goal": "تغییر دکوراسیون اتاق خواب",
            "requirements": [
                _requirement("تخت خواب", "تخت"),
                _requirement("کمد لباس", "کمد"),
                _requirement("روشنایی اتاق", "چراغ", required=False),
            ],
        },
        category="furniture",
    )
    assert intent.intent.value == "NEED_SEARCH"
    _assert_usable_requirements(intent.project_requirements)
    # the facts the user stated are preserved untouched
    assert intent.room == "اتاق خواب"
    assert intent.room_token == "bedroom"
    assert intent.requirements.area_m2 == 15.0
    assert intent.project_type.value == "redesign"
    # and nothing they did not state was invented
    assert intent.requirements.style is None
    assert intent.requirements.budget is None
    assert intent.requirements.quality is None


def test_a_broad_bathroom_renovation_produces_usable_requirements(catalog_file):
    intent = _interpret(
        "بازسازی سرویس بهداشتی ۱۲ متری، کیفیت متوسط",
        project={
            "type": "renovation",
            "room": "سرویس بهداشتی",
            "room_token": "bathroom",
            "area_m2": 12.0,
            "goal": "بازسازی سرویس بهداشتی",
            "requirements": [
                _requirement("توالت", "توالت"),
                _requirement("روشویی و کابینت", "سینک"),
                _requirement("شیر", "شیر"),
            ],
        },
        category="bathroom",
        quality="medium",
    )
    assert intent.intent.value == "NEED_SEARCH"
    _assert_usable_requirements(intent.project_requirements)
    assert intent.requirements.area_m2 == 12.0
    # "کیفیت متوسط" was stated, so it must survive
    assert intent.requirements.quality == "medium"
    assert intent.requirements.budget is None, "no budget was stated"


def test_an_explicit_quantity_survives_and_none_is_not_invented(catalog_file):
    stated = _interpret(
        "برای اتاقم دو تا صندلی میخوام",
        project={
            "type": "renovation", "room": "اتاق", "room_token": None, "area_m2": None,
            "goal": "تجهیز اتاق",
            "requirements": [_requirement("صندلی", "صندلی", quantity=2)],
        },
    )
    assert stated.project_requirements[0].quantity == 2

    not_stated = _interpret(
        "میخوام حموم رو نوسازی کنم",
        project={
            "type": "renovation", "room": "حموم", "room_token": "bathroom",
            "area_m2": None, "goal": "نوسازی حموم",
            "requirements": [_requirement("توالت", "توالت")],
        },
    )
    assert not_stated.project_requirements[0].quantity is None, (
        "a quantity the user never gave is not invented"
    )


# --------------------------------------------------------------------------- #
# The two properties a fixed list would break
# --------------------------------------------------------------------------- #
def test_two_goals_in_one_room_differ(catalog_file):
    """
    A room→requirements table cannot pass this.

    It answers from the room name alone, so both bedrooms would return the same
    list however differently the jobs were described. Nothing here names the right
    answers — only that the room is not the variable that decides.
    """
    redesign = _interpret(
        "اتاق خوابم رو می‌خوام تغییر دکوراسیون بدم",
        project={
            "type": "redesign", "room": "اتاق خواب", "room_token": "bedroom",
            "area_m2": None, "goal": "تغییر دکوراسیون اتاق خواب",
            "requirements": [
                _requirement("تخت خواب", "تخت"),
                _requirement("کمد لباس", "کمد"),
            ],
        },
    )
    study = _interpret(
        "توی اتاق خوابم یه گوشه برای درس‌خواندن می‌خوام",
        project={
            "type": "redesign", "room": "اتاق خواب", "room_token": "bedroom",
            "area_m2": None, "goal": "ایجاد گوشهٔ مطالعه در اتاق خواب",
            "requirements": [
                _requirement("میز تحریر", "میز"),
                _requirement("صندلی", "صندلی"),
                _requirement("چراغ مطالعه", "چراغ", required=False),
            ],
        },
    )
    redesign_terms = {t for r in redesign.project_requirements for t in r.terms}
    study_terms = {t for r in study.project_requirements for t in r.terms}
    assert redesign_terms != study_terms, (
        "the same room answered the same way for two different jobs — "
        "that is a room checklist, not an understanding"
    )


def test_requirements_are_not_limited_to_what_the_catalogue_stocks(catalog_file):
    """
    A legitimate need the file cannot serve is still a need.

    The catalogue decides availability later; if it decided the requirement set,
    the project's meaning would depend on what happened to be in stock today.
    """
    intent = _interpret(
        "میخوام یه گلخونه کوچک توی بالکن درست کنم",
        project={
            "type": "renovation", "room": "بالکن", "room_token": None, "area_m2": None,
            "goal": "ساخت گلخانه کوچک در بالکن",
            "requirements": [
                _requirement("گلدان", "گلدان"),
                _requirement("خاک گلدانی", "خاک"),
            ],
        },
    )
    requirements = intent.project_requirements
    _assert_usable_requirements(requirements)

    from app.catalog.selection import RoomScope, subcategories_for_terms
    from app.catalog.store import get_catalog

    index = get_catalog()
    unresolvable = [
        r for r in requirements if not subcategories_for_terms(index, r.terms, scope=RoomScope())
    ]
    assert unresolvable, (
        "this fixture deliberately names needs the catalogue does not stock; "
        "if they all resolve, the test is no longer proving the point"
    )


def test_the_schema_rejects_a_requirement_that_is_a_product(catalog_file):
    """The boundary that lets decomposition stay planning."""
    from pydantic import ValidationError

    from app.domains.search.schemas import SemanticRequirement

    SemanticRequirement(description="تخت خواب", terms=["تخت"])  # fine
    for product_shaped in (
        {"description": "تخت", "terms": ["تخت"], "brand": "ایکس ویژن"},
        {"description": "تخت", "terms": ["تخت"], "model": "X1"},
        {"description": "تخت", "terms": ["تخت"], "price": 1_000_000},
        {"description": "تخت", "terms": ["تخت"], "slug": "bed"},
        {"description": "تخت", "terms": ["تخت"], "seller": "فروشگاه"},
    ):
        with pytest.raises(ValidationError):
            SemanticRequirement.model_validate(product_shaped)
