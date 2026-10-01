"""Catalog domain schemas (normalised product views)."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import CategoryKind, Domain, Quality
from app.domains.sellers.schemas import OfferOut, SellerOut


class CategoryOut(BaseModel):
    """A catalogue subcategory. ``id`` is the slug, because that is what the
    catalogue file uses and what the filters address."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    name: str
    domain: Domain
    kind: CategoryKind
    description_fa: str | None = None
    product_count: int = 0


class BrandOut(BaseModel):
    """A brand. The catalogue stores only the Persian name it found in the title."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    name: str
    name_en: str | None = None
    country: str | None = None


class AttributeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    label: str
    value: str
    value_num: Decimal | None = None
    unit: str | None = None


class ProductOut(BaseModel):
    """Normalised product projection used by search and product detail.

    `quality`, `quality_fa`, `style`, `unit`, `warranty_months`, `rating`,
    `origin_country` and `description` are all **nullable**: the catalogue does
    not record them, and the API never invents a value. The UI hides whatever is
    null instead of showing a fabricated zero.
    """

    id: UUID
    slug: str
    name: str
    subtitle: str | None = None
    brand: BrandOut | None = None
    category: CategoryOut
    domain: Domain
    #: catalogue fields, exactly as the file holds them
    subcategory: str = ""
    model: str | None = None
    image_url: str | None = None
    source_url: str | None = None
    #: absent from the catalogue
    quality: Quality | None = None
    quality_fa: str | None = None
    style: str | None = None
    unit: str | None = None
    rating: Decimal | None = None
    warranty_months: int | None = None
    origin_country: str | None = None
    attributes: list[AttributeOut] = Field(default_factory=list)
    offers: list[OfferOut] = Field(default_factory=list)
    offers_count: int = 0
    min_price: int | None = None
    max_price: int | None = None
    available_offers_count: int = 0
    is_demo: bool = False
    match_score: float | None = None


class ProductDetail(ProductOut):
    description: str | None = None
    reference_price: int | None = None


class SimilarProduct(BaseModel):
    """A product of the same kind, chosen deterministically from the catalogue."""

    product: ProductOut
    #: "same_subcategory", "same_brand" or "same_category"
    match_type: str
    reason: str


class ComplementaryProduct(BaseModel):
    """
    A complementary product.

    ``product_id`` is the id the backend validated against the catalogue. The
    frontend only ever sees the validated projection, so an id the model invented
    can never reach the browser.
    """

    product_id: UUID
    product: ProductOut
    reason: str
    #: "llm" when the model chose it, "heuristic" when the catalogue pairings did
    source: str


class ComplementaryResponse(BaseModel):
    """The response for the complementary-products endpoint."""

    items: list[ComplementaryProduct] = Field(default_factory=list)
    #: whether an LLM was available for this answer
    llm_available: bool
    #: how many catalogue products the model was allowed to choose from
    candidate_count: int
    #: shown to the user when the list is empty or degraded
    note: str | None = None
    #: ids the model returned that are not in the catalogue, and were dropped
    discarded_ids: list[str] = Field(default_factory=list)


class ProductSearchItem(BaseModel):
    product: ProductOut
    matched_terms: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class FacetValue(BaseModel):
    value: str
    label: str
    count: int


class Facets(BaseModel):
    """Filter options, counted from the catalogue.

    There is no ``qualities`` facet: the catalogue records no quality.
    """

    categories: list[FacetValue] = Field(default_factory=list)
    brands: list[FacetValue] = Field(default_factory=list)
    subcategories: list[FacetValue] = Field(default_factory=list)


class ProductSearchResponse(BaseModel):
    query: str
    total: int
    limit: int
    offset: int
    detected_category: str | None = None
    #: The human label for `detected_category`, so a result list can name the
    #: category it detected. It used to get this from the interpreter's
    #: `category_name`, which a deterministically routed search does not have — a
    #: search answered without an inference must still read like one.
    detected_category_name: str | None = None
    detected_domain: Domain | None = None
    intent: str | None = None
    items: list[ProductSearchItem] = Field(default_factory=list)
    facets: Facets = Field(default_factory=Facets)
    explanations: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


__all__ = [
    "BrandOut",
    "ComplementaryProduct",
    "ComplementaryResponse",
    "SimilarProduct",
    "CategoryOut",
    "AttributeOut",
    "Facets",
    "FacetValue",
    "OfferOut",
    "ProductDetail",
    "ProductOut",
    "ProductSearchItem",
    "ProductSearchResponse",
    "SellerOut",
]
