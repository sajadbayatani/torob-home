"""Which catalogue products are *eligible* for a project, decided from the file.

The enriched catalogue tags every product with what it actually is and where it
belongs — ``rooms``, ``product_roles``, ``use_cases``, ``project_types``,
``space_fit``, ``search_terms``. This module turns those tags into a decision.

It exists because the alternative was a category check, and a category is far too
coarse to answer the question. Everything in ``furniture`` is the same category,
yet a bed belongs in a bedroom and a dining table does not. Asking a language
model to make that call instead was worse: the model cannot see the catalogue, so
it either guesses or is handed a pool it has to sift through. The sift belongs
here, where it is reproducible and free.

The division of labour this establishes:

* **here** — which products are eligible at all
* **the model** — which of the eligible ones are most useful

No model is consulted here, and no wording of the user's is inspected. The only
text read is the room the interpreter reported, and it is matched against labels
the catalogue itself carries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.catalog.store import CatalogIndex, CatalogProduct
from app.core.text import normalize_persian

#: Shortest word that may carry meaning when matching a room. Two-letter
#: fragments collide constantly in Persian ("می" of "میز", "شی" of "شیر") and
#: would match rooms on the strength of a fragment.
MIN_ROOM_TOKEN = 3

#: The file describes size qualitatively ("small", "medium", "large", "flexible")
#: and carries no numbers, so an area has to be read onto those labels somehow.
#: This is the one place a number is introduced, and it is a *preference order
#: only*: it reorders eligible candidates and never removes one. A wrong band
#: therefore costs a worse first choice, not a missing product.
SPACE_BANDS: tuple[tuple[float, str], ...] = ((10.0, "small"), (20.0, "medium"))

#: Preference rank, best first. "flexible" suits any room, so it leads.
SPACE_PREFERENCE: dict[str, int] = {
    "flexible": 0,
    "small": 1,
    "medium": 2,
    "large": 3,
}


def _tokens(text: str | None) -> set[str]:
    """The words of a phrase, ignoring anything shorter than a real word."""
    if not text:
        return set()
    return {
        word
        for word in re.findall(r"[\u0600-\u06ffA-Za-z0-9]+", text.lower())
        if len(word) >= MIN_ROOM_TOKEN
    }


def _same_word(asked: str, known: str) -> bool:
    """
    Whether two words mean the same thing for matching purposes.

    Persian attaches its possessives and some vowel endings directly to the
    word, so a room is often reported as "خوابم" where the catalogue says
    "خواب". A prefix comparison catches that without needing a list of endings,
    which would be a keyword table.
    """
    if asked == known:
        return True
    shorter, longer = sorted((asked, known), key=len)
    return len(shorter) >= MIN_ROOM_TOKEN and longer.startswith(shorter)


@dataclass(frozen=True, slots=True)
class RoomScope:
    """
    The rooms a project is about, resolved from the catalogue's own vocabulary.

    ``tokens`` is empty when the interpreter named no room, or named one this
    catalogue has no word for. That is a real and common case — the labels are a
    shop's labels, not a thesaurus — and it means *do not narrow by room*,
    which is the safe direction: the template's own rules still apply.
    """

    tokens: frozenset[str] = frozenset()
    vocabulary: dict[str, frozenset[str]] = field(default_factory=dict)

    @property
    def scoped(self) -> bool:
        return bool(self.tokens)

    def admits(self, product: CatalogProduct) -> bool:
        """Whether a product belongs to at least one of the project's rooms."""
        if not self.tokens:
            return True
        rooms = set(product.metadata.get("rooms") or [])
        if not rooms:
            # nothing said about where it goes, so nothing excludes it
            return True
        return bool(rooms & self.tokens)


def rooms_for_subcategory(index: CatalogIndex, slug: str | None) -> frozenset[str]:
    """
    The rooms a subcategory is recorded as belonging to.

    This is what lets a *requirement* be judged before anything is looked up in
    the catalogue: the question "is a dining table part of a bedroom?" is answered
    from the shop's own tagging, not from whether we happen to stock one today.

    Empty means nothing was recorded, which is not the same as "belongs to no
    room" and so must not be read as a reason to drop a requirement.
    """
    if not slug:
        return frozenset()
    return frozenset(
        room
        for product in index.subcategories_of(slug)
        for room in (product.metadata.get("rooms") or ())
    )


