"""The product catalogue: `data/catalog/products.json`, owned by the backend.

This module is the **single source of truth** for products, sellers, prices and
products. It reads the JSON file from the filesystem, validates every
record, and answers the queries the API needs. There is no product table and no
seeded product data any more.

Design notes:

* **Nothing is invented.** A record that cannot be trusted is dropped and the
  reason is recorded, rather than being patched up. A field the file does not
  carry stays ``None`` all the way to the response, so the UI can hide it instead
  of showing a fabricated zero.
* **The file is re-read when it changes**, keyed on its mtime and size. Running
  ``make catalog`` is picked up without restarting the API.
* **No session, no ORM.** Everything here is plain Python, which keeps the
  catalogue independent of the database that still stores baskets, projects and
  the interpreter's reference data.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Mapping
from typing import Any, Iterator
from uuid import UUID

from app.core.config import get_settings

# Persian text is folded in exactly one place — `app.core.text` — so search, the
# interpreter and the catalogue can never disagree about what a term means.
from app.core.text import normalize_persian, tokenize


def fa_tokens(value: str | None) -> list[str]:
    return [token for token in tokenize(value or "") if token]


# --------------------------------------------------------------------------- #
# Presentation labels
#
# These are labels for the catalogue's own vocabulary, not product data: the
# subcategory slugs and attribute keys are fixed by `build_catalog.py`, and the
# UI needs a Persian label and unit for each.
# --------------------------------------------------------------------------- #

SUBCATEGORY_LABELS: dict[str, str] = {
    "dishwasher": "ماشین ظرفشویی",
    "microwave": "مایکروویو",
    "refrigerator": "یخچال و فریزر",
    "television": "تلویزیون",
    "vacuum-cleaner": "جاروبرقی",
    "washing-machine": "ماشین لباسشویی",
    "bathroom-mirror": "آینه سرویس بهداشتی",
    "sink": "روشویی",
    "sink-faucet": "شیر روشویی",
    "toilet": "توالت",
    "toilet-faucet": "شیر توالت",
    "bed": "تخت خواب",
    "desk": "میز",
    "dining-chair": "صندلی ناهارخوری",
    "dining-table": "میز ناهارخوری",
    "sofa": "مبل راحتی",
    "wardrobe": "کمد",
    "built-in-oven": "فر توکار",
    "cooktop": "اجاق گاز",
    "kitchen-faucet": "شیر آشپزخانه",
    "kitchen-hood": "هود آشپزخانه",
    "kitchen-sink": "سینک آشپزخانه",
}

CATEGORY_LABELS: dict[str, str] = {
    "appliance": "لوازم برقی",
    "bathroom": "سرویس بهداشتی",
    "furniture": "مبلمان",
    "kitchen": "آشپزخانه",
}

#: The enriched file spells the appliance category in the plural ("appliances")
#: while the public vocabulary is singular. Both spellings used to be listed here,
#: which made the label table the second place the mapping lived and left the
#: filter broken in both directions: ``domain=appliance`` matched nothing, because
#: the file stores the plural, and the plural was not a value the enum accepted.
#: The folding happens once, in :func:`canonical_category`, and this table holds
#: only what the API actually speaks.

ATTRIBUTE_LABELS: dict[str, tuple[str, str | None]] = {
    "capacity_feet": ("ظرفیت", "فوت"),
    "capacity_kg": ("ظرفیت", "کیلوگرم"),
    "capacity_liters": ("ظرفیت", "لیتر"),
    "capacity_place_settings": ("ظرفیت", "نفره"),
    "burner_count": ("تعداد شعله", "شعله"),
    "seat_count": ("ظرفیت", "نفره"),
    "size_inch": ("اندازهٔ صفحه", "اینچ"),
    "dimensions_cm": ("ابعاد", "سانتی‌متر"),
    "color": ("رنگ", None),
    "door_type": ("نوع درب", None),
    "installation": ("نوع نصب", None),
}


def subcategory_label(slug: str) -> str:
    return SUBCATEGORY_LABELS.get(slug, slug)


def canonical_category(value: str | None) -> str | None:
    """
    A catalogue category in the vocabulary the API speaks.

    The file is the source of truth and is taken as it is, so "appliances" stays
    "appliances" in the file. Everywhere the value crosses into the API — a
    facet, ``detected_domain``, a ``domain=`` filter — it goes through here, so
    there is exactly one spelling of each category in circulation and the two can
    never be compared against each other.

    The folding is delegated to the domain vocabulary rather than repeated, so the
    enum stays the single place the public category names are declared. A category
    the vocabulary does not know is returned unchanged: the file may name one we
    have not added yet, and dropping it would hide products that exist.
    """
    if not value:
        return None
    from app.core.enums import domain_from

    domain = domain_from(value)
    return domain.value if domain else value


def category_label(slug: str) -> str:
    return CATEGORY_LABELS.get(canonical_category(slug) or "", slug)


# --------------------------------------------------------------------------- #
# In-memory model
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CatalogAttribute:
    key: str
    label: str
    value: str
    value_num: float | int | None
    unit: str | None


@dataclass(frozen=True)
class CatalogSeller:
    """A seller, as the catalogue records it."""

    id: str
    name: str
    city: str | None


@dataclass(frozen=True)
class CatalogOffer:
    """One seller offer. The catalogue keeps at most five per product."""

    id: UUID
    seller: CatalogSeller
    price: int
    available: bool
    url: str | None
    price_updated_at: str | None
    is_price_unreliable: bool
    guarantee_status: str | None

    @property
    def availability(self) -> str:
        return "in_stock" if self.available else "out_of_stock"


@dataclass(frozen=True)
class CatalogProduct:
    """A catalogue product. Absent fields are ``None``, never defaulted."""

    id: UUID
    name: str
    category: str
    subcategory: str
    brand: str | None
    model: str | None
    #: ``None`` when the source stated no image. The local file always carries
    #: one — the loader rejects a record without it — but Torob's search result
    #: has no image field at all, and inventing one is not an option.
    image_url: str | None
    source_name: str
    source_url: str | None
    lowest_price_toman: int
    attributes: tuple[CatalogAttribute, ...]
    offers: tuple[CatalogOffer, ...]
    #: the enriched catalogue's own block (rooms, roles, use cases, ...), kept
    #: verbatim. Nothing derives from it; it is carried, not interpreted.
    metadata: Mapping[str, Any] = field(default_factory=dict)

    # --- derived, always from the file -------------------------------------
    @property
    def category_name(self) -> str:
        return category_label(self.category)

    @property
    def subcategory_name(self) -> str:
        return subcategory_label(self.subcategory)

    @property
    def min_price(self) -> int:
        return self.lowest_price_toman

    @property
    def purchasable_min_price(self) -> int | None:
        """
        The cheapest price a shopper can actually pay for this product.

        ``min_price`` is the file's headline figure, which may come from an offer
        that is unavailable or flagged unreliable. A budget has to be checked
        against a price someone can pay, so this reads the offers that are both
        available and trustworthy, and returns ``None`` when the file offers
        nothing buyable — which is a different answer from "free", and is treated
        as such: a product with nothing to buy cannot satisfy a ceiling.
        """
        buyable = [
            offer
            for offer in self.purchasable_offers
            if offer.available and not offer.is_price_unreliable
        ]
        return min((offer.price for offer in buyable), default=None)

    @property
    def max_price(self) -> int | None:
        return max((offer.price for offer in self.offers), default=None)

    @property
    def offers_count(self) -> int:
        return len(self.offers)

    @property
    def available_offers_count(self) -> int:
        return sum(1 for offer in self.offers if offer.available)

    @property
    def purchasable_offers(self) -> tuple[CatalogOffer, ...]:
        """Available offers, cheapest first, doubtful prices ranked last."""
        return tuple(
            sorted(self.offers, key=lambda o: (not o.available, o.is_price_unreliable, o.price))
        )

    def purchasable(self) -> tuple[CatalogOffer, ...]:
        return tuple(offer for offer in self.purchasable_offers if offer.available)

    def search_haystack(self) -> str:
        parts = [self.name, self.subcategory_name, self.category_name]
        if self.brand:
            parts.append(self.brand)
        if self.model:
            parts.append(self.model)
        return normalize_persian(" ".join(parts))


@dataclass(frozen=True)
class CatalogMatch:
    product: CatalogProduct
    matched_terms: tuple[str, ...]
    reasons: tuple[str, ...]
    score: int


@dataclass(frozen=True)
class SkippedRecord:
    name: str
    reason: str


#: How much a word counts, by the place in the file it was found. The label is
#: the shop's canonical name for the subcategory and a search term is something
#: the file offers deliberately as a way in; a product name or a feature is
#: incidental context. The scale matters, not the arithmetic.
VOCAB_WEIGHT_FEATURE = 1
VOCAB_WEIGHT_NAME = 2
VOCAB_WEIGHT_SEARCH_TERM = 3
VOCAB_WEIGHT_LABEL = 4


@dataclass(frozen=True)
class SubcategoryVocabulary:
    """
    Every way the file refers to one subcategory, reduced to words.

    ``tokens`` maps a word to the strongest weight it was ever seen at, so a
    word the label uses outranks the same word appearing inside one product's
    name. ``phrases`` holds the whole strings — a requirement that matches one
    exactly is the file naming the thing itself, and needs no further evidence.
    """

    slug: str
    tokens: Mapping[str, int]
    phrases: frozenset[str]


def _feature_words(features) -> list[str]:
    """
    The words a ``features`` list contributes.

    The file writes features as ``kind:value`` ("brand:اخوان", "model:نیکا"), so
    the value is what carries a name worth matching. Only the Persian part is
    taken: a feature like "black_color" is a tag the file uses to filter, not a
    word a shopper would ever type, and indexing it would let a product match a
    requirement on the strength of a word that is not part of its name.
    """
    words: list[str] = []
    for feature in features or ():
        value = str(feature).split(":", 1)[-1] if ":" in str(feature) else str(feature)
        if not _PERSIAN_WORD.search(value):
            continue
        words.extend(fa_tokens(value))
    return words


_PERSIAN_WORD = re.compile(r"[\u0600-\u06ff]")


def _build_vocabulary(
    index: "CatalogIndex",
) -> "dict[str, SubcategoryVocabulary]":
    """
    Group the file's words by subcategory, and count how shared each word is.

    The shared count is what makes a generic word harmless. "مبلمان" is the
    category label of every furniture subcategory, so it is measured as evidence
    for all of them and therefore for none; "مبل" is used only by sofas, so it
    decides. Both facts come out of the file, so neither is a rule written here.
    """
    tokens: dict[str, dict[str, int]] = {}
    phrases: dict[str, set[str]] = {}
    frequency: dict[str, int] = {}

    def offer(slug: str, words, weight: int) -> None:
        seen = tokens.setdefault(slug, {})
        for word in words:
            if not word:
                continue
            if weight > seen.get(word, 0):
                seen[word] = weight

    for slug in sorted({product.subcategory for product in index.products}):
        products = index.subcategories_of(slug)
        if not products:
            continue
        label = index.subcategory_label(slug)
        offer(slug, fa_tokens(label), VOCAB_WEIGHT_LABEL)
        for product in products:
            offer(slug, fa_tokens(product.name), VOCAB_WEIGHT_NAME)
            for term in product.metadata.get("search_terms") or ():
                folded = normalize_persian(str(term))
                if not folded:
                    continue
                phrases.setdefault(slug, set()).add(folded)
                offer(slug, fa_tokens(folded), VOCAB_WEIGHT_SEARCH_TERM)
            offer(
                slug,
                _feature_words(product.metadata.get("features")),
                VOCAB_WEIGHT_FEATURE,
            )
        # the label is itself a phrase the file offers
        phrases.setdefault(slug, set()).add(normalize_persian(label))

    for slug, words in tokens.items():
        for word in words:
            frequency[word] = frequency.get(word, 0) + 1

    vocabulary = {
        slug: SubcategoryVocabulary(
            slug=slug, tokens=dict(words), phrases=frozenset(phrases.get(slug, ()))
        )
        for slug, words in tokens.items()
    }
    index._vocabulary_frequency = frequency
    return vocabulary


@dataclass
class CatalogIndex:
    """A validated, indexed view of one read of the file."""

    products: list[CatalogProduct] = field(default_factory=list)
    by_id: dict[UUID, CatalogProduct] = field(default_factory=dict)
    skipped: list[SkippedRecord] = field(default_factory=list)
    source: Path | None = None
    error: str | None = None
    #: derived from `products`, built on first use and kept for the life of this
    #: index. Not part of the value: two indexes over the same products are equal.
    _vocabulary: "dict[str, SubcategoryVocabulary] | None" = field(
        default=None, repr=False, compare=False
    )
    _vocabulary_frequency: "dict[str, int]" = field(
        default_factory=dict, repr=False, compare=False
    )
    _brands: frozenset[str] | None = field(default=None, repr=False, compare=False)

    def __len__(self) -> int:
        return len(self.products)

    def get(self, product_id: UUID | str) -> CatalogProduct | None:
        try:
            key = UUID(str(product_id))
        except (ValueError, AttributeError, TypeError):
            return None
        return self.by_id.get(key)

    def subcategories(self) -> list[tuple[str, int]]:
        counts: dict[str, int] = {}
        for product in self.products:
            counts[product.subcategory] = counts.get(product.subcategory, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], subcategory_label(kv[0])))

    def brands(self) -> list[tuple[str, int]]:
        counts: dict[str, int] = {}
        for product in self.products:
            if product.brand:
                counts[product.brand] = counts.get(product.brand, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

    def categories(self) -> list[tuple[str, int]]:
        """Top-level categories and their counts, in the API's spelling.

        Counted in the file's own spelling and then folded, so a category the file
        writes differently from the API is neither split into two facets nor
        reported under a name no caller can filter by.
        """
        counts: dict[str, int] = {}
        for product in self.products:
            key = canonical_category(product.category) or product.category
            counts[key] = counts.get(key, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], category_label(kv[0])))

    def subcategory_slugs(self) -> set[str]:
        return {product.subcategory for product in self.products}

    def subcategory_label(self, subcategory: str) -> str:
        return subcategory_label(subcategory)

    def top_category_of(self, subcategory: str) -> str | None:
        for product in self.products:
            if product.subcategory == subcategory:
                return product.category
        return None

    def subcategories_of(self, subcategory: str) -> list[CatalogProduct]:
        return [p for p in self.products if p.subcategory == subcategory]

    def iter_subcategory(self, subcategory: str) -> Iterator[CatalogProduct]:
        return (p for p in self.products if p.subcategory == subcategory)

    def iter_category(self, category: str) -> Iterator[CatalogProduct]:
        return (p for p in self.products if p.category == category)

    def brand_tokens(self) -> frozenset[str]:
        """
        Every word the file uses as part of a brand or model name.

        Collected so a brand can be told apart from a kind of thing. A brand is
        not a category: «دوو» makes washing machines, refrigerators and vacuums,
        so a query naming one is asking for a maker, not for a kind of product,
        and a brand on its own must not decide which subcategory is meant. The
        file already separates the two — ``brand`` and ``model`` are their own
        columns — so this reads them rather than knowing any brand name.
        """
        if self._brands is None:
            words: set[str] = set()
            for product in self.products:
                for value in (product.brand, product.model):
                    if value:
                        words.update(fa_tokens(value))
            self._brands = frozenset(words)
        return self._brands

    def subcategory_vocabulary(self) -> Mapping[str, "SubcategoryVocabulary"]:
        """
        What the file itself calls each subcategory, as comparable tokens.

        Built once per read of the file and cached, because a project resolves
        every one of its requirements against it.

        The point of tokenising here rather than searching a joined string is
        that a subcategory's own name is not the only way the file refers to it:
        a shop lists the same thing as "تخت خواب", "تخت" and "نیکا". Collecting
        them all as *words* is what lets an unseen phrase reach the subcategory
        the model meant, without anything in this code knowing what a bed is.
        """
        if self._vocabulary is None:
            self._vocabulary = _build_vocabulary(self)
        return self._vocabulary

    def token_document_frequency(self) -> Mapping[str, int]:
        """
        How many subcategories use each word.

        A word every subcategory uses says nothing about which one is meant.
        "مبلمان" is the category label on all eight furniture subcategories, so
        it cannot distinguish a sofa from a bed — and treating it as evidence
        that a sofa was asked for is how a sofa requirement came to be answered
        with a bed. The frequency is measured from the file rather than listed,
        so a word stops being decisive the moment the shop stops using it
        everywhere.
        """
        if self._vocabulary is None:
            self._vocabulary = _build_vocabulary(self)
        return self._vocabulary_frequency


# --------------------------------------------------------------------------- #
# Reading and validating the file
# --------------------------------------------------------------------------- #

REJECTION_REASONS: dict[str, str] = {
    "not_an_object": "ردیف یک شیء نیست",
    "missing_id": "شناسهٔ محصول وجود ندارد",
    "invalid_id": "شناسهٔ محصول معتبر نیست",
    "missing_name": "نام محصول وجود ندارد",
    "missing_or_invalid_price": "قیمت معتبر نیست",
    "missing_or_invalid_image": "تصویر معتبر نیست",
    "missing_category": "دستهٔ محصول وجود ندارد",
}


class CatalogError(RuntimeError):
    """The catalogue file could not be used at all."""

    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _metadata_from(raw: Any) -> Mapping[str, Any]:
    """
    The enriched catalogue's per-product block, taken as it is.

    Stored verbatim and read by nothing: the catalogue's job here is to be the
    canonical data, and inventing defaults for a field the file happens to have
    would be second-guessing it.
    """
    return dict(raw) if isinstance(raw, dict) else {}


def resolve_catalog_path(path: str | Path | None = None) -> Path:
    """
    Resolve the catalogue file, relative to the backend package if needed.

    Settings are read at call time rather than captured at import, so a
    ``CATALOG_PATH`` change takes effect without reimporting the module.
    """
    raw = Path(path or get_settings().catalog_path)
    if raw.is_absolute():
        return raw
    # app/core/config.py -> backend/
    backend_root = Path(__file__).resolve().parent.parent
    candidates = [backend_root / raw, backend_root.parent / raw, Path.cwd() / raw]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return candidates[0].resolve()


def _offer_from(entry: Any) -> CatalogOffer | None:
    if not isinstance(entry, dict):
        return None
    price = entry.get("price")
    if not isinstance(price, int) or isinstance(price, bool) or price <= 0:
        # an unavailable seller is not an offer
        return None
    raw_id = entry.get("prk")
    if not isinstance(raw_id, str) or not raw_id:
        shop_id = entry.get("shop_id")
        raw_id = str(shop_id) if shop_id not in (None, "") else ""
    try:
        offer_id = UUID(raw_id)
    except (ValueError, AttributeError, TypeError):
        shop_id = entry.get("shop_id")
        if shop_id in (None, ""):
            return None
        # a stable UUID for a seller row that has no prk of its own
        offer_id = UUID(int=abs(hash(str(shop_id))) % (1 << 128))
    guarantee = entry.get("guarantee_info")
    return CatalogOffer(
        id=offer_id,
        seller=CatalogSeller(
            id=str(entry.get("shop_id") or ""),
            name=str(entry.get("shop_name") or ""),
            city=str(entry["shop_name2"]) if entry.get("shop_name2") else None,
        ),
        price=price,
        available=entry.get("availability") is True,
        url=str(entry["page_url"]) if entry.get("page_url") else None,
        price_updated_at=(
            str(entry["last_price_change_date"]) if entry.get("last_price_change_date") else None
        ),
        is_price_unreliable=entry.get("is_price_unreliable") is True,
        guarantee_status=(
            str(guarantee["status"]) if isinstance(guarantee, dict) and guarantee.get("status") else None
        ),
    )


def _attributes_from(raw: Any) -> tuple[CatalogAttribute, ...]:
    if not isinstance(raw, dict):
        return ()
    out: list[CatalogAttribute] = []
    for key, value in raw.items():
        meta = ATTRIBUTE_LABELS.get(key)
        if meta is None:
            # an unknown key gets no invented label
            continue
        label, unit = meta
        out.append(
            CatalogAttribute(
                key=key,
                label=label,
                value=str(value),
                value_num=value if isinstance(value, (int, float)) and not isinstance(value, bool) else None,
                unit=unit,
            )
        )
    return tuple(out)


def _product_from(entry: Any) -> tuple[CatalogProduct | None, str | None]:
    if not isinstance(entry, dict):
        return None, "not_an_object"
    raw_id = entry.get("id")
    if not isinstance(raw_id, str) or not raw_id.strip():
        return None, "missing_id"
    try:
        product_id = UUID(raw_id.strip())
    except (ValueError, AttributeError):
        return None, "invalid_id"
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        return None, "missing_name"
    price = entry.get("lowest_price_toman")
    if not isinstance(price, int) or isinstance(price, bool) or price <= 0:
        return None, "missing_or_invalid_price"
    image = entry.get("image_url")
    if not isinstance(image, str) or not image.startswith("http"):
        return None, "missing_or_invalid_image"
    category = entry.get("category")
    if not isinstance(category, str) or not category.strip():
        return None, "missing_category"
    subcategory = entry.get("subcategory")
    if not isinstance(subcategory, str) or not subcategory.strip():
        subcategory = category
    source = entry.get("source") if isinstance(entry.get("source"), dict) else {}
    offers = [
        offer
        for offer in (_offer_from(raw) for raw in (entry.get("offers") or []))
        if offer is not None
    ]
    # keep the file's own order: it is already cheapest-first with doubtful
    # prices ranked last
    return (
        CatalogProduct(
            id=product_id,
            name=name.strip(),
            category=category.strip(),
            subcategory=subcategory.strip(),
            brand=str(entry["brand"]) if entry.get("brand") else None,
            model=str(entry["model"]) if entry.get("model") else None,
            image_url=image,
            source_name=str(source.get("name") or "torob"),
            source_url=str(source["url"]) if source.get("url") else None,
            lowest_price_toman=price,
            attributes=_attributes_from(entry.get("attributes")),
            offers=tuple(offers),
            metadata=_metadata_from(entry.get("metadata")),
        ),
        None,
    )


def build_index(payload: Any, source: Path | None = None) -> CatalogIndex:
    """Validate a parsed catalogue payload into an index."""
    if not isinstance(payload, list):
        raise CatalogError("ساختار فایل کاتالوگ درست نیست.", 500)
    index = CatalogIndex(source=source)
    for position, entry in enumerate(payload):
        product, reason = _product_from(entry)
        if product is None:
            name = entry.get("name") if isinstance(entry, dict) else None
            index.skipped.append(
                SkippedRecord(
                    name=str(name)[:60] if isinstance(name, str) and name else f"ردیف {position + 1}",
                    reason=reason or "unknown",
                )
            )
            continue
        if product.id in index.by_id:
            index.skipped.append(SkippedRecord(name=product.name, reason="duplicate_id"))
            continue
        index.products.append(product)
        index.by_id[product.id] = product
    return index


def read_index(path: Path) -> CatalogIndex:
    """Read and validate the file, or raise `CatalogError`."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise CatalogError(
            f"فایل کاتالوگ پیدا نشد: {path}. با «make catalog» آن را بسازید.", 500
        ) from exc
    except OSError as exc:
        raise CatalogError(f"خواندن فایل کاتالوگ ممکن نشد: {exc}", 500) from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CatalogError(f"فایل کاتالوگ خراب است و خوانده نشد: {exc}", 500) from exc
    return build_index(payload, source=path)


