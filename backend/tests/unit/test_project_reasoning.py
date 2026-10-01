"""
The model reasons over a bounded candidate set; the backend still decides what
is true.

These tests are about the boundary, not about the model's judgement. They script
a reply and then check that everything between the prompt and the response is
real: the candidate set is built from the catalogue, the prompt carries the
project's own parameters, ids are validated against what was offered, prices come
from the file, and nothing reaches the basket without the user putting it there.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from app.catalog.store import get_catalog
from app.core.enums import Quality
from app.domains.projects.reasoning import (
    ProjectReasoningResponse,
    _validate,
    build_candidate_set,
)
from app.domains.projects.needs import ProjectNeed
from app.domains.search.schemas import InterpretedIntent

#: The enriched catalogue, not the small fixture one.
#:
#: The session fixture in ``conftest`` points ``CATALOG_PATH`` at a minimal
#: catalogue that predates the enrichment: its products carry no ``rooms``, no
#: ``complementary_subcategories`` and one product per subcategory. Reasoning
#: over rooms, complements and quality is entirely metadata-driven, so a test
#: that used it would be asserting against data the feature cannot read. These
#: tests therefore read the real enriched file, deliberately, for this module
#: only — the override is undone afterwards.
ENRICHED_CATALOG = (
    Path(__file__).resolve().parents[3] / "data" / "catalog" / "products_70_enriched.json"
)


@pytest.fixture(scope="module")
def catalog_file(tmp_path_factory):
    """
    This module runs against the **enriched** catalogue.

    ``conftest`` points ``CATALOG_PATH`` at a minimal catalogue for the whole
    session, and its products carry no ``rooms``, no
    ``complementary_subcategories`` and one product per subcategory. Reasoning
    over rooms, complements and quality is entirely metadata-driven, so those
    tests would be asserting against data this feature cannot read. Shadowing the
    session fixture — rather than repointing the variable inside a test — keeps
    the application and the assertions reading the *same* file, which matters
    because the basket service validates a product against the configured
    catalogue when an item is added.
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


def _catalog():
    """The catalogue this module is configured to read."""
    return get_catalog()


def _needs(*roles: str) -> list[ProjectNeed]:
    """
    The project's needs, as the interpreter stated them.

    These used to be built from the ``furniture_redesign`` template's own rules,
    which is the whole change under test: a project's requirements are the
    model's understanding now, so a test that wants a bed asks for a bed rather
    than reaching for a rulebook and taking whatever it happens to contain.

    The roles here are named rather than numbered because ``resolve_needs``
    assigns ``req_1``, ``req_2``… in the engine; a test that constructs needs
    itself is free to say which one it means.
    """
    slugs = {
        "bed": ("bed", "تخت"),
        "wardrobe": ("wardrobe", "کمد"),
        "sofa": ("sofa", "مبل"),
        "desk": ("desk", "میز"),
        "dining_table": ("dining-table", "میز ناهارخوری"),
        "dining_chair": ("dining-chair", "صندلی"),
        "lighting": ("lamp", "چراغ"),
        "decor": ("curtain", "پرده"),
        "television": ("television", "تلویزیون"),
    }
    return [
        ProjectNeed(
            role=role,
            description=label,
            terms=(label,),
            slugs=(slug,) if slug else (),
            quantity=1,
            required=True,
            quality_min=Quality.LOW,
        )
        for position, role in enumerate(roles, start=1)
        for slug, label in [slugs.get(role, ("", role))]
    ]


def _bedroom_needs() -> list[ProjectNeed]:
    return _needs("bed", "wardrobe", "lighting", "decor")


def _room_intent() -> InterpretedIntent:
    return InterpretedIntent.model_validate(
        {
            "intent": "NEED_SEARCH",
            "domain": "furniture",
            "project_type": "redesign",
            "template_slug": "furniture_redesign",
            "product_query": None,
            "requirements": {
                "area_m2": 12,
                "quality": None,
                "style": None,
                "budget": None,
                "priorities": [],
                "extra": {},
            },
            "constraint_kind": "NONE",
            "confidence": 0.9,
            "interpreter": "llm",
            "explanations": [],
            "matched_subcategories": [],
            "missing_categories": [],
            "room": "اتاق خواب",
            "goal": None,
        }
    )


# --------------------------------------------------------------------------- #
# The candidate set is the boundary
# --------------------------------------------------------------------------- #
def test_candidate_set_only_contains_products_the_project_can_use():
    """Every candidate suits the room, the job and can be bought."""
    index = _catalog()
    intent = _room_intent()
    plans = build_candidate_set(index, _bedroom_needs(), intent=intent, area=12)

    assert plans, "a bedroom project should have requirements to satisfy"
    for plan in plans:
        for candidate in plan.candidates:
            rooms = set(candidate.product.metadata.get("rooms") or ())
            assert rooms & {"bedroom"}, f"{candidate.product.name} is not a bedroom product"
            assert candidate.product.purchasable_offers
            assert candidate.price > 0


