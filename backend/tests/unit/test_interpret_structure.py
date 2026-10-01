"""
One failure from the runtime log: the model's semantics were right and its
structure was not.

«بازسازی سرویس بهداشتی ۱۲ متری، کیفیت متوسط» came back with ``intent:
project_search``, ``area_m2: 12``, ``quality: medium``, the right room and a real
requirements list — and with ``search``, ``constraint_kind``, ``confidence``,
``explanations`` and the root ``constraints`` object *inside* ``project``.

That is not a near miss that can be absorbed. ``ProjectIntent`` is a ``StrictModel``
(``extra="forbid"``), so every one of those misplaced keys is a validation error,
and a correct interpretation is discarded with a 503. There is nothing to repair
downstream without weakening the schema, and weakening it is the wrong trade: a
strict schema is the only reason a wrong shape is visible at all.

So the prompt is what changed, and these tests pin the two deterministic things
behind it — the contract the prompt states, and the schema's behaviour on the exact
broken payload. No model is called. That the model now obeys the contract is a fact
about the model, and is the one thing here that must be confirmed against a live
run.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domains.search.llm_interpreter import SYSTEM_PROMPT, LLMInterpreter
from app.domains.search.llm_schema import LLMIntentResponse
from app.domains.search.taxonomy import build_taxonomy

QUERY = "بازسازی سرویس بهداشتی ۱۴ متری، کیفیت متوسط"


@pytest.fixture
def real_catalog(monkeypatch):
    """The enriched file, so ``room_token`` has the room list to resolve against."""
    import os
    from pathlib import Path

    from app.catalog.store import reset_cache
    from app.core.config import get_settings

    path = Path(__file__).resolve().parents[3] / "data" / "catalog" / "products_70_enriched.json"
    monkeypatch.setenv("CATALOG_PATH", str(path))
    get_settings.cache_clear()
    reset_cache()
    yield path
    if previous := os.environ.get("CATALOG_PATH"):
        os.environ["CATALOG_PATH"] = previous
    get_settings.cache_clear()
    reset_cache()


# --------------------------------------------------------------------------- #
# The broken payload, exactly as it arrived
# --------------------------------------------------------------------------- #
def _nested_payload() -> dict:
    """The logged response: good semantics, root fields pushed one level down."""
    return {
        "intent": "project_search",
        "category": "bathroom",
        "project": {
            "type": "renovation",
            "room": "سرویس بمداشتی",
            "room_token": "bathroom",
            "area_m2": 12,
            "goal": None,
            "constraints": [],
            "requirements": [
                {
                    "description": "کاشی و سرامیک برای کف و دیوار",
                    "terms": ["کاشی", "سرامیک"],
                    "quantity": None,
                    "required": True,
                    "quality_min": "medium",
                }
            ],
            # …and the four that do not belong here:
            "search": None,
            "constraints": {"quality": "medium", "budget": None, "notes": []},
            "constraint_kind": "QUALITY",
            "confidence": 0.99,
            "explanations": ["بازسازی سرویس بهداشتی با کیفیت متوسط"],
        },
        "search": None,
        "constraints": {"quality": "medium", "budget": None, "notes": []},
        "constraint_kind": "QUALITY",
        "confidence": 0.99,
        "explanations": ["بازسازی سرویس بهداشتی با کیفیت متوسط"],
    }


def _correct_payload() -> dict:
    """The same answer with every field in the place the schema expects."""
    return {
        "intent": "project_search",
        "category": "bathroom",
        "project": {
            "type": "renovation",
            "room": "سرویس بهداشتی",
            "room_token": "bathroom",
            "area_m2": 12,
            "goal": None,
            "constraints": [],
            "requirements": [
                {
                    "description": "کاشی و سرامیک برای کف و دیوار",
                    "terms": ["کاشی", "سرامیک"],
                    "quantity": None,
                    "required": True,
                    "quality_min": "medium",
                }
            ],
        },
        "search": None,
        "constraints": {"quality": "medium", "budget": None, "notes": []},
        "constraint_kind": "QUALITY",
        "confidence": 0.99,
        "explanations": ["بازسازی سرویس بهداشتی با کیفیت متوسط"],
    }


class TestTheBrokenShapeIsStillRejected:
    """The strict schema is the reason this is visible. It has to stay strict."""

    def test_nesting_the_root_fields_fails_validation(self):
        with pytest.raises(ValidationError) as caught:
            LLMIntentResponse.model_validate(_nested_payload())
        assert caught.value.errors()

    @pytest.mark.parametrize(
        "smuggled",
        ["search", "constraints", "constraint_kind", "confidence", "explanations"],
    )
    def test_each_root_field_is_refused_inside_project(self, smuggled):
        payload = _nested_payload()
        # `constraints` is legal inside project as a *list*; the object is not.
        if smuggled == "constraints":
            payload["project"]["constraints"] = {"quality": "medium", "budget": None}
        else:
            payload["project"][smuggled] = payload[smuggled]
        with pytest.raises(ValidationError):
            LLMIntentResponse.model_validate(payload)


# --------------------------------------------------------------------------- #
# The prompt must now say what the schema cannot say for itself
# --------------------------------------------------------------------------- #
class TestThePromptStatesTheHierarchy:
    def test_it_lists_the_fields_project_may_contain(self):
        for field in ("type", "room", "room_token", "area_m2", "goal", "constraints",
                      "requirements"):
            assert field in SYSTEM_PROMPT

    def test_it_forbids_the_root_fields_inside_project(self):
        """Each banned key must be named next to ``project``, not left implied."""
        forbidden_section = SYSTEM_PROMPT[
            SYSTEM_PROMPT.index("در project فقط") : SYSTEM_PROMPT.index("همین حالا JSON")
        ]
        for field in ("search", "constraint_kind", "confidence", "explanations"):
            assert field in forbidden_section

    def test_it_tells_the_two_constraints_fields_apart(self):
        """``project.constraints`` is a list; ``constraints`` is the object at root.

        This is the merge the model actually made, so the prompt has to name both
        and say they are not the same field.
        """
        assert "project.constraints" in SYSTEM_PROMPT
        assert "دو فیلد constraints" in SYSTEM_PROMPT

    def test_it_no_longer_asks_for_reasoning(self):
        """The contradictory instruction is gone, replaced by the flat demand."""
        assert "همین حالا JSON را بنویس." in SYSTEM_PROMPT
        assert "هیچ reasoning یا prose تولید نکن" in SYSTEM_PROMPT
        assert "فقط و فقط یک JSON object" in SYSTEM_PROMPT
        assert "یک کار ساختاری کوچک است" not in SYSTEM_PROMPT

    def test_explanations_remain_the_one_allowed_prose_field(self):
        assert "explanations" in SYSTEM_PROMPT


# --------------------------------------------------------------------------- #
# The semantics of the logged query, unchanged and correct
# --------------------------------------------------------------------------- #
class TestTheQueryStillReadsCorrectly:
    """The logged query, answered correctly — the semantics this fix must not touch.

    The four assertions are on the parsed model response, because that is where
    the nesting happened: ``project.type``, ``project.room_token``,
    ``project.area_m2`` and the root ``constraints.quality`` are four different
    places, and only the last one is at the root.
    """

    @staticmethod
    def _parsed() -> LLMIntentResponse:
        return LLMIntentResponse.model_validate(_correct_payload())

    def test_the_project_facts_are_read_from_the_query(self):
        parsed = self._parsed()
        assert parsed.project is not None
        assert parsed.project.type.value == "renovation"
        assert parsed.project.room_token == "bathroom"
        assert parsed.project.area_m2 == 12

    def test_quality_lands_in_the_root_constraints(self):
        parsed = self._parsed()
        assert parsed.constraints.quality.value == "medium"
        # …and nowhere else. This is the exact mistake: a second `constraints`
        # inside `project`, in the object form where a list belongs.
        assert parsed.project.constraints == []

    def test_root_fields_are_at_root(self):
        parsed = self._parsed()
        assert parsed.search is None
        assert parsed.constraint_kind.value == "QUALITY"
        assert parsed.confidence == 0.99
        assert parsed.explanations == ["بازسازی سرویس بهداشتی با کیفیت متوسط"]
        # nothing that belongs to the root is reachable through `project`
        assert not hasattr(parsed.project, "search")
        assert not hasattr(parsed.project, "constraint_kind")
        assert not hasattr(parsed.project, "confidence")
        assert not hasattr(parsed.project, "explanations")

    def test_resolution_keeps_the_same_reading(self, real_catalog):
        result = LLMInterpreter().resolve(
            "بازسازی سرویس بهداشتی ۱۲ متری، کیفیت متوسط",
            self._parsed(),
            build_taxonomy(),
        )
        assert result.intent.value == "NEED_SEARCH"  # how the resolver names a project
        assert result.project_type.value == "renovation"
        assert result.room_token == "bathroom"
        assert result.requirements.area_m2 == 12
        # root quality and root constraint_kind, resolved onto the requirement set
        assert result.requirements.quality.value == "medium"
        assert result.constraint_kind.value == "QUALITY"
        # a project query is not a product query, and must not turn into one
        assert result.product_query is None

    def test_the_needs_stay_semantic_needs(self, real_catalog):
        """Requirements stay needs of the job — no brand, price or SKU invented."""
        result = LLMInterpreter().resolve(
            "بازسازی سرویس بهداشتی ۱۲ متری، کیفیت متوسط",
            self._parsed(),
            build_taxonomy(),
        )
        assert [need.description for need in result.project_requirements] == [
            "کاشی و سرامیک برای کف و دیوار"
        ]
        assert result.project_requirements[0].quality_min.value == "medium"