# --------------------------------------------------------------------------- #
# Cached access
# --------------------------------------------------------------------------- #

_lock = threading.Lock()
_cache: CatalogIndex | None = None
_cache_stamp: tuple[float, int] | None = None
_cache_path: Path | None = None


def _stamp(path: Path) -> tuple[float, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime, stat.st_size)


def get_catalog(*, refresh: bool = False, path: str | Path | None = None) -> CatalogIndex:
    """The catalogue, re-read when the file changes.

    This is the only entry point the rest of the backend uses.
    """
    global _cache, _cache_stamp, _cache_path
    resolved = resolve_catalog_path(path)
    with _lock:
        stamp = _stamp(resolved)
        if (
            not refresh
            and _cache is not None
            and _cache_path == resolved
            and stamp is not None
            and stamp == _cache_stamp
        ):
            return _cache
        index = read_index(resolved)
        _cache = index
        _cache_stamp = stamp
        _cache_path = resolved
        return index


#: Every word the file uses, keyed by the identity of the index it was read
#: from. Held beside the index cache it belongs with, and cleared with it, so a
#: re-read of the file can never be answered from a stale vocabulary.
_file_words: dict[int, frozenset[str]] = {}


def reset_cache() -> None:
    """Drop the cached read. Used by tests and after a rebuild."""
    global _cache, _cache_stamp, _cache_path
    with _lock:
        _cache = None
        _cache_stamp = None
        _cache_path = None
        _file_words.clear()