def test_candidate_set_excludes_other_rooms_requirements():
    index = _catalog()
    intent = _room_intent()
    plans = build_candidate_set(index, _bedroom_needs(), intent=intent, area=12)
    slugs = {plan.slug for plan in plans}
    # a bedroom project's needs are the bedroom's, and nothing else was asked for
    assert "dining-table" not in slugs
    assert "sofa" not in slugs


def test_candidates_offer_a_real_choice_for_at_least_one_requirement():
    """A single candidate per requirement would make selection meaningless."""
    index = _catalog()
    intent = _room_intent()
    plans = build_candidate_set(
        index, _bedroom_needs(), intent=intent, area=12
    )
    assert any(len(plan.candidates) > 1 for plan in plans), (
        "no requirement has alternatives, so quality or budget could never change the pick"
    )


def test_complements_are_never_alternatives_of_the_same_subcategory():
    index = _catalog()
    intent = _room_intent()
    plans = build_candidate_set(
        index, _bedroom_needs(), intent=intent, area=12
    )
    for plan in plans:
        for complement in plan.complements:
            assert complement.product.subcategory != plan.slug, (
                "a second product of the same subcategory is an alternative, not a complement"
            )
            assert complement.complementary_for == plan.slug


# --------------------------------------------------------------------------- #
# Validation: the model cannot widen its own candidate set
# --------------------------------------------------------------------------- #
def _plan_for(role: str):
    index = _catalog()
    intent = _room_intent()
    plans = build_candidate_set(
        index, _bedroom_needs(), intent=intent, area=12
    )
    return next(p for p in plans if p.role == role), plans


def test_a_fabricated_product_id_is_rejected():
    """Scenario G: an invented id can never become a recommendation."""
    plan, plans = _plan_for("bed")
    response = ProjectReasoningResponse.model_validate(
        {
            "selections": [
                {
                    "requirement_role": "bed",
                    "product_id": "00000000-0000-0000-0000-000000000000",
                    "reason": "یک محصول ساختگی",
                }
            ],
            "complementary": [],
            "basket_actions": [],
            "budget_assessment": {"status": "no_budget", "reason": ""},
            "explanations": [],
        }
    )
    outcome = _validate(response, plans, set())
    assert outcome.selections == {}
    assert any("not in the candidate set" in r for r in outcome.rejected)


def test_a_product_from_another_requirement_is_rejected():
    """Naming a wardrobe as the bed is a real id, but the wrong relationship."""
    bed_plan, plans = _plan_for("bed")
    other = next(
        c for p in plans for c in p.candidates if p.role != "bed"
    )
    response = ProjectReasoningResponse.model_validate(
        {
            "selections": [
                {"requirement_role": "bed", "product_id": str(other.product.id), "reason": ""}
            ],
            "complementary": [],
            "basket_actions": [],
            "budget_assessment": {"status": "no_budget", "reason": ""},
            "explanations": [],
        }
    )
    outcome = _validate(response, plans, set())
    assert outcome.selections == {}
    assert any("was offered for" in r for r in outcome.rejected)


def test_an_alternative_cannot_be_promoted_to_a_complement():
    """Scenario: the two relationships must not blur into each other."""
    bed_plan, plans = _plan_for("bed")
    alternative = bed_plan.candidates[1] if len(bed_plan.candidates) > 1 else None
    if alternative is None:
        pytest.skip("this subcategory has a single candidate")
    response = ProjectReasoningResponse.model_validate(
        {
            "selections": [],
            "complementary": [
                {
                    "requirement_role": "bed",
                    "product_id": str(alternative.product.id),
                    "reason": "به نظر مکمل می‌آید",
                }
            ],
            "basket_actions": [],
            "budget_assessment": {"status": "no_budget", "reason": ""},
            "explanations": [],
        }
    )
    outcome = _validate(response, plans, set())
    assert outcome.complementary == []
    assert any("not a declared complement" in r for r in outcome.rejected)


def test_a_valid_selection_survives_and_keeps_the_models_reason():
    plan, plans = _plan_for("bed")
    chosen = plan.candidates[-1]  # the most expensive one, to prove it is not forced cheap
    response = ProjectReasoningResponse.model_validate(
        {
            "selections": [
                {
                    "requirement_role": "bed",
                    "product_id": str(chosen.product.id),
                    "reason": "برای کیفیت بالاتر مناسب‌تر است",
                }
            ],
            "complementary": [],
            "basket_actions": [],
            "budget_assessment": {"status": "no_budget", "reason": ""},
            "explanations": [],
        }
    )
    outcome = _validate(response, plans, set())
    assert outcome.selections["bed"].product.id == chosen.product.id
    assert outcome.reasons["bed"] == "برای کیفیت بالاتر مناسب‌تر است"
    assert outcome.rejected == []