def requirement_belongs_to_rooms(
    index: CatalogIndex, slug: str | None, scope: RoomScope
) -> bool:
    """
    Whether a requirement is plausible for the project's room.

    Only excludes on positive evidence: the shop records the subcategory as
    belonging to *other* rooms, and none of them is the room in question. A
    subcategory with no recorded rooms, or an unscoped project, is left alone.
    """
    if not scope.scoped or not slug:
        return True
    rooms = rooms_for_subcategory(index, slug)
    if not rooms:
        return True
    return bool(rooms & scope.tokens)


def room_vocabulary_matches(asked: str, token: str, words: frozenset[str] | set[str]) -> bool:
    """
    Whether a word names one of the catalogue's room tokens.

    The same word test the vocabulary is built from, exposed so the interpreter
    and the deterministic filter cannot disagree about what a room is. A word the
    catalogue never uses simply matches nothing.
    """
    return any(_same_word(asked, known) for known in words)


def room_vocabulary(index: CatalogIndex) -> dict[str, frozenset[str]]:
    """
    Each room the catalogue knows, as the words the catalogue uses for it.

    Built from every product tagged with that room: its subcategory label, its
    own name, and its ``search_terms``. The result is the shop's own vocabulary,
    so adding a product changes it without any code being touched.
    """
    words: dict[str, set[str]] = {}
    for product in index.products:
        surface = {product.subcategory_name, product.name}
        surface.update(product.metadata.get("search_terms") or ())
        tokens = _tokens(" ".join(t for t in surface if t))
        for room in product.metadata.get("rooms") or ():
            words.setdefault(room, set()).update(tokens)
    return {room: frozenset(tokens) for room, tokens in words.items()}


def scope_for_rooms(rooms) -> RoomScope:
    """
    A scope from room tokens directly, for when the tokens are already known.

    Used where the subject is a set of products rather than a sentence: the
    rooms those products belong to are the rooms their complements must share.
    """
    tokens = frozenset(r for r in (rooms or ()) if r)
    return RoomScope(tokens=tokens)


def rooms_of(products) -> frozenset[str]:
    """Every room the given products are recorded as belonging to."""
    return frozenset(
        room for product in products for room in (product.metadata.get("rooms") or ())
    )


def build_room_scope(index: CatalogIndex, room: str | None) -> RoomScope:
    """
    Work out which rooms a project is about, from the room the interpreter gave.

    Returns a scope with no tokens — "not narrowed by room" — when the room is
    absent or names something this catalogue has no word for.
    """
    if not room:
        return RoomScope()
    asked = _tokens(room)
    if not asked:
        return RoomScope()
    vocabulary = room_vocabulary(index)
    matched = {
        candidate
        for candidate, words in vocabulary.items()
        if any(_same_word(word, known) for word in asked for known in words)
    }
    # The vocabulary holds the words the file uses inside product names and
    # labels, so a room *token* itself — "bedroom" — matches none of them. A
    # caller that already speaks the catalogue's vocabulary is still naming a
    # room, and taking it at its word is not a translation table: the token has
    # to be one the file itself declares. Without this, a room that reached us
    # already resolved produced an *empty* scope, which reads as "no room" and
    # lets every rule in the template through.
    # Compared in the same normalised form, so "living_room" is recognised
    # however it was written, and the token has to be fully accounted for.
    matched |= {
        candidate for candidate in vocabulary if _tokens(candidate) <= asked
    }
    return RoomScope(tokens=frozenset(matched), vocabulary=vocabulary)


def scope_for_room_token(index: CatalogIndex, token: str | None) -> RoomScope:
    """
    The scope for a room the catalogue already places products in.

    Used when the interpreter named one of the catalogue's own rooms. The token
    comes from the file, so nothing is invented here: an unknown token simply
    produces an empty scope, which means "not narrowed by room" rather than
    "no such room".
    """
    if not token:
        return RoomScope()
    return RoomScope(tokens=frozenset({token}), vocabulary=room_vocabulary(index))


def allows_project_type(product: CatalogProduct, project_type: str | None) -> bool:
    """
    Whether the file says the product is relevant to this kind of job.

    A product that lists other kinds of job and not this one is not a candidate.
    A product that lists none is left alone: the file may simply not have
    recorded a restriction, and refusing it would invent one.
    """
    if not project_type:
        return True
    types = set(product.metadata.get("project_types") or ())
    if not types:
        return True
    return project_type in types