# --------------------------------------------------------------------------- #
# Queries
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CatalogFilters:
    category: str | None = None  # subcategory slug
    top_category: str | None = None
    brand: str | None = None
    only_available: bool = False
    #: an upper bound on what the shopper will pay, in Toman. Applied to the
    #: cheapest price the product can actually be bought at, never to the file's
    #: headline figure.
    max_price: int | None = None


def _score_match(
    product: CatalogProduct, terms: list[str]
) -> tuple[list[str], list[str], int] | None:
    """Score one product against the query terms, or return None if it misses.

    Terms are matched as **whole words**, not as substrings. A substring test
    reads «تا» inside «تانیا» and «یه» inside «پایه», so a query carrying those
    words matched sinks, desks and chairs that have nothing to do with what was
    asked for — and because a single stray hit was enough to return a product,
    those false positives outnumbered the real answers. Persian attaches
    possessives and clitics to the stem (*ماشینم*, *ماشین‌ها*), which a whole-word
    test tolerates and a substring test both misses and over-matches.
    """
    name = normalize_persian(product.name)
    brand = normalize_persian(product.brand) if product.brand else ""
    subcategory = normalize_persian(product.subcategory_name)
    category = normalize_persian(product.category_name)

    matched: list[str] = []
    reasons: list[str] = []
    score = 0
    for term in terms:
        hit = False
        if _has_word(name, term):
            hit = True
            score += 12 if name.startswith(term) else 8
            if not any("نام" in reason for reason in reasons):
                reasons.append(f"نام محصول شامل «{term}» است.")
        if not hit and brand and _has_word(brand, term):
            hit = True
            score += 6
            reasons.append(f"برند «{product.brand}» شامل «{term}» است.")
        if not hit and _has_word(subcategory, term):
            hit = True
            score += 5
            reasons.append(f"دستهٔ «{product.subcategory_name}» شامل «{term}» است.")
        if not hit and _has_word(category, term):
            hit = True
            score += 3
            reasons.append(f"دسته‌بندی شامل «{term}» است.")
        if hit:
            matched.append(term)
    if not matched:
        return None
    # every term matching beats one term matching
    score += 6 if len(matched) == len(terms) else 0
    return matched, reasons, score