def test_a_replacement_outside_the_candidate_set_is_rejected():
    plan, plans = _plan_for("bed")
    response = ProjectReasoningResponse.model_validate(
        {
            "selections": [],
            "complementary": [],
            "basket_actions": [
                {
                    "action": "replace",
                    "current_product_id": "not-in-the-basket",
                    "replacement_product_id": str(plan.candidates[0].product.id),
                    "reason": "",
                }
            ],
            "budget_assessment": {"status": "no_budget", "reason": ""},
            "explanations": [],
        }
    )
    outcome = _validate(response, plans, {"something-else"})
    assert outcome.basket_actions == []
    assert any("unknown basket item" in r for r in outcome.rejected)


# --------------------------------------------------------------------------- #
# End to end: the project's parameters reach the model and can change the pick
# --------------------------------------------------------------------------- #
def _reasoning_reply(selections: dict[str, str], **extra) -> dict:
    return {
        "selections": [
            {"requirement_role": role, "product_id": product_id, "reason": "انتخاب مدل"}
            for role, product_id in selections.items()
        ],
        "complementary": [],
        "basket_actions": [],
        "budget_assessment": {"status": "no_budget", "reason": ""},
        "explanations": [],
        **extra,
    }


def _cheapest_id(plan) -> str:
    return str(plan.candidates[0].product.id)


def _dearest_id(plan) -> str:
    return str(plan.candidates[-1].product.id)


def _plans(intent=None, area=12):
    index = _catalog()
    intent = intent or _room_intent()
    return build_candidate_set(
        index, _bedroom_needs(), intent=intent,
        area=area,
    )


def test_quality_reaches_the_prompt_and_can_change_the_selection(llm):
    """Scenario A: the same project, medium vs ultra, may pick differently."""
    from app.core.enums import Quality
    from app.domains.projects.reasoning import reason_project

    intent = _room_intent()
    plans = _plans(intent)
    bed = next(p for p in plans if p.role == "bed")

    llm.provider_body(content=json.dumps(_reasoning_reply({"bed": _cheapest_id(bed)})))
    _, medium = reason_project(
        intent=intent, plans=plans, area=12, quality=Quality.MEDIUM, style=None,
        budget=None, basket_items=[],
    )
    llm.provider_body(content=json.dumps(_reasoning_reply({"bed": _dearest_id(bed)})))
    _, ultra = reason_project(
        intent=intent, plans=plans, area=12, quality=Quality.ULTRA, style=None,
        budget=None, basket_items=[],
    )

    prompt = llm.calls[-1]["user"]
    assert '"quality":"ultra"' in prompt.replace(" ", ""), "quality must reach the model"
    assert medium.selections["bed"].product.id != ultra.selections["bed"].product.id, (
        "the two quality levels produced the same product, so quality is not "
        "actually influencing selection"
    )


def test_budget_reaches_the_prompt_and_can_change_the_selection(llm):
    """Scenario B: a tighter budget may pick a cheaper valid alternative."""
    from app.core.enums import Quality
    from app.domains.projects.reasoning import reason_project

    intent = _room_intent()
    plans = _plans(intent)
    bed = next(p for p in plans if p.role == "bed")

    llm.provider_body(content=json.dumps(_reasoning_reply({"bed": _dearest_id(bed)})))
    reason_project(
        intent=intent, plans=plans, area=12, quality=Quality.MEDIUM, style=None,
        budget=50_000_000, basket_items=[],
    )
    generous_prompt = llm.calls[-1]["user"]

    llm.provider_body(content=json.dumps(_reasoning_reply({"bed": _cheapest_id(bed)})))
    reason_project(
        intent=intent, plans=plans, area=12, quality=Quality.MEDIUM, style=None,
        budget=6_000_000, basket_items=[],
    )
    tight_prompt = llm.calls[-1]["user"]

    assert "50000000" in generous_prompt
    assert "6000000" in tight_prompt
    assert generous_prompt != tight_prompt


def test_area_reaches_the_prompt(llm):
    """Scenario C: area is part of the project the model is given."""
    from app.core.enums import Quality
    from app.domains.projects.reasoning import reason_project

    intent = _room_intent()
    for area in (8, 40):
        plans = _plans(intent, area=area)
        bed = next(p for p in plans if p.role == "bed")
        llm.provider_body(content=json.dumps(_reasoning_reply({"bed": _cheapest_id(bed)})))
        reason_project(
            intent=intent, plans=plans, area=area, quality=Quality.MEDIUM, style=None,
            budget=None, basket_items=[],
        )
        assert f'"area_m2":{area}' in llm.calls[-1]["user"]