def space_preference(product: CatalogProduct, area_m2: float | None) -> int:
    """How well the product suits the space, lower being better. Never excludes."""
    fits = product.metadata.get("space_fit") or ()
    if not fits:
        return 0
    if area_m2 is None:
        return min(SPACE_PREFERENCE.get(fit, 0) for fit in fits)
    band = "large"
    for limit, name in SPACE_BANDS:
        if area_m2 <= limit:
            band = name
            break
    best = min(SPACE_PREFERENCE.get(fit, 0) for fit in fits)
    if band in fits or "flexible" in fits:
        return min(best, SPACE_PREFERENCE.get(band, 0))
    # nothing the file offers suits this size: rank it last, but keep it
    return max(SPACE_PREFERENCE.get(fit, 0) for fit in fits)


def is_eligible(
    product: CatalogProduct,
    *,
    scope: RoomScope,
    project_type: str | None,
    area_m2: float | None,
) -> bool:
    """The whole deterministic test, in one place."""
    if not product.purchasable_offers:
        return False
    if not scope.admits(product):
        return False
    return allows_project_type(product, project_type)


def select_candidates(
    index,
    subcategory_slug: str | None,
    *,
    scope: RoomScope,
    project_type: str | None = None,
    area_m2: float | None = None,
):
    """
    Every product the catalogue offers for this role that the project can take.

    Eligibility comes from the enriched metadata alone: the product has to sit in
    one of the project's rooms, and to allow this kind of job. Nothing here is
    allowed to invent a requirement, and nothing is allowed to keep a product the
    file does not place in this room.

    Order is suitability then price, so a product the file says suits the space
    wins over a cheaper one it does not.

    The project's budget plays no part here. With one cheapest-first pick per
    requirement, a budget cannot change which product is chosen: whenever the
    cheapest option is inside the ceiling it is also the cheapest inside it. A
    budget filter that appeared to work here would be a no-op — measured over
    every subcategory and ceiling in the catalogue, it reordered nothing. Where
    the budget genuinely belongs is the estimate against it and the optimiser's
    plan, and both are re-run on every recalculation.
    """
    if not subcategory_slug:
        return []
    pool = [
        product
        for product in index.subcategories_of(subcategory_slug)
        if is_eligible(
            product, scope=scope, project_type=project_type, area_m2=area_m2
        )
    ]
    if not pool:
        return []
    return sorted(
        pool,
        key=lambda p: (space_preference(p, area_m2), p.min_price, str(p.id)),
    )


def complementary_subcategories_for(index: CatalogIndex, slug: str | None) -> tuple[str, ...]:
    """
    The subcategories the file says go with this one.

    Read from the products in ``slug`` rather than from a table, so the file
    stays the only source. A subcategory that declares nothing has no
    complements: guessing a relationship the data does not state is exactly the
    kind of invention this module exists to prevent.
    """
    if not slug:
        return ()
    found: set[str] = set()
    for product in index.subcategories_of(slug):
        for other in product.metadata.get("complementary_subcategories") or ():
            if other and other != slug:
                found.add(str(other))
    return tuple(sorted(found))


def complementary_slugs(product: CatalogProduct) -> tuple[str, ...]:
    """
    The subcategories the file says go with this product.

    The catalogue states this per product, so it is read rather than tabulated.
    An empty value falls back to the same room, which is the one relationship the
    file always implies: a product that names no complement is complemented by
    what it sits with.
    """
    declared = tuple(
        slug
        for slug in (product.metadata.get("complementary_subcategories") or ())
        if slug
    )
    if declared:
        return declared
    return ()


#: A word may not decide a match when more than this fraction of subcategories
#: use it. "مبلمان" is the category label on every furniture subcategory, so it
#: is true of all of them and therefore of none; measured rather than listed, so
#: a word stops being decisive the moment the shop stops using it everywhere.
MAX_SHARED_FRACTION = 0.5


def _room_words(scope: RoomScope) -> frozenset[str]:
    """
    The words that only name the rooms this project is about.

    A subcategory label may carry its room — "آینه سرویس بهداشتی" is the one
    bathroom label that spells the room out, while the rest are bare: "روشویی",
    "شیر روشویی", "توالت". Those two words were therefore *only* ever evidence for
    that one subcategory, at the highest weight there is, and a requirement that
    mentions the room at all — which a requirement about a bathroom nearly always
    does — resolved to the mirror. Lighting and plumbing came back as mirrors
    because both said "سرویس بهداشتی".

    The room is not missing from the decision, though: :meth:`RoomScope.admits`
    has already excluded everything the shop does not put in this room. Reading
    the room out of the words a second time adds nothing and, because the evidence
    is unevenly distributed, subtracts a great deal. So the room words are dropped
    from the requirement before scoring, and a term left with nothing but room
    words decides nothing — which is the honest answer for "the room needs
    something" and leaves the need reported as unmet rather than answered wrongly.
    """
    from app.catalog.store import CATEGORY_LABELS

    words: set[str] = set()
    for room in scope.tokens:
        label = CATEGORY_LABELS.get(room)
        if label:
            words |= _tokens(label)
    return frozenset(words)