def _has_word(text: str, term: str) -> bool:
    """
    Whether ``text`` contains ``term`` as a standalone word.

    Compared on tokens, so «ماشین» is found in «ماشین لباسشویی» and in
    «ماشین‌های»، and is *not* found in «ماشین‌چین». The file is folded once, the
    same way search text is, so a word is never compared in two spellings.
    """
    if not term:
        return False
    return term in set(fa_tokens(text))


def evidence_terms(query: str, index: CatalogIndex | None = None) -> list[str]:
    """
    The words of a query that may stand as evidence that a product is wanted.

    Three kinds of word are dropped, and none of them can decide a match:

    * **filler** — the clitics, prepositions and politeness in the routing
      matcher's closed list, which name nothing in the shop;
    * **quantities** — a bare number is a size, a capacity or a count, and is
      handled by the filters rather than by matching it against a title;
    * **money** — «تومن» and its scales are a unit, and become a budget.

    And then, given the catalogue, a fourth kind is dropped for a reason that
    needs no list at all: **any word the file never uses**. It cannot match a
    product, so letting it stand as evidence could only ever inflate the count of
    matched terms and the "matched everything" bonus. This is what stops a
    search verb like «دنبال» or «میگردم» from being treated as something to look
    for, without those words having to be enumerated here — and it holds for a
    filler word nobody thought of. The closed list stays, because some words *are*
    used in the file while naming nothing (*خوب*, *ارزان*), and only the file can
    tell those apart from a brand or a model.

    What is left is a word that names something the shop sells. A query
    consisting only of dropped words yields nothing here, and is then answered by
    the structured constraints alone if there are any, and with no results if
    there are not.
    """
    from app.catalog.matcher import _NOT_PRODUCT_WORDS
    from app.core.text import MONEY_WORDS

    money = set(MONEY_WORDS)
    terms: list[str] = []
    for token in fa_tokens(query):
        if token in _NOT_PRODUCT_WORDS or token in money:
            continue
        if not any(ch.isalpha() for ch in token):
            continue
        if token.isdigit():
            continue
        terms.append(token)

    if index is None:
        return terms
    return [token for token in terms if _the_file_uses(index, token)]