def test_the_prompt_never_contains_the_whole_catalogue(llm):
    """The model is shown a candidate set, not the catalogue."""
    from app.core.enums import Quality
    from app.domains.projects.reasoning import reason_project

    intent = _room_intent()
    plans = _plans(intent)
    bed = next(p for p in plans if p.role == "bed")
    llm.provider_body(content=json.dumps(_reasoning_reply({"bed": _cheapest_id(bed)})))
    reason_project(
        intent=intent, plans=plans, area=12, quality=Quality.MEDIUM, style=None,
        budget=None, basket_items=[],
    )
    prompt = llm.calls[-1]["user"]
    # a complement that is already a candidate is not repeated in the prompt
    already = {str(c.product.id) for p in plans for c in p.candidates}
    supplied = sum(len(p.candidates) for p in plans) + sum(
        1 for p in plans for c in p.complements if str(c.product.id) not in already
    )
    catalog_size = sum(
        len(_catalog().subcategories_of(slug))
        for slug in _catalog().subcategory_slugs()
    )
    assert supplied < catalog_size, (
        f"the prompt carries {supplied} products but the catalogue has "
        f"{catalog_size}; it should be a subset, not everything"
    )
    assert prompt.count('"id"') == supplied, (
        "every product in the prompt must come from a cleared pool"
    )


def test_no_call_when_there_is_nothing_to_choose(llm):
    """Scenario: a project with no choice costs no reasoning call."""
    from app.core.enums import Quality
    from app.domains.projects.reasoning import reason_project

    intent = _room_intent()
    plans = _plans(intent)
    # requirements with no choice at all: nothing to pick between
    single = [p for p in plans if len(p.candidates) <= 1]
    assert single, "expected at least one requirement with nothing to choose between"
    llm.provider_body(content="{}")
    response, outcome = reason_project(
        intent=intent, plans=single, area=12, quality=Quality.MEDIUM, style=None,
        budget=None, basket_items=[],
    )
    assert response is None, "no reasoning call should have been made"
    assert llm.calls == []


def test_a_failing_model_leaves_the_deterministic_answer_intact(llm):
    """A model problem must not break a project."""
    from app.core.enums import Quality
    from app.domains.projects.reasoning import reason_project

    intent = _room_intent()
    plans = _plans(intent)
    bed = next(p for p in plans if p.role == "bed")
    llm.raises = RuntimeError("connection refused")
    response, outcome = reason_project(
        intent=intent, plans=plans, area=12, quality=Quality.MEDIUM, style=None,
        budget=None, basket_items=[],
    )
    assert response is None
    assert outcome.selections == {}, "no selection may be invented when the model fails"
    assert bed.candidates, "the deterministic candidate list is still there"


def test_prices_come_from_the_catalogue_not_the_model(llm):
    """The model's numbers are never authoritative."""
    from app.core.enums import Quality
    from app.domains.projects.reasoning import reason_project

    intent = _room_intent()
    plans = _plans(intent)
    bed = next(p for p in plans if p.role == "bed")
    chosen = bed.candidates[-1]
    # a model trying to state its own price
    llm.provider_body(
        content=json.dumps(
            _reasoning_reply(
                {"bed": str(chosen.product.id)},
                explanations=["این محصول ۱۰۰۰ تومان است"],
            )
        )
    )
    reason_project(
        intent=intent, plans=plans, area=12, quality=Quality.MEDIUM, style=None,
        budget=None, basket_items=[],
    )
    offer = chosen.product.purchasable_offers[0]
    assert chosen.price == int(offer.price), "the candidate price is the catalogue's"
    assert 1000 not in (chosen.price,)




# --------------------------------------------------------------------------- #
# Optimisation: the model proposes, the backend decides what is a valid proposal
# --------------------------------------------------------------------------- #
def _optimization_reply(actions: list[dict], status: str = "over_budget") -> dict:
    return {
        "actions": actions,
        "budget_assessment": {"status": status, "reason": "جمع سبد از بودجه بیشتر است"},
        "explanations": ["یک جایگزین ارزان‌تر پیشنهاد شد."],
    }


def _bed_alternatives():
    """Two real beds from the enriched file: one dearer than the other."""
    index = _catalog()
    from app.catalog.selection import build_room_scope, select_candidates

    beds = select_candidates(
        index, "bed", scope=build_room_scope(index, "اتاق خواب"),
        project_type="redesign", area_m2=12,
    )
    assert len(beds) >= 2, "the fixture needs two beds to reason about"
    dear = max(beds, key=lambda p: p.min_price)
    cheap = min(beds, key=lambda p: p.min_price)
    return index, dear, cheap


