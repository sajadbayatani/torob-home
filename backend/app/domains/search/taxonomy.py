"""The catalogue taxonomy, in the form the intent model is shown.

The model may only map a user's words onto categories that **exist**. That is
only possible if it is told what exists, so this module is the bridge: it reads
the real catalogue and renders the taxonomy — top-level categories,
subcategories with their counts, and brands — as the prompt block.

Nothing here is authored by hand. Add a product to ``products.json`` and the
taxonomy the model sees grows with it, which is the whole point: the vocabulary
of the shop is a property of the shop, not of a list in a source file.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.catalog.store import CatalogIndex, get_catalog

#: shown to the model as the closed set of project kinds it may report
PROJECT_TYPE_HINTS = (
    "renovation",
    "new_build",
    "redesign",
    "repair",
)


@dataclass(frozen=True, slots=True)
class SubcategoryView:
    slug: str
    label: str
    category: str
    category_label: str
    count: int


@dataclass(frozen=True, slots=True)
class Taxonomy:
    """Everything the model is allowed to refer to."""

    categories: tuple[tuple[str, str], ...] = ()
    subcategories: tuple[SubcategoryView, ...] = ()
    brands: tuple[str, ...] = ()
    subcategory_slugs: frozenset[str] = field(default_factory=frozenset)
    #: The rooms the catalogue actually places products in, each with the words
    #: the file uses for it. Read from the file, not tabulated: a room appears
    #: here because products carry it, so the list grows with the data.
    rooms: tuple[tuple[str, tuple[str, ...]], ...] = ()

    def room_token(self, value: str) -> str | None:
        """The catalogue room a word belongs to, or None when it names none.

        Matching is the same word test the project engine already uses, so the
        model and the deterministic filter agree on what a room is.
        """
        from app.catalog.selection import room_vocabulary_matches

        for token, words in self.rooms:
            if room_vocabulary_matches(value, token, set(words)):
                return token
        return None

    def label_of(self, slug: str) -> str | None:
        for view in self.subcategories:
            if view.slug == slug:
                return view.label
        return None

    def has(self, slug: str) -> bool:
        return slug in self.subcategory_slugs

    def render_categories(self) -> str:
        """
        The four top-level categories, with their Persian names.

        This is the *entire* vocabulary the model is given. It used to be handed
        22 subcategory slugs and 35 brand names as well, and then answered with a
        category where a subcategory belonged. Naming categories is enough: which
        subcategories a project needs is the catalogue's decision, made
        deterministically, not the model's.
        """
        return "، ".join(f"{slug} ({label})" for slug, label in self.categories)

    def render_subcategories(self) -> str:
        """Subcategory slugs per category, for callers that need the detail."""
        lines = []
        by_category: dict[str, list[SubcategoryView]] = {}
        for view in self.subcategories:
            by_category.setdefault(view.category, []).append(view)

        for slug, label in self.categories:
            lines.append(f"\nدستهٔ {slug} ({label}):")
            for view in by_category.get(slug, ()):
                lines.append(f"  - {view.slug} | {view.label}")
        return "\n".join(lines)

    def has_category(self, slug: str) -> bool:
        """Whether the catalogue really carries this top-level category."""
        return any(candidate == slug for candidate, _ in self.categories)


def build_taxonomy(index: CatalogIndex | None = None, *, max_brands: int = 40) -> Taxonomy:
    """Read the real catalogue and describe it for the model."""
    catalog = index if index is not None else get_catalog()
    if catalog is None:
        return Taxonomy()

    from app.catalog.selection import room_vocabulary

    vocabulary = room_vocabulary(catalog)
    # A brand is not evidence of a room. The vocabulary is built from product
    # names, and a name carries its maker — so «دوو» and «پاکشوما» came out as
    # words that place a product in the utility room, and «ظرفشویی» was offered to
    # the model as a utility-room word. That is both wrong and expensive: the model
    # is handed evidence that contradicts the query it is reading, and works to
    # reconcile it. Brands are already their own column in the file, so the words
    # to drop are read rather than listed.
    brands = catalog.brand_tokens()
    rooms = tuple(
        (token, tuple(sorted(word for word in words if word not in brands)))
        for token, words in sorted(vocabulary.items())
    )

    subcategories = tuple(
        SubcategoryView(
            slug=slug,
            label=catalog.subcategory_label(slug),
            category=catalog.top_category_of(slug) or "",
            category_label=_category_label(catalog, catalog.top_category_of(slug)),
            count=count,
        )
        for slug, count in catalog.subcategories()
    )
    return Taxonomy(
        categories=tuple((slug, _category_label(catalog, slug)) for slug, _ in catalog.categories()),
        subcategories=subcategories,
        brands=tuple(name for name, _ in catalog.brands()[:max_brands]),
        subcategory_slugs=catalog.subcategory_slugs(),
        rooms=rooms,
    )


def _category_label(catalog: CatalogIndex, slug: str | None) -> str:
    if not slug:
        return ""
    from app.catalog.store import category_label

    return category_label(slug)


__all__ = [
    "PROJECT_TYPE_HINTS",
    "SubcategoryView",
    "Taxonomy",
    "build_taxonomy",
]