def _the_file_uses(index: CatalogIndex, token: str) -> bool:
    """Whether any product in the file uses this word, in any of its words."""
    return token in _catalog_words(index)


def _catalog_words(index: CatalogIndex) -> frozenset[str]:
    """Every word the file uses about any product, cached per read of the file."""
    cached = _file_words.get(id(index))
    if cached is None:
        words: set[str] = set()
        for product in index.products:
            words.update(fa_tokens(product.name))
            words.update(fa_tokens(product.subcategory_name))
            words.update(fa_tokens(product.category_name))
            if product.brand:
                words.update(fa_tokens(product.brand))
            if product.model:
                words.update(fa_tokens(product.model))
            for term in product.metadata.get("search_terms") or ():
                words.update(fa_tokens(str(term)))
        cached = frozenset(words)
        _file_words[id(index)] = cached
    return cached


def search(
    index: CatalogIndex,
    query: str,
    filters: CatalogFilters | None = None,
    *,
    limit: int = 20,
    offset: int = 0,
    detected_category: str | None = None,
) -> tuple[list[CatalogMatch], int]:
    """
    Search the catalogue. Returns the page of matches and the total.

    The order of authority is the whole design:

        structured constraints  >  free text

    A category the caller passed, and a category this module resolved from the
    query against the file's own labels, are **hard** constraints. Once either is
    known, a product outside it cannot enter the result set at all, whatever else
    the query happens to contain. Free text is then only what orders what is left
    — so «ماشین» can no longer pull a dishwasher into a washing-machine search,
    which is what it did when a lone word was sufficient evidence for a match.

    A ceiling is hard in the same way, and is checked against the cheapest price
    the product can actually be bought at rather than the file's headline figure,
    so «تا ۳۰ تومن» never returns a ۱۸۷ میلیون dishwashers because its sticker
    once read lower.

    With no resolved category, the text decides, and it decides conservatively:
    a product is returned only if a word that names something matched it, and the
    words that cannot name anything are dropped before matching starts.
    """
    filters = filters or CatalogFilters()

    # A caller's category wins over a detected one: it is an explicit choice.
    category = filters.category or detected_category
    terms = evidence_terms(query, index)

    if not category and not terms:
        return [], 0

    matches: list[CatalogMatch] = []
    for product in index.products:
        if category and product.subcategory != category:
            continue
        if filters.top_category and (
            canonical_category(product.category) != canonical_category(filters.top_category)
        ):
            continue
        if filters.brand and product.brand != filters.brand:
            continue
        if filters.only_available and not product.available_offers_count:
            continue
        if filters.max_price is not None:
            buyable = product.purchasable_min_price
            # nothing buyable is not "within budget"; it is not a candidate
            if buyable is None or buyable > filters.max_price:
                continue

        if not terms:
            # The category is known and the query said nothing else about the
            # product, so every product of that kind qualifies and the ordering
            # below puts the cheapest first.
            matches.append(CatalogMatch(product, (), (), 0))
            continue

        scored = _score_match(product, terms)
        if scored is None:
            continue
        matched, reasons, score = scored
        matches.append(CatalogMatch(product, tuple(matched), tuple(reasons), score))

    # A resolved category narrows the set; within it, text order first, then the
    # cheapest, so a query that names nothing in particular is still useful.
    matches.sort(key=lambda m: (-m.score, m.product.min_price, m.product.name))
    return matches[offset : offset + limit], len(matches)


