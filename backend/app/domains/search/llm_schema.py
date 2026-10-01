"""The contract the intent model has to answer.

The model answers one question: *what is this person asking for?* It is not
asked which catalogue products apply, because that is the catalogue's business
and it is better at it.

Two rules shape this schema.

**The model names no catalogue slugs.** It used to be asked for
``catalog.subcategories``, and it answered ``["furniture"]`` — a top-level
category, not a subcategory, so nothing matched. Rather than validate a value
the model had no business producing, the field is gone. The model now returns a
single ``category`` drawn from a closed set, and the backend maps that onto real
subcategories deterministically. A slug it cannot name is a slug it cannot get
wrong.

**The model names no catalogue facts.** There is no field for a product, a
seller, a price, an offer, availability or a specification, and ``extra`` is
forbidden so one cannot be smuggled in. Products come from ``products.json`` or
nowhere.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, PrivateAttr, field_validator, model_validator

from app.core.enums import Domain, ProjectType, Quality
from app.domains.search.schemas import (
    MAX_QUERY_LENGTH,
    ConstraintKind,
    SemanticRequirement,
    StrictModel,
)


class ProjectIntent(StrictModel):
    """The project the user described, as far as they actually said it."""

    #: one of ProjectType, or null when they did not say
    type: ProjectType | None = None
    #: the room or space, named plainly. Not "۱۲متری‌ام" — the size goes in
    #: ``area_m2``, and a measurement left in here reads as the room's name.
    room: str | None = None
    #: Which of the catalogue's own rooms this project is about, chosen from the
    #: room list supplied in the prompt. This is a *space*, not a category: it
    #: decides which products the file places in that room, and nothing else. It
    #: may be null when the user named no space we recognise — the project is
    #: still a project, and unplaceable is not the same as invalid.
    room_token: str | None = None
    #: only when the user stated a number
    area_m2: float | None = Field(default=None, gt=0)
    #: what they want to achieve, in their words
    goal: str | None = None
    #: only what they actually said
    constraints: list[str] = Field(default_factory=list)
    #: What the project needs, in the model's own understanding of the sentence.
    #:
    #: This is the *source* of a project's requirements. It used to come from a
    #: predefined template, which meant a model that understood «a gaming corner
    #: in my hall» perfectly well still had its project overwritten by whichever
    #: rulebook matched the room name.
    requirements: list[SemanticRequirement] = Field(default_factory=list)


class SearchTerms(StrictModel):
    """
    What to look for, in the user's own words.

    These are handed to the deterministic catalogue search, which decides what
    actually matches. Nothing is interpreted twice.
    """

    #: the product words, with the filler removed
    text: str | None = None
    terms: list[str] = Field(default_factory=list)
    brand: str | None = None
    color: str | None = None

    @field_validator("terms")
    @classmethod
    def _cap_terms(cls, value: list[str]) -> list[str]:
        return [t for t in (v.strip() for v in value) if t][:12]


class Constraints(StrictModel):
    """Explicit requirements, only when the user actually stated them."""

    quality: Quality | None = None
    #: toman
    budget: int | None = Field(default=None, ge=0)
    notes: list[str] = Field(default_factory=list)


class LLMIntentResponse(StrictModel):
    """
    The whole answer, validated before anything downstream sees it.

    Deliberately small: a small schema is a small prompt, and a small prompt is a
    fast one. Every field here is something only a model can work out.
    """

    #: A Literal, so the JSON Schema sent to the provider carries the closed set.
    intent: Literal["product_search", "project_search", "unknown"]
    #: the one catalogue reference the model may name, and it is a top-level
    #: category, checked against the catalogue before it is used
    category: Domain | None = None
    #: what the model actually said, kept only so a value we do not recognise
    #: can be reported. It is never used as a category.
    category_raw: str | None = None
    project: ProjectIntent | None = None
    search: SearchTerms | None = None
    constraints: Constraints = Field(default_factory=Constraints)
    constraint_kind: ConstraintKind = ConstraintKind.NONE
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    explanations: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, data: Any) -> Any:
        """
        Fold the spelling variants a model reaches for, before the schema checks.

        A ``Literal`` is what puts an enum in the JSON Schema, but it rejects
        ``"PRODUCT_SEARCH"`` and ``"furniture"`` with a capital outright. Folding
        first is a normalisation of the *spelling*; it never invents a value that
        was not one of the allowed ones.
        """
        if not isinstance(data, dict):
            return data
        out = dict(data)
        for key in ("intent", "category"):
            value = out.get(key)
            if isinstance(value, str):
                out[key] = value.strip().lower().replace("-", "_").replace(" ", "_")
        return out

    @model_validator(mode="before")
    @classmethod
    def _keep_an_unknown_category_from_failing_everything(cls, data: Any) -> Any:
        """
        An unrecognised category is dropped, not fatal.

        A ``Domain`` field is what puts the enum in the JSON Schema the provider
        is given, but it would also throw away a perfectly good interpretation
        because of one bad word — and a small model produces bad words. So the
        word is kept in ``category_raw`` for reporting, ``category`` becomes null,
        and the intent, room and area all survive.
        """
        if not isinstance(data, dict):
            return data
        claimed = data.get("category")
        if not isinstance(claimed, str) or not claimed.strip():
            return data
        if claimed.strip().lower() in {d.value for d in Domain}:
            return data
        return {**data, "category": None, "category_raw": claimed.strip()[:80]}

    @field_validator("explanations")
    @classmethod
    def _cap_explanations(cls, value: list[str]) -> list[str]:
        return [v for v in (x.strip() for x in value) if v][:3]

    @field_validator("project")
    @classmethod
    def _cap_room_and_goal(cls, value: ProjectIntent | None) -> ProjectIntent | None:
        if value is None:
            return None
        if value.room:
            value.room = value.room[:80]
        if value.goal:
            value.goal = value.goal[:160]
        value.constraints = [c[:160] for c in value.constraints][:8]
        value.requirements = value.requirements[:12]
        return value

    def constraint_kind_from_evidence(self) -> ConstraintKind:
        """What the query is really about, when it is not a search at all."""
        if self.intent != "unknown":
            return self.constraint_kind
        if self.constraints.budget is not None:
            return ConstraintKind.BUDGET
        if self.constraints.quality is not None:
            return ConstraintKind.QUALITY
        if self.project and self.project.area_m2 is not None:
            return ConstraintKind.AREA
        return ConstraintKind.NONE

    def text_for_search(self, query: str) -> str:
        """
        The string the catalogue search will actually run.

        Prefers the extracted terms, because «یه شیر توالت خوب میخوام» carries
        filler the catalogue should not try to match. Falls back to the raw query
        when nothing was extracted.
        """
        if self.intent != "product_search" or self.search is None:
            return query
        parts = [t for t in (self.search.text, *self.search.terms) if t]
        if self.search.brand:
            parts.append(self.search.brand)
        if self.search.color:
            parts.append(self.search.color)
        joined = " ".join(parts).strip()
        return joined[:MAX_QUERY_LENGTH] or query


__all__ = [
    "Constraints",
    "LLMIntentResponse",
    "ProjectIntent",
    "SearchTerms",
    "SemanticRequirement",
]