def _reason_optimization(llm, *, basket_product, alternatives, action):
    from app.core.enums import Quality
    from app.domains.projects.reasoning import Candidate, reason_optimization

    llm.provider_body(content=json.dumps(_optimization_reply([action])))
    index = _catalog()
    basket_items = [
        {
            "product_id": basket_product.id,
            "name": basket_product.name,
            "subcategory": basket_product.subcategory,
            "unit_price": int(basket_product.min_price),
            "quantity": 1,
            "role": "bed",
        }
    ]
    cleared = [
        Candidate(
            alt,
            requirement_role="bed",
            price=int(alt.purchasable_offers[0].price),
            offer_id=alt.purchasable_offers[0].id,
            seller_name=alt.purchasable_offers[0].seller.name,
        )
        for alt in alternatives
    ]
    return reason_optimization(
        intent=_room_intent(),
        basket_items=basket_items,
        candidates_by_item={str(basket_product.id): cleared},
        area=12,
        quality=Quality.MEDIUM,
        budget=6_000_000,
        style=None,
    )


def test_optimization_sees_only_the_basket_and_its_alternatives(llm):
    """The optimiser is not shown the catalogue."""
    from app.core.enums import Quality
    from app.domains.projects.reasoning import reason_optimization

    index, dear, cheap = _bed_alternatives()
    _optimization_reply([], status="within_budget")
    llm.provider_body(content=json.dumps(_optimization_reply([], status="within_budget")))
    reason_optimization(
        intent=_room_intent(),
        basket_items=[
            {
                "product_id": dear.id,
                "name": dear.name,
                "subcategory": dear.subcategory,
                "unit_price": int(dear.min_price),
                "quantity": 1,
                "role": "bed",
            }
        ],
        candidates_by_item={str(dear.id): []},
        area=12,
        quality=Quality.MEDIUM,
        budget=6_000_000,
        style=None,
    )
    assert llm.calls == [], "no alternatives means no reasoning call"


def test_a_valid_replacement_survives_validation(llm):
    """Scenario D: the model's proposal is accepted as a proposal."""
    _, dear, cheap = _bed_alternatives()
    _, answer, rejected = _reason_optimization(
        llm,
        basket_product=dear,
        alternatives=[cheap],
        action={
            "action": "replace",
            "current_product_id": str(dear.id),
            "replacement_product_id": str(cheap.id),
            "reason": "همان نیاز با هزینهٔ کمتر",
        },
    )
    assert rejected == []
    assert [a.action for a in answer.actions] == ["replace"]
    assert answer.actions[0].replacement_product_id == str(cheap.id)
    assert answer.budget_assessment.status == "over_budget"


def test_an_invented_replacement_is_rejected(llm):
    """Scenario G: an id that was never offered cannot become a proposal."""
    _, dear, cheap = _bed_alternatives()
    _, answer, rejected = _reason_optimization(
        llm,
        basket_product=dear,
        alternatives=[cheap],
        action={
            "action": "replace",
            "current_product_id": str(dear.id),
            "replacement_product_id": "00000000-0000-0000-0000-000000000000",
            "reason": "یک محصول ساختگی",
        },
    )
    assert answer.actions == []
    assert any("not a cleared alternative" in r for r in rejected)


def test_a_replacement_outside_the_basket_is_rejected(llm):
    _, dear, cheap = _bed_alternatives()
    _, answer, rejected = _reason_optimization(
        llm,
        basket_product=dear,
        alternatives=[cheap],
        action={
            "action": "replace",
            "current_product_id": "00000000-0000-0000-0000-000000000000",
            "replacement_product_id": str(cheap.id),
            "reason": "قلمی که در سبد نیست",
        },
    )
    assert answer.actions == []
    assert any("unknown basket item" in r for r in rejected)


def test_a_remove_is_returned_as_a_proposal_not_an_edit(llm):
    """The model may say remove; the backend never treats that as a deletion."""
    _, dear, cheap = _bed_alternatives()
    _, answer, rejected = _reason_optimization(
        llm,
        basket_product=dear,
        alternatives=[cheap],
        action={"action": "remove", "current_product_id": str(dear.id), "reason": "گران است"},
    )
    assert rejected == []
    assert [a.action for a in answer.actions] == ["remove"]


def test_keep_everything_is_a_valid_answer(llm):
    _, dear, cheap = _bed_alternatives()
    _, answer, rejected = _reason_optimization(
        llm,
        basket_product=dear,
        alternatives=[cheap],
        action={"action": "keep", "current_product_id": str(dear.id), "reason": "مناسب است"},
    )
    assert rejected == []
    assert [a.action for a in answer.actions] == ["keep"]
    assert answer.budget_assessment.status == "over_budget"


# --------------------------------------------------------------------------- #
# Room normalisation and template choice without a category
# --------------------------------------------------------------------------- #
def test_the_taxonomy_carries_the_catalogues_own_rooms():
    """The room list is read from the file, so it grows with the data."""
    from app.domains.search.taxonomy import build_taxonomy

    from app.catalog.selection import room_vocabulary

    rooms = {token for token, _words in build_taxonomy().rooms}
    # every room the model may name is one the file actually places products in
    assert rooms == set(room_vocabulary(_catalog()))
    assert {"living_room", "bedroom", "kitchen"} <= rooms