@dataclass(frozen=True)
class DetectedCategory:
    """
    The subcategory a query names, and how sure the file allows us to be.

    ``slug`` is the strongest single reading of the query; ``run_length`` is the
    number of consecutive words that made it. A caller that needs a hard
    constraint requires ``decisive``, because a reading that merely tied with
    another is not a constraint — it is a guess, and guessing a category is what
    this whole change exists to stop.
    """

    slug: str
    top_category: str
    run_length: int
    decisive: bool


#: Words that turn a number into a ceiling rather than a measurement of the
#: product. This is a closed piece of grammar, not a table of queries: what is
#: recognised is the *relation* between a number and a limit, the same way
#: :data:`app.core.text.MONEY_WORDS` recognises the unit. A sentence that says
#: "up to", "under" or "at most" is stating a bound, whoever wrote it.
_BUDGET_CEILING_MARKERS = frozenset({"تا", "زیر", "حداکثر", "حداکثرا", "کمتر", "کمتر از"})


def detect_budget_ceiling(query: str) -> int | None:
    """
    The upper price a query states, in Toman, or ``None``.

    Recognises a number that is introduced as a bound — «تا ۳۰ تومن»,
    «زیر ۱۰ میلیون تومان» — and scales it by the unit around it. Only a bound is
    read: «۹ کیلوگرم» is a capacity and «۳۰ سانتی» a measurement, so a number
    with no money unit beside it is not a budget.

    A number bound to a currency with **no** magnitude word is read as millions.
    That is the colloquial reading, and it is the only usable one: «تا ۳۰ تومن»
    does not mean thirty Toman, it means thirty million, and taking it literally
    would drop every product from the results and report an empty shop. A caller
    that means something else passes ``max_price`` explicitly, which always wins
    over anything read here.

    This exists so a stated ceiling is honoured without spending an inference.
    It is deliberately narrow: a query it cannot read yields ``None`` and the
    ceiling is simply not applied.
    """
    from app.core.text import MONEY_WORDS, digits_to_ascii

    #: A bare currency word with no scale beside it means millions.
    _CURRENCY_WORDS = {word for word, scale in MONEY_WORDS.items() if scale == 1}
    _SCALE_WORDS = {
        word: scale for word, scale in MONEY_WORDS.items() if scale != 1
    }

    words = fa_tokens(query)
    for position, word in enumerate(words):
        if not word.isdigit():
            continue
        # the words immediately around the number decide what kind it is
        before = words[position - 1] if position else ""
        after = words[position + 1] if position + 1 < len(words) else ""
        if before not in _BUDGET_CEILING_MARKERS and after not in _BUDGET_CEILING_MARKERS:
            continue
        # and it is money only if a unit is stated nearby
        window = words[max(0, position - 2) : position + 3]
        scale: int | None = None
        for candidate in window:
            if candidate in _SCALE_WORDS:
                scale = _SCALE_WORDS[candidate]
                break
            if candidate in _CURRENCY_WORDS:
                scale = 1_000_000
                break
        if scale is None:
            continue
        return int(digits_to_ascii(word)) * scale
    return None


