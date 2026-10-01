"""Intent interpretation contracts.

DESIGN RULE (product principle #4)
-----------------------------------
These schemas describe **only what the user wants**, never what exists in the
market. There is intentionally no field for a product id, seller, price, offer,
availability or specification anywhere in this module: the interpreter cannot
represent invented catalogue data, so an LLM answering this schema cannot
fabricate it. Products and prices are resolved afterwards from PostgreSQL.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from app.core.enums import Domain, Intent, ProjectType, Quality
from app.core.text import format_toman

MAX_QUERY_LENGTH = 500


class StrictModel(BaseModel):
    """Rejects unknown keys so an LLM cannot smuggle extra data through."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ConstraintKind(StrEnum):
    BUDGET = "BUDGET"
    QUALITY = "QUALITY"
    STYLE = "STYLE"
    AREA = "AREA"
    PRIORITY = "PRIORITY"
    NONE = "NONE"


class ProductQuery(StrictModel):
    """What the user typed about a product, still unresolved."""

    text: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH)
    tokens: list[str] = Field(default_factory=list)
    raw_brand: str | None = None
    brand_id: UUID | None = None
    brand_name: str | None = None
    category_slug: str | None = None
    category_name: str | None = None
    domain: Domain | None = None
    quality: Quality | None = None
    style: str | None = None


class RequirementSpec(StrictModel):
    """Structured, editable constraints extracted from a need query."""

    area_m2: float | None = None
    quality: Quality | None = None
    style: str | None = None
    budget: int | None = Field(default=None, ge=0)
    priorities: list[str] = Field(default_factory=list)
    extra: dict[str, str | int | float | bool] = Field(default_factory=dict)

    @field_serializer("area_m2")
    def _serialize_area(self, value: float | None) -> float | int | None:
        # "12.0" reads badly in the API/UI; emit 12 for integral areas
        if value is not None and float(value).is_integer():
            return int(value)
        return value


class SemanticRequirement(StrictModel):
    """
    One thing the user's project needs — a **purchasable need**, not a quotation.

    This is the model's most important output, and the reason the project engine
    has no opinion of its own: *what this person is trying to achieve* is
    understanding, and it belongs to the model. The deterministic layer owns
    everything after it — which catalogue products answer this need, what they
    cost, whether they can be bought.

    **A need is not what the user said. It is what their goal decomposes into.**
    «میخوام گوشه هال یه فضای گیمینگ ایجاد کنم» names no purchasable thing at
    all; a model asked to transcribe it produces «تجهیزات لازم برای ایجاد فضای
    گیمینگ», which resolves to nothing in any catalogue. The model is therefore
    expected to *derive* the needs its goal implies — «میز», «صندلی» — and
    stopping at the abstraction is the failure this docstring exists to prevent.
    Deriving them is decomposition, not recommendation: the model still names no
    product, only the kind of thing needed.

    **Requirements are procurement planning; project facts are transcription.**
    Those are two different contracts and the prompt keeps them apart, because
    conflating them is what made this field come back empty. A user who describes
    a bedroom redesign has not enumerated a purchase list — and being asked to help
    them work out what that redesign needs *is the request*. So a requirement need
    not have been named by the user, and ordinary domain knowledge of what a job
    of this kind requires is the expected source, not a hallucination.

    The model is given a procedure: identify the requested outcome and its scope,
    identify what would have to be obtained or done to reach it, split that where
    the outcome plainly has several parts, and stay at the sentence's own level of
    detail when it did not say more. Every candidate is then checked for relevance
    to *this* project — something you would actually obtain to complete this job.

    What the model is not asked to do is consult a list. A room, a project type and
    a use case each have an obvious shopping list, and a model that consults one
    gives the same answer for every bedroom regardless of what was asked, which is
    the template this contract removed, arriving through the prompt instead of the
    database. Equally, the earlier version of this prompt asked a model to justify
    every inferred item against "did the user ask for this, or is it just usual in
    that room?" — a question with no good answer, since a bed is both, and a model
    asked it returns nothing. An empty list is now the exceptional case, reserved
    for input that describes no project at all.

    **A need does not have to be purchasable from *this* catalogue.** If a
    complete gaming room needs a monitor and the file stocks no monitor, the
    need is still real and is still reported; the deterministic layer decides
    what is available. Asking the model to guess at the stock would make the
    project's meaning depend on what happened to be in the file today.

    The line it must not cross: a need is a **concrete, generic category concept**
    that some catalogue product could plausibly satisfy, and never a specific
    product. So «میز» is a need; «میز گیمینگ ارگونومیک مدل X» is a product
    recommendation, and «تجهیزات» is neither — it names nothing at all.

    There is no field for a slug, a product id, a brand, a model, a seller, an
    offer, a price or a specification: naming one of those would make the model a
    catalogue lookup dressed up as an understanding, and it is the one thing the
    model is not reliable at. ``extra`` is forbidden, so none can be smuggled in
    either.

    ``terms`` is what makes the need resolvable rather than merely eloquent. The
    backend scores those words against the enriched catalogue and gets real
    subcategories back; the model never has to know a slug exists.
    """

    #: what the project needs, said plainly and briefly, for the user to read.
    #: «مبل راحتی» — a need, not «وسایل لازم برای پذیرایی», which names nothing.
    description: str = Field(min_length=1, max_length=200)
    #: The generic words for *what kind of thing* answers it, so the catalogue can
    #: be searched: «میز», «صندلی», «سینک». One or two ordinary nouns.
    #:
    #: Two failure shapes to avoid, and they are opposite. Too abstract
    #: («تجهیزات», «لوازم») resolves to nothing. Too specific
    #: («میز گیمینگ ارگونومیک») is a product recommendation wearing a need's
    #: clothes, and is also unlikely to appear in the file verbatim.
    terms: list[str] = Field(default_factory=list)
    #: how many, when the user actually said. Absent means "as many as the job
    #: needs", which is one.
    quantity: int | None = Field(default=None, ge=1, le=99)
    #: **Core or secondary** — not "indispensable or not".
    #:
    #: This used to mean "the goal is impossible without it", which was a bar no
    #: inferred need could clear: a model asked for a gaming corner, judged every
    #: component short of indispensable, and answered with the bare minimum. The
    #: question is now whether the need is a **core component of the project**
    #: (`True`) or a **secondary one that meaningfully contributes** to it
    #: (`False`) — which is a distinction about the project's scope rather than
    #: about logical necessity, and it is one a model can actually make.
    required: bool = True
    #: the floor the user set for this need, not the project's global one
    quality_min: Quality | None = None

    @field_validator("terms")
    @classmethod
    def _clean_terms(cls, value: list[str]) -> list[str]:
        return [t for t in (v.strip() for v in value) if t][:8]

    @field_validator("description")
    @classmethod
    def _clean_description(cls, value: str) -> str:
        return value.strip()[:200]