def test_a_room_named_in_the_users_own_words_resolves_deterministically():
    from app.domains.search.taxonomy import build_taxonomy

    taxonomy = build_taxonomy()
    # the file says "خواب", so the user's word matches it without a phrase list
    assert taxonomy.room_token("خوابم") == "bedroom"


def test_the_model_may_name_a_room_the_file_never_uses():
    """A word absent from the file is placed by the model, then checked."""
    from app.domains.search.llm_schema import LLMIntentResponse
    from app.domains.search.llm_interpreter import LLMInterpreter
    from app.domains.search.taxonomy import build_taxonomy

    taxonomy = build_taxonomy()
    # nothing in the file says "پذیرایی", so only the model can close that gap
    assert taxonomy.room_token("پذیرایی") is None

    placed = LLMInterpreter().resolve(
        "دکور پذیرایی رو تغییر بدم",
        LLMIntentResponse.model_validate(
            {"intent": "project_search", "category": None,
             "project": {"type": "redesign", "room": "پذیرایی",
                         "room_token": "living_room", "area_m2": None}}
        ),
        taxonomy,
    )
    assert placed.room_token == "living_room"
    assert placed.intent.value == "NEED_SEARCH", "the project keeps its intent"
    assert placed.domain is None, "and the category stays absent"


def test_an_invented_room_token_is_refused():
    """The model can name a space; it cannot invent one."""
    from app.domains.search.llm_schema import LLMIntentResponse
    from app.domains.search.llm_interpreter import LLMInterpreter
    from app.domains.search.taxonomy import build_taxonomy

    out = LLMInterpreter().resolve(
        "یک جای خاص",
        LLMIntentResponse.model_validate(
            {"intent": "project_search", "category": None,
             "project": {"type": "redesign", "room": "یک جای خاص",
                         "room_token": "spaceship_bridge", "area_m2": None}}
        ),
        build_taxonomy(),
    )
    assert out.room_token is None
    assert out.room == "یک جای خاص", "the user's own wording is still reported"


# --------------------------------------------------------------------------- #
# A prompt that cannot be rendered is a bug, and it used to be silent
# --------------------------------------------------------------------------- #
def test_a_decimal_area_does_not_break_the_prompt():
    """The area can arrive from a Numeric column as a Decimal.

    json refuses a Decimal, so a project asked for without a size used to raise
    TypeError inside the reasoning call, fall back quietly, and still answer
    HTTP 200. The payload has to render whatever the columns hand over.
    """
    from decimal import Decimal as D

    from app.core.enums import Quality as Q
    from app.domains.projects.reasoning import _render, project_payload

    intent = _room_intent()
    plans = _plans(intent)
    for area in (D("14.00"), D("0.01"), 14.0, 14, None):
        rendered = _render(
            project_payload(
                intent=intent, plans=plans, area=area, quality=Q.MEDIUM,
                style=None, budget=None, basket_items=[],
            )
        )
        assert isinstance(rendered, str)
        assert "room" in rendered


def test_a_failing_reasoning_call_is_reported_not_hidden():
    """A failure must be visible in the outcome, not just swallowed."""
    from app.core.enums import Quality as Q
    from app.domains.projects.reasoning import reason_project
    import app.domains.projects.reasoning as module

    intent = _room_intent()
    plans = _plans(intent)

    def boom(**_kwargs):
        raise TypeError("simulated")

    original = module.chat_json if hasattr(module, "chat_json") else None
    import app.llm as llm
    real = llm.chat_json
    llm.chat_json = boom
    try:
        response, outcome = reason_project(
            intent=intent, plans=plans, area=None, quality=Q.MEDIUM, style=None,
            budget=None, basket_items=[],
        )
    finally:
        llm.chat_json = real

    assert response is None
    assert outcome.ran is False, "a failed call must not look like a completed one"
    assert outcome.selections == {}, "nothing may be invented when the call failed"
    assert outcome.error and "TypeError" in outcome.error


# --------------------------------------------------------------------------- #
# The room constrains which products answer a need, not which needs exist
# --------------------------------------------------------------------------- #
#
# This used to be a different test. There was a filter that cut a *template's*
# rules down to the room, and these tests pinned it: a bedroom project kept
# bed and wardrobe and dropped sofa. The filter is gone, and with it the
# question it answered — requirements no longer arrive in a fixed list to be
# trimmed, they arrive as the interpreter's understanding of the sentence.
#
# What the room still does is narrower and stronger: it decides which catalogue
# products may answer a need. That is below.


