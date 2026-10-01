"""Shared domain vocabulary.

These enums are the contract between the API, the database and the frontend.
Money is always an integer amount of **Toman** (تومان).
"""

from __future__ import annotations

from enum import StrEnum


class Intent(StrEnum):
    """The two supported user intents (deliberately only two in v0.1)."""

    PRODUCT_SEARCH = "PRODUCT_SEARCH"
    NEED_SEARCH = "NEED_SEARCH"
    UNKNOWN = "UNKNOWN"


class Domain(StrEnum):
    """Top-level catalogue categories, exactly as the catalogue names them."""

    APPLIANCE = "appliance"
    BATHROOM = "bathroom"
    FURNITURE = "furniture"
    KITCHEN = "kitchen"


#: The enriched catalogue spells the appliance category in the plural. The data
#: is taken as it is, so the vocabulary folds the two spellings together here
#: rather than the file being rewritten.
DOMAIN_ALIASES: dict[str, str] = {"appliances": Domain.APPLIANCE.value}


def domain_from(value: str) -> Domain | None:
    """The domain a catalogue category names, or None if it names nothing we know."""
    folded = DOMAIN_ALIASES.get(value, value)
    try:
        return Domain(folded)
    except ValueError:
        return None


class ProjectType(StrEnum):
    RENOVATION = "renovation"
    NEW_BUILD = "new_build"
    REDESIGN = "redesign"
    REPAIR = "repair"


class ReasoningEffort(StrEnum):
    """
    How much a reasoning model should think before answering.

    The values OpenRouter documents for ``reasoning.effort``, and nothing else:
    the set is closed here so a typo in the environment is caught at startup
    rather than sent to the provider and rejected there with a message about a
    request this application did not know was malformed.

    It is an enum and not a free string for the same reason :class:`Quality` is —
    the value is sent to someone else's API, so what we accept and what they
    accept must not drift apart silently.
    """

    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Quality(StrEnum):
    """Ordered quality ladder. Higher is better; used for budget trade-offs."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    ULTRA = "ultra"

    @property
    def rank(self) -> int:
        return _QUALITY_RANK[self]

    @classmethod
    def from_rank(cls, rank: int) -> Quality:
        return _RANK_QUALITY[max(0, min(len(_RANK_QUALITY) - 1, rank))]


_QUALITY_RANK: dict[Quality, int] = {
    Quality.LOW: 0,
    Quality.MEDIUM: 1,
    Quality.HIGH: 2,
    Quality.ULTRA: 3,
}
_RANK_QUALITY = {v: k for k, v in _QUALITY_RANK.items()}

QUALITY_FA: dict[Quality, str] = {
    Quality.LOW: "اقتصادی",
    Quality.MEDIUM: "متوسط",
    Quality.HIGH: "بالا",
    Quality.ULTRA: "لوکس",
}

STYLE_FA: dict[str, str] = {
    "modern": "مدرن",
    "classic": "کلاسیک",
    "minimal": "مینیمال",
    "industrial": "صنعتی",
}


class Availability(StrEnum):
    IN_STOCK = "in_stock"
    LOW_STOCK = "low_stock"
    PREORDER = "preorder"
    OUT_OF_STOCK = "out_of_stock"

    @property
    def is_purchasable(self) -> bool:
        return self is not Availability.OUT_OF_STOCK


class CategoryKind(StrEnum):
    FIXTURE = "fixture"
    SURFACE = "surface"
    ACCESSORY = "accessory"
    MATERIAL = "material"
    APPLIANCE = "appliance"
    LIGHTING = "lighting"
    HARDWARE = "hardware"


class RelationType(StrEnum):
    """Explicit catalog relationships driving contextual recommendations."""

    #: same subcategory / same top-level category. The catalogue records no
    #: compatibility claims, so this is the only relation it can support.
    SAME_KIND = "same_kind"
    INSTALL_KIT = "install_kit"
    COMPATIBLE_FITTING = "compatible_fitting"
    REQUIRED_MATERIAL = "required_material"
    ACCESSORY_PAIR = "accessory_pair"
    ROOM_PAIR = "room_pair"
    ALTERNATIVE = "alternative"


class QuantityMode(StrEnum):
    PER_AREA = "per_area"
    FIXED = "fixed"


class BasketKind(StrEnum):
    PRODUCT = "product"
    PROJECT = "project"
    RELATED = "related"


class ItemOrigin(StrEnum):
    SEARCH = "search"
    PROJECT = "project"
    RELATED = "related"
    OPTIMIZATION = "optimization"
    MANUAL = "manual"


class DataSource(StrEnum):
    """Marks data provenance.

    ``CATALOG`` is the captured Torob catalogue in ``data/catalog/products.json``,
    which is what the API now serves. ``SEED`` covers the remaining reference data
    (project templates and need rules), which is still invented for the demo.
    """

    CATALOG = "catalog"
    SEED = "seed"
    CRAWL = "crawl"
    MANUAL = "manual"
