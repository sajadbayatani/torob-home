"""Project analysis schemas."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import Domain, ProjectType, Quality
from app.domains.catalog.schemas import CategoryOut, ProductOut
from app.domains.search.schemas import InterpretedIntent, StrictModel
from app.domains.sellers.schemas import OfferOut


class ProjectConstraints(StrictModel):
    """User editable knobs for a project analysis."""

    area_m2: float | None = Field(default=None, gt=0, le=1000)
    quality: Quality | None = None
    style: str | None = None
    budget: int | None = Field(default=None, ge=0)
    priorities: list[str] = Field(default_factory=list)


class AnalyzeRequest(StrictModel):
    """
    A project request, either raw or already interpreted.

    ``interpretation`` is the important field. When the caller has already had
    the query interpreted — ``/search/interpret`` did it, or an earlier call in
    the same request chain — passing it here means the model is **not** asked
    again. The query is still required: it is what the analysis is stored against
    and what the user sees later.
    """

    query: str = Field(min_length=2, max_length=500)
    constraints: ProjectConstraints = Field(default_factory=ProjectConstraints)
    #: reuse an existing interpretation instead of inferring one again
    interpretation: InterpretedIntent | None = None


class OptimizeProjectRequest(StrictModel):
    """
    The optimization values exactly as they stand in the form.

    Every field is optional and ``None`` means *the user cleared it*. There is no
    distinction between "omitted" and "cleared" on purpose: this action always
    sends the whole current state, so an absent value is an absent value. The
    backend resolves an absent value to the project's own template default and
    never to a value the user entered earlier — that is the whole point.
    """

    area_m2: float | None = Field(default=None, gt=0, le=1000)
    quality: Quality | None = None
    budget: int | None = Field(default=None, ge=0)
    style: str | None = Field(default=None, max_length=40)


class ProjectOptimizeResponse(BaseModel):
    """
    One optimization: the project as it now stands, and what could change.

    The recommendations and the basket proposals come from the same reasoning
    step, so the two cannot describe different situations.
    """

    analysis: ProjectAnalysisOut
    basket: BasketOut
    budget_status: dict[str, int | float | bool | None] = Field(default_factory=dict)
    optimization: OptimizationResult


class ReanalyzeRequest(StrictModel):
    constraints: ProjectConstraints


#: Shown when the site does not stock the role at all. The requirement stays in
#: the project's needs and is reported as unavailable: the need itself is never in
#: question, only whether we can supply it, so the wording asserts the need and
#: states the unavailability rather than speculating about whether it is wanted.
UNAVAILABLE_NOT_STOCKED = "برای این پروژه لازم است، اما در سایت موجود نیست."

#: Shown when the catalogue does carry the role but records nothing in it as
#: belonging to this room, this kind of job or this space. The requirement is
#: still a real need of the project; the reason it cannot be met is given
#: separately, so the user is never left guessing.
UNAVAILABLE_NOT_SUITABLE = (
    "برای این پروژه لازم است، اما در سایت برای این اتاق یا این نوع کار "
    "موجود نیست."
)

#: Why a need has no recommended product, machine-readable and reported apart from
#: the wording so the user and the interface never have to infer it from a
#: sentence. Only these two are reachable: a product that exists but sits above
#: the project's budget is still a match, and is recommended at its real price.
UNAVAILABLE_REASON_NOT_STOCKED = "not_stocked"
UNAVAILABLE_REASON_NOT_SUITABLE = "not_suitable"


class RecommendedCategory(BaseModel):
    role: str
    label: str
    category: CategoryOut
    quantity: int
    unit: str
    is_required: bool = True
    quality_min: Quality
    reason: str
    #: True for every entry: this row is a need of the project, decided from the
    #: project context alone. It is never withdrawn because we cannot supply it.
    project_need: bool = True
    #: True when the catalogue can actually cover this need. Independent of
    #: project_need: need + no match = an unavailable requirement, which is kept.
    catalog_match: bool = False
    #: kept for existing consumers; always equal to catalog_match
    in_catalog: bool = False
    #: why there is no match, in fixed wording; None when catalog_match is True
    note: str | None = None
    #: machine-readable companion to note: not_stocked, not_suitable or
    #: over_budget. None when catalog_match is True.
    unavailable_reason: str | None = None


class ProjectCandidate(BaseModel):
    role: str
    label: str
    quantity: int
    unit: str
    product: ProductOut
    offer: OfferOut
    unit_price: int
    line_total: int
    seller_name: str
    reason: str
    #: None when the catalogue states no quality for the product
    quality: Quality | None = None
    quality_fa: str | None = None


class ProjectTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name: str
    domain: Domain
    project_type: ProjectType
    description_fa: str | None = None
    requirement_count: int = 0


class ProjectAnalysisOut(BaseModel):
    id: UUID
    #: The matching preset, when there was one. **Null is normal**: a project
    #: described in the user's own words does not have to match a rulebook, and
    #: its requirements come from the interpreter either way.
    template_slug: str | None = None
    title: str
    domain: Domain | None = None
    project_type: ProjectType | None = None
    area_m2: float | None = None
    quality: Quality
    quality_fa: str
    style: str | None = None
    budget: int | None = None
    requirements: ProjectConstraints
    estimated_total: int
    confidence: float
    interpreter: str
    interpretation: InterpretedIntent
    #: How the product reasoning went. "ok" means the model chose from the
    #: candidates it was offered; "not_needed" means there was nothing to choose
    #: between; "failed" means the call did not produce a usable answer and the
    #: recommendations below are the deterministic ones, not a considered result.
    #: Reported separately from the HTTP status so a 200 cannot be read as a
    #: successful analysis.
    reasoning_status: Literal["ok", "not_needed", "failed"] = "not_needed"
    #: every requirement the template asked for
    categories: list[RecommendedCategory] = Field(default_factory=list)
    #: the subcategories of OUR catalogue that are relevant to this project
    available_categories: list[CategoryOut] = Field(default_factory=list)
    candidates: list[ProjectCandidate] = Field(default_factory=list)
    #: products that complete the project rather than satisfy a requirement of
    #: their own. Advice only: the model proposed them, the backend checked each
    #: against the catalogue's declared relationship and the project's room, and
    #: none of them is ever added to the basket.
    complementary: list[ProjectCandidate] = Field(default_factory=list)
    #: needs kept for the project that the catalogue cannot cover
    missing_categories: list[RecommendedCategory] = Field(default_factory=list)
    basket_id: UUID | None = None
    explanations: list[str] = Field(default_factory=list)
    created_at: str


class ProjectAnalyzeResponse(BaseModel):
    analysis: ProjectAnalysisOut
    basket: BasketOut
    budget_status: dict[str, int | bool | None] = Field(default_factory=dict)


# Imported here, not at the top: the basket schemas reach back into this module,
# so a top-level import would be circular.
from app.domains.basket.schemas import BasketOut, OptimizationResult  # noqa: E402

ProjectAnalyzeResponse.model_rebuild()
ProjectOptimizeResponse.model_rebuild()