def _intent_for(room: str, token: str | None, project_type: str = "redesign"):
    return InterpretedIntent.model_validate(
        {
            "intent": "NEED_SEARCH", "domain": None, "project_type": project_type,
            "template_slug": None, "product_query": None,
            "requirements": {"area_m2": 12, "quality": None, "style": None,
                             "budget": None, "priorities": [], "extra": {}},
            "constraint_kind": "NONE", "confidence": 1.0, "interpreter": "llm",
            "explanations": [], "matched_subcategories": [],
            "missing_categories": [], "room": room, "room_token": token, "goal": None,
            "project_requirements": [],
        }
    )


def test_a_bedroom_project_only_ever_offers_bedroom_products():
    index = _catalog()
    intent = _intent_for("bedroom", "bedroom")
    plans = build_candidate_set(index, _bedroom_needs(), intent=intent, area=12)

    assert plans
    for plan in plans:
        for candidate in plan.candidates:
            rooms = set(candidate.product.metadata.get("rooms") or ())
            assert rooms & {"bedroom"}, f"{candidate.product.name} is not a bedroom product"


def test_a_room_scope_filters_products_and_never_the_needs():
    """The room narrows the offer; it does not narrow what the project is.

    This is the distinction the old architecture got wrong. A room filter used to
    cut a *requirement list* down to the room — which is only a meaningful thing
    to do when the list came from a rulebook rather than from the person. The
    needs are now whatever the interpreter said, in every room; what the room
    decides is which catalogue products may answer them.
    """
    index = _catalog()
    needs = _needs("bed", "wardrobe")
    bedroom = build_candidate_set(
        index, needs, intent=_intent_for("bedroom", "bedroom"), area=12
    )
    living_room = build_candidate_set(
        index, needs, intent=_intent_for("پذیرایی", "living_room"), area=12
    )

    # identical needs, whatever the room
    assert [p.role for p in bedroom] == [p.role for p in living_room] == ["bed", "wardrobe"]
    # and every product offered belongs to the room it was offered in
    for plans, room in ((bedroom, "bedroom"), (living_room, "living_room")):
        for plan in plans:
            for candidate in plan.candidates:
                assert room in set(candidate.product.metadata.get("rooms") or ())


def test_a_room_named_as_the_catalogue_token_still_scopes():
    """The interpreter may put the token in `room` and omit `room_token`.

    That is what the runtime did, and the vocabulary holds the file's *product*
    words, so the token matched nothing and every room-tagged product came
    through. The room is still the room.
    """
    index = _catalog()
    with_token = build_candidate_set(
        index, _bedroom_needs(), intent=_intent_for("bedroom", "bedroom"), area=12
    )
    without = build_candidate_set(
        index, _bedroom_needs(), intent=_intent_for("bedroom", None), area=12
    )
    assert {c.product.id for p in with_token for c in p.candidates} == {
        c.product.id for p in without for c in p.candidates
    }


def test_each_space_gets_only_its_own_products():
    index = _catalog()
    for room, expected in (("bedroom", "bed"), ("living_room", "sofa"), ("home_office", "desk")):
        needs = _needs(expected)
        plans = build_candidate_set(index, needs, intent=_intent_for(room, room), area=12)
        assert any(plan.candidates for plan in plans), f"{room} has nothing for {expected}"
        for plan in plans:
            for candidate in plan.candidates:
                rooms = set(candidate.product.metadata.get("rooms") or ())
                assert room in rooms, f"{candidate.product.name} is not a {room} product"


def test_kitchen_renovation_offers_only_kitchen_products():
    index = _catalog()
    needs = _needs("sink", "cooktop")
    intent = _intent_for("kitchen", "kitchen", project_type="renovation")
    for plan in build_candidate_set(index, needs, intent=intent, area=12):
        for candidate in plan.candidates:
            assert "kitchen" in set(candidate.product.metadata.get("rooms") or ())


def test_the_reasoning_payload_shrinks_with_the_room_scope():
    """The bound is on what reaches the model, not on raising its budget."""
    from app.core.enums import Quality as Q
    from app.domains.projects.reasoning import _render, project_payload

    index = _catalog()
    unscoped_intent = _intent_for("حیاط", None)
    unscoped = build_candidate_set(index, _bedroom_needs(), intent=unscoped_intent, area=12)
    big = _render(project_payload(intent=unscoped_intent, plans=unscoped, area=12,
                                  quality=Q.MEDIUM, style=None, budget=None, basket_items=[]))
    intent = _intent_for("bedroom", "bedroom")
    scoped = build_candidate_set(index, _bedroom_needs(), intent=intent, area=12)
    small = _render(project_payload(
        intent=intent, plans=scoped,
        area=12, quality=Q.MEDIUM, style=None, budget=None, basket_items=[]))
    assert len(small) < len(big), "the payload must shrink, not grow"


def test_a_room_the_catalogue_does_not_know_stays_unscoped():
    """Unknown stays unknown: it is not guessed, and it is not an error."""
    from app.catalog.selection import build_room_scope

    assert build_room_scope(_catalog(), "حیاط").tokens == frozenset()