def detect_category(index: CatalogIndex, query: str) -> DetectedCategory | None:
    """
    Read the kind of product a query is about off the catalogue's own labels.

    A product query names **one** kind of thing, so this looks for the longest
    run of consecutive query words that the file itself uses for a subcategory —
    its label or one of its ``search_terms``. The longest run wins, because the
    longer the phrase the shop itself uses, the more of what was asked it accounts
    for.

    That rule is what separates the two kinds of «ماشین». The file offers
    "ماشین لباسشویی" and "ماشین ظرفشویی" as search terms, so a query carrying
    either resolves to exactly that subcategory, and a bare «ماشین» ties between
    them and is reported as not decisive rather than resolved to whichever row
    happened to come first in the file.

    A top-level label ("لوازم برقی") is a reading too, but of nothing in
    particular, so it is only returned when no subcategory reading exists and it
    is decisive on its own.
    """
    words = evidence_terms(query, index)
    if not words:
        return None
    vocabulary = index.subcategory_vocabulary()

    brands = index.brand_tokens()
    best: tuple[int, str] | None = None
    tied = False
    for slug, subcategory in vocabulary.items():
        kinds = tuple(phrase for phrase in subcategory.phrases if _names_a_kind(phrase, brands))
        length = _longest_run(words, kinds)
        if not length:
            continue
        if best is None or length > best[0]:
            best, tied = (length, slug), False
        elif length == best[0]:
            tied = True
    if best is not None:
        slug, length = best[1], best[0]
        return DetectedCategory(
            slug=slug,
            top_category=canonical_category(index.top_category_of(slug)) or "",
            run_length=length,
            decisive=not tied,
        )
    return None