def subcategories_for_terms(
    index,
    terms,
    *,
    scope: RoomScope,
    project_type: str | None = None,
    area_m2: float | None = None,
    limit: int = 4,
) -> list[str]:
    """
    Which subcategories answer a requirement the model described in words.

    The other half of "the model understands, the backend resolves": a
    ``SemanticRequirement`` carries words for the kind of thing needed, and this
    returns real subcategory slugs the file uses those words for. Nothing is
    invented — a requirement whose words the file does not use resolves to
    nothing, and is reported as unmet rather than quietly matched to whatever
    happens to be in stock.

    The comparison is **word by word**, not substring by substring, and that
    distinction is the whole fix. Joining a product's words into one string and
    asking whether the requirement sits inside it makes two errors, and the file
    produces both:

    * a word matches a longer one that merely contains it, so "مبل" (a sofa)
      matches "مبلمان" — the category label carried on all eight furniture
      subcategories — and a sofa requirement is answered with a bed;
    * a multi-word requirement has to appear contiguously, so "میز تحریر" fails
      against a subcategory the file calls "میز کار" and "میز اداری", even
      though the model and the shop plainly mean the same thing.

    So each requirement is reduced to the words the model used, and each
    subcategory to the words the file uses for it (`subcategory_vocabulary`), and
    a word counts when the file offers it as a way *into* that subcategory — its
    label or a search term — and when it is not shared by most of the catalogue.
    A word that only appears inside one product's name is context, not a claim
    that the product is that word.

    Eligibility is unchanged and still applies first: a subcategory the project
    cannot use is never offered as though it could satisfy the need.
    """
    vocabulary = index.subcategory_vocabulary()
    frequency = index.token_document_frequency()
    total = len(vocabulary) or 1
    # the project's own room words: applied by the scope already, so they are not
    # evidence for any one subcategory (see _room_words)
    ignored = _room_words(scope)

    ranked: list[tuple[float, int, str]] = []
    for slug, words in vocabulary.items():
        if not any(
            is_eligible(product, scope=scope, project_type=project_type, area_m2=area_m2)
            for product in index.subcategories_of(slug)
        ):
            continue
        best = 0.0
        matched_terms = 0
        for term in terms or ():
            score = _term_score(term, words, frequency, total, ignored)
            if score > 0:
                matched_terms += 1
                best = max(best, score)
        if best > 0:
            ranked.append((best, matched_terms, slug))
    # Strongest word first, then the most of the requirement's words a
    # subcategory accounts for, then the slug so the order never depends on
    # dictionary order.
    ranked.sort(key=lambda row: (-row[0], -row[1], row[2]))
    return [slug for _, _, slug in ranked[:limit]]


def _term_score(term, words, frequency, total: int, ignored=frozenset()) -> float:
    """
    How well one requirement word is answered by one subcategory, 0.0 to 1.0.

    1.0 when the requirement *is* something the file offers as a phrase for that
    subcategory — the file naming the thing itself, which is as strong as this
    kind of evidence gets. Otherwise the best qualifying word, discounted by how
    much of the requirement it accounts for, so "تخت" answers "تخت خواب" better
    than it answers "تخت خواب چوبی دو نفره".
    """
    from app.catalog.store import (
        VOCAB_WEIGHT_LABEL,
        VOCAB_WEIGHT_SEARCH_TERM,
        SubcategoryVocabulary,
    )

    assert isinstance(words, SubcategoryVocabulary)
    folded = normalize_persian(str(term))
    if not folded:
        return 0.0
    if folded in words.phrases:
        return 1.0
    tokens = _tokens(folded)
    # the room is not a product word, so it is neither evidence nor part of how
    # much of the requirement a match accounts for
    tokens = [token for token in tokens if token not in ignored]
    if not tokens:
        return 0.0
    best = 0.0
    for token in tokens:
        weight = words.tokens.get(token)
        if weight is None or weight < VOCAB_WEIGHT_SEARCH_TERM:
            # not offered as a way in: it only occurs incidentally
            continue
        if frequency.get(token, 0) > total * MAX_SHARED_FRACTION:
            # too many subcategories use it to point at this one
            continue
        best = max(best, (weight / VOCAB_WEIGHT_LABEL) / len(tokens))
    return best