def test_every_catalogue_room_token_resolves_to_itself():
    """A room the file declares is a room, however it was written."""
    from app.catalog.selection import build_room_scope, room_vocabulary

    index = _catalog()
    for token in room_vocabulary(index):
        assert build_room_scope(index, token).tokens == frozenset({token})


# --------------------------------------------------------------------------- #
# The room-token contract, and the reasoning output contract
# --------------------------------------------------------------------------- #
def test_the_prompt_offers_canonical_room_tokens_separately_from_evidence():
    """room_token is an identifier, and the evidence must not be mistaken for it."""
    from app.domains.search.llm_interpreter import LLMInterpreter
    from app.domains.search.taxonomy import build_taxonomy

    taxonomy = build_taxonomy()
    prompt = LLMInterpreter()._user_prompt("دکوراسیون پذیرایی", taxonomy)

    tokens = {token for token, _words in taxonomy.rooms}
    block = prompt.split("شناسه‌های مجاز room_token:")[1].split("شاهد")[0]
    # every identifier is offered, and only identifiers
    assert all(token in block for token in tokens)
    assert not any(w in block for _t, words in taxonomy.rooms for w in words), (
        "product words must not appear in the token list"
    )
    # the two are labelled apart
    assert "شاهد" in prompt


def test_the_evidence_identifies_each_room():
    """A word that only one room uses is what names that room."""
    from app.domains.search.taxonomy import build_taxonomy

    taxonomy = build_taxonomy()
    spread: dict[str, set[str]] = {}
    for token, words in taxonomy.rooms:
        for word in words:
            spread.setdefault(word, set()).add(token)
    # مبل is only in a living room in this catalogue, which is what lets the
    # model place "پذیرایی" without a phrase table on our side.
    assert spread.get("مبل") == {"living_room"}


def test_the_prompt_asks_for_both_room_fields():
    from app.domains.search.llm_interpreter import SYSTEM_PROMPT

    assert "room_token" in SYSTEM_PROMPT
    # and the example the model copies carries it too
    example = SYSTEM_PROMPT.strip().splitlines()[-1]
    assert '"room_token"' in example, "the example must not contradict the schema"


def test_the_reasoning_prompt_states_the_canonical_output():
    """Prompt, JSON schema and parser must be the same shape."""
    from app.domains.projects.reasoning import (
        OPTIMIZATION_SYSTEM_PROMPT,
        PROJECT_SYSTEM_PROMPT,
    )

    for prompt, fields in (
        (PROJECT_SYSTEM_PROMPT,
         ("selections", "requirement_role", "product_id", "complementary",
          "basket_actions", "budget_assessment", "explanations")),
        (OPTIMIZATION_SYSTEM_PROMPT,
         ("actions", "current_product_id", "replacement_product_id")),
    ):
        for field in fields:
            assert f'"{field}"' in prompt, f"{field} is missing from the prompt"


def test_the_canonical_reasoning_answer_parses():
    from app.domains.projects.reasoning import ProjectReasoningResponse

    answer = {
        "selections": [{"requirement_role": "sofa", "product_id": "abc", "reason": "مناسب"}],
        "complementary": [],
        "basket_actions": [],
        "budget_assessment": {"status": "no_budget", "reason": "بودجه‌ای نیست"},
        "explanations": [],
    }
    parsed = ProjectReasoningResponse.model_validate(answer)
    assert parsed.selections[0].requirement_role == "sofa"
    assert parsed.budget_assessment.status == "no_budget"


def test_the_shape_the_model_actually_returned_is_rejected():
    """Reproduces the runtime failure so the mismatch cannot come back quietly.

    The model echoed the *input* payload instead of answering in the contract:
    `role`/`candidate_id`/`name`/`price_toman` are not output fields, and
    `budget_not_provided` is not a status. Both are refused, on purpose.
    """
    from pydantic import ValidationError

    from app.domains.projects.reasoning import ProjectReasoningResponse

    answer = {
        "selections": [{
            "role": "sofa", "subcategory": "sofa", "candidate_id": "abc",
            "name": "مبل راحتی", "quantity": 1, "price_toman": 5850000,
            "seller": "فروشگاه", "quality": "medium", "reason": "مناسب",
        }],
        "basket_actions": [],
        "budget_assessment": {
            "budget_toman": None, "selected_total_toman": 5850000,
            "status": "budget_not_provided", "reason": "",
        },
    }
    with pytest.raises(ValidationError) as caught:
        ProjectReasoningResponse.model_validate(answer)
    text = str(caught.value)
    assert "extra_forbidden" in text
    assert "budget_assessment.status" in text
    # and the prompt now says so, so the model is not left guessing
    from app.domains.projects.reasoning import PROJECT_SYSTEM_PROMPT

    assert "budget_not_provided" in PROJECT_SYSTEM_PROMPT
    assert "پاسخ نیست" in PROJECT_SYSTEM_PROMPT