def _names_a_kind(phrase: str, brands: frozenset[str]) -> bool:
    """
    Whether a phrase names a *kind of thing* rather than a maker.

    A subcategory's ``search_terms`` mix the two: "ماشین لباسشویی" is what the
    thing is, "پاکشوما" is who makes it, and both live in the same list. Letting
    the second count is how «یخچال دوو» ended up a tie between refrigerators and
    washing machines, and therefore no decision at all — with the category no
    longer a hard constraint, a brand-matched washing machine answered a fridge
    query. A phrase whose every word is a brand or a model identifies no kind, and
    is not used to detect one.
    """
    tokens = fa_tokens(phrase)
    return bool(tokens) and not all(token in brands for token in tokens)


def _longest_run(words: list[str], phrases) -> int:
    """
    The longest consecutive stretch of ``words`` that spells one of ``phrases``.

    Phrases are compared word by word, so the length is in *words*: a two-word
    search term that appears intact beats a one-word one, which is the comparison
    that decides "ماشین لباسشویی" against "ماشین".
    """
    best = 0
    for phrase in phrases:
        tokens = fa_tokens(phrase)
        if not tokens:
            continue
        span = len(tokens)
        for start in range(len(words) - span + 1):
            if words[start : start + span] == tokens:
                best = max(best, span)
    return best


def similar(index: CatalogIndex, product: CatalogProduct, limit: int = 6) -> list[CatalogMatch]:
    """
    "Similar products", deterministically, from the catalogue only.

    The order is fixed and explainable:

    1. same subcategory **and** the same brand — the closest thing in the file;
    2. same subcategory;
    3. a different model of the same brand, elsewhere in the same top-level
       category;
    4. anything else in the same top-level category.

    No model is consulted, so the same query always returns the same list.
    """
    out: list[CatalogMatch] = []
    taken: set[UUID] = {product.id}

    def add(candidate: CatalogProduct, score: int, why: str) -> None:
        if candidate.id in taken or len(out) >= limit:
            return
        taken.add(candidate.id)
        out.append(
            CatalogMatch(
                product=candidate,
                matched_terms=(),
                reasons=(why,),
                score=score,
            )
        )

    same_subcategory = list(index.subcategories_of(product.subcategory))
    same_brand_sub = [c for c in same_subcategory if product.brand and c.brand == product.brand]
    for candidate in same_brand_sub:
        add(candidate, 400, f"همان برند «{product.brand}» و همان دسته.")
    for candidate in same_subcategory:
        add(candidate, 300, "از همان دستهٔ کاتالوگ.")

    if product.brand:
        for candidate in index.iter_category(product.category):
            if candidate.brand != product.brand or candidate.subcategory == product.subcategory:
                continue
            add(candidate, 200, f"همان برند «{product.brand}» در همین دسته‌بندی.")

    for candidate in index.iter_category(product.category):
        add(candidate, 100, f"از همان دسته‌بندی «{category_label(candidate.category)}».")
    return out




def alternatives(index: CatalogIndex, product: CatalogProduct) -> list[CatalogProduct]:
    """Cheaper products of the same kind, used for the basket's savings hint."""
    return [
        candidate
        for candidate in index.iter_subcategory(product.subcategory)
        if candidate.id != product.id
        and candidate.min_price
        and candidate.min_price < product.min_price
    ]


__all__ = [
    "ATTRIBUTE_LABELS",
    "CATEGORY_LABELS",
    "SUBCATEGORY_LABELS",
    "CatalogAttribute",
    "CatalogError",
    "CatalogFilters",
    "CatalogIndex",
    "CatalogMatch",
    "CatalogOffer",
    "CatalogProduct",
    "CatalogSeller",
    "SkippedRecord",
    "alternatives",
    "build_index",
    "DetectedCategory",
    "canonical_category",
    "category_label",
    "detect_budget_ceiling",
    "detect_category",
    "evidence_terms",
    "fa_tokens",
    "get_catalog",
    "normalize_persian",
    "read_index",
    "reset_cache",
    "resolve_catalog_path",
    "search",
    "subcategory_label",
]