class InterpretedIntent(StrictModel):
    intent: Intent
    domain: Domain | None = None
    project_type: ProjectType | None = None
    template_slug: str | None = None
    product_query: ProductQuery | None = None
    requirements: RequirementSpec = Field(default_factory=RequirementSpec)
    constraint_kind: ConstraintKind = ConstraintKind.NONE
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    interpreter: str = "llm"
    explanations: list[str] = Field(default_factory=list)

    #: catalogue subcategories the interpreter matched, already verified against
    #: the catalogue. This is what the project engine looks products up by.
    matched_subcategories: list[str] = Field(default_factory=list)
    #: things a person would expect for this need that the catalogue does not
    #: stock. Reported to the user; never turned into a product.
    missing_categories: list[str] = Field(default_factory=list)
    #: the room the user named, in their own words
    room: str | None = None
    #: the catalogue room this is about, when one could be placed. None means we
    #: could not name a space the catalogue carries — which is a gap in coverage,
    #: not a reason to refuse the project.
    room_token: str | None = None
    #: what the user wants to achieve, in their own words
    goal: str | None = None
    #: What the project needs, in the interpreter's own understanding of the
    #: sentence. **This is the project's requirement list.**
    #:
    #: It used to come from a predefined template, which meant a correct
    #: understanding could be overwritten by whichever rulebook happened to match
    #: a room name — a hall asking for a refrigerator, a bedroom asking for a
    #: sofa. Understanding is the model's job; everything after it is ours.
    project_requirements: list[SemanticRequirement] = Field(default_factory=list)

    @model_validator(mode="after")
    def _sync_domain(self) -> InterpretedIntent:
        if self.domain is None and self.product_query and self.product_query.domain:
            self.domain = self.product_query.domain
        return self


class SearchRouteResponse(BaseModel):
    """
    Where a query should go, decided without a model.

    The whole point of this endpoint is that answering it costs nothing: the
    caller asks it *before* `/search/interpret`, and a ``product`` verdict means
    the query can be answered from the catalogue with no inference at all.

    ``needs_interpretation`` is the field to branch on. The rest is why.
    """

    #: ``product`` — answer from the catalogue, zero inferences.
    #: ``llm`` — the catalogue could not decide; ask the model what is wanted.
    route: Literal["product", "llm"]
    #: the same decision, as a plain boolean
    is_product: bool
    #: the words the catalogue accounted for
    explained: list[str] = Field(default_factory=list)
    #: the words it could not, which is why the model was asked
    unexplained: list[str] = Field(default_factory=list)
    #: a stable machine-readable reason, for logs and for a test to assert on
    reason: str


class InterpretRequest(StrictModel):
    query: str = Field(min_length=2, max_length=MAX_QUERY_LENGTH)


class InterpretResponse(StrictModel):
    intent: Intent
    domain: Domain | None = None
    project_type: ProjectType | None = None
    template_slug: str | None = None
    product_query: ProductQuery | None = None
    requirements: RequirementSpec = Field(default_factory=RequirementSpec)
    constraint_kind: ConstraintKind = ConstraintKind.NONE
    confidence: float
    interpreter: str
    explanations: list[str] = Field(default_factory=list)
    matched_subcategories: list[str] = Field(default_factory=list)
    missing_categories: list[str] = Field(default_factory=list)
    room: str | None = None
    #: the catalogue room this is about, when one could be placed
    room_token: str | None = None
    goal: str | None = None
    #: the project's requirements, as the interpreter understood them
    project_requirements: list[SemanticRequirement] = Field(default_factory=list)

    @classmethod
    def from_intent(cls, intent: InterpretedIntent) -> InterpretResponse:
        return cls(**intent.model_dump())


class BudgetPhrase(StrictModel):
    budget: int = Field(ge=0)
    explanation: str


def budget_explanation(budget: int) -> str:
    return f"بودجه اعلام‌شده: {format_toman(budget)}"
