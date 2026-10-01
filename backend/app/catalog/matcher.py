"""Is this obviously a product search? Asked without a model.

The system used to spend a language model on every search, including
«شیر توالت». Classifying product-versus-project is not understanding, and the
model is the most expensive component in the system — so the first routing
decision is made here, from the catalogue file, and the model is only asked when
this cannot decide.

**The asymmetry is the whole point.** Being wrong in one direction costs one
inference; being wrong in the other sends a person's renovation to a product list.
So the rule is deliberately one-sided:

    every meaningful word in the query is accounted for by the catalogue
        → it is a product search, and we answer it with no inference
    otherwise
        → we do not guess, and the model is asked what the person wants

A project sentence fails this almost by construction. «آشپزخونه‌م رو میخوام
بازسازی کنم» contains «آشپزخونه», which the catalogue does know — but *بازسازی* and
*کنم* are not product words, so the query is not entirely about products and the
model is asked. That is the intended outcome, not a miss.

Nothing here is a list of products or of phrasings. The words in
:data:`_NOT_PRODUCT_WORDS` are Persian function words and generic preference
adjectives, which name nothing in the shop; the decision itself is made by
matching against the same fields the search itself matches — name, brand,
subcategory label, category label, and the enriched ``search_terms``. Adding a
product to ``products_70_enriched.json`` is therefore enough to make queries
about it route here, with no code change.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.catalog.store import CatalogIndex, CatalogProduct
from app.core.text import normalize_persian

#: Words that carry no reference to anything the shop sells.
#:
#: Deliberately limited to two closed groups, neither of which is a product or a
#: project:
#:
#: * function words — clitics, prepositions, conjunctions, and the handful of
#:   politeness words that carry no meaning in a search;
#: * generic preference adjectives — *خوب*, *ارزان* and their like, which say how
#:   the person feels and never *what* they want.
#:
#: Predicate verbs are **not** here. «مبل لازم دارم» and «مبل» are both plausible
#: readings, and dropping *لازم* and *دارم* would force the second, so the query
#: goes to the model. A false negative costs one inference; the opposite mistake
#: would misroute a project.
_NOT_PRODUCT_WORDS = frozenset(
    {
        # clitics and pronouns
        "م", "ما", "من", "تو", "شما", "خودم", "خود",
        # prepositions
        "برای", "از", "توی", "با", "به", "بر", "در", "رو",
        # conjunctions
        "و", "یا", "ولی", "اما", "که", "پس", "تا",
        # politeness and quantity filler
        "لطفا", "ممنون", "سلام", "یه", "یک", "دو", "چند",
        # the want-verb family. It appears in product and project sentences alike
        # — «شیر توالت خوب میخوام» and «میخوام خونه‌م رو مدرن کنم» both carry it —
        # so it distinguishes nothing and is dropped from both. The words that
        # *do* distinguish, such as «بازسازی» or «کنم», are not here.
        "میخوام", "میخوایم", "میخواید", "میخواهید", "میخوای", "میخواهی",
        "میخوامش", "بخوام", "بخرم", "بخرید",
        # generic preference, not identity
        "خوب", "خیلی", "بهترین", "عالی", "ارزان", "ارزون", "گرون", "مناسب",
    }
)


@dataclass(frozen=True)
class ProductVerdict:
    """
    The deterministic answer to "is this obviously a product search?".

    ``is_product`` is the only thing a caller should branch on. The rest is
    there to be read in a log when a routing decision is questioned: *why* a
    query went to the model, or why it did not, should not require a re-run.
    """

    is_product: bool
    #: the words that were considered, after filler was dropped
    terms: tuple[str, ...] = ()
    #: the words the catalogue accounts for
    explained: tuple[str, ...] = ()
    #: the words it does not — each one is the reason we asked the model
    unexplained: tuple[str, ...] = ()
    #: a short, stable, machine-readable reason, for logs
    reason: str = ""


def _fields(product: CatalogProduct) -> tuple[str, str, str, str]:
    """The four fields a product word can come from, normalised."""
    return (
        normalize_persian(product.name),
        normalize_persian(product.brand) if product.brand else "",
        normalize_persian(product.subcategory_name),
        normalize_persian(product.category_name),
    )


def _haystack(product: CatalogProduct) -> str:
    """Every word the file itself uses to describe one product.

    ``search_terms`` is included because it is the enriched vocabulary — the words
    a shopper would use that the product title does not contain — and it is the
    part of the file that makes this matcher work without a hand-written list.
    """
    name, brand, subcategory, category = _fields(product)
    terms = " ".join(product.metadata.get("search_terms") or ())
    return normalize_persian(f"{name} {brand} {subcategory} {category} {terms}")


def _names_something(token: str) -> bool:
    """
    Whether a token could name a thing at all.

    Digits are a size or a count, and a token with no letters is punctuation the
    tokeniser happened to keep («؟»). Neither names a product, and both would
    otherwise count as words the catalogue failed to explain — which would send a
    perfectly clear product query to the model over a question mark.
    """
    return any(ch.isalpha() for ch in token)


def meaningful_terms(query: str) -> tuple[str, ...]:
    """The words of a query that could name something the shop sells."""
    from app.catalog.store import fa_tokens

    return tuple(
        token
        for token in fa_tokens(query)
        if token not in _NOT_PRODUCT_WORDS and _names_something(token)
    )


def product_verdict(index: CatalogIndex, query: str) -> ProductVerdict:
    """
    Decide whether a query is unambiguously a request for catalogue products.

    Every meaningful word must be accounted for by the file, and at least one of
    them must land on something that identifies a *product* — its name, its brand,
    its subcategory, or the enriched search terms. A word that only appears in a
    broad top-level label ("خانگی") is not enough on its own, and one word is
    never enough: a single stray hit in a 70-product file is noise, not evidence.
    """
    terms = meaningful_terms(query)
    if not terms:
        return ProductVerdict(False, reason="no_product_words")

    explained: set[str] = set()
    identified: set[str] = set()
    for product in index.products:
        haystack = _haystack(product)
        if not haystack:
            continue
        name, brand, subcategory, _category = _fields(product)
        for term in terms:
            if term in explained and term in identified:
                continue
            if term not in haystack:
                continue
            explained.add(term)
            # A hit on the title, the brand, the subcategory, or the enriched
            # vocabulary identifies a product. A hit only on the top-level
            # category ("لوازم خانگی") does not.
            if term in name or term in brand or term in subcategory or term in haystack:
                identified.add(term)

    unexplained = tuple(term for term in terms if term not in explained)
    if not identified:
        return ProductVerdict(
            False, terms=terms, explained=tuple(sorted(explained)),
            unexplained=unexplained, reason="no_product_evidence",
        )
    if unexplained:
        return ProductVerdict(
            False, terms=terms, explained=tuple(sorted(explained)),
            unexplained=unexplained, reason="unexplained_words",
        )
    return ProductVerdict(
        True, terms=terms, explained=tuple(sorted(explained)), reason="all_words_explained"
    )


def is_product_search(index: CatalogIndex, query: str) -> bool:
    """The routing question itself, for callers that want only the answer."""
    return product_verdict(index, query).is_product


__all__ = ["ProductVerdict", "is_product_search", "meaningful_terms", "product_verdict"]
