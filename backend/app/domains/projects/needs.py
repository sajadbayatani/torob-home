"""
What a project needs, and what the catalogue can do about it.

This module is the seam between the two halves of the project pipeline.

**The model's half** is understanding: *this person wants a gaming corner in
their hall, so it needs somewhere to put the console and somewhere to sit.*
That arrives as `SemanticRequirement` objects — a description and the words for
the kind of thing needed. Nothing else.

**The backend's half** is truth: which subcategories in the enriched file answer
that need, what they cost, whether they suit the room, whether they can be
bought. That happens here and in `app.catalog.selection`, deterministically,
and it never calls a model.

The reason this exists is that requirements used to come from
`project_templates`. A model could understand the sentence perfectly and have
its answer replaced by whatever rulebook matched a room name — which is how a
hall project ended up asking for a refrigerator.

The template tables are still there and still seeded, and an admin surface can
still read them. Nothing in this pipeline consults them, and that is deliberate
rather than provisional. An earlier version of this module kept a narrow use for
them — a template could refine the *quantity* of a need the model had already
named. It was removed, because it could not do anything: every rule carrying
real arithmetic (a 12 m² room takes ~39 m² of tile) is keyed on a rulebook role
with **no catalogue subcategory**, so there was nothing to match a resolved need
against, and every rule that did name a subcategory was a plain "one of these".
Wiring the arithmetic back up would mean matching the model's words to rulebook
roles, which is a mapping by another name and the exact thing this change
removes. A quantity is therefore what the model stated, or one.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.enums import Quality


@dataclass(frozen=True)
class ProjectNeed:
    """
    One requirement of the project, resolved against the catalogue.

    ``role`` is the backend's own key for this need, assigned in the order the
    model listed them. The model never names one: roles are how selections are
    recorded, replayed and looked up, so a model inventing them would put two
    different projects' answers under the same key.
    """

    role: str
    #: the model's own description, shown to the user
    description: str
    #: the words it gave for the kind of thing needed
    terms: tuple[str, ...] = ()
    #: catalogue subcategories that answer it. Empty means the catalogue has
    #: nothing for this need, which is reported rather than papered over.
    slugs: tuple[str, ...] = ()
    quantity: int = 1
    required: bool = True
    quality_min: Quality = Quality.LOW

    @property
    def slug(self) -> str | None:
        """The subcategory this need is answered from, when it has one."""
        return self.slugs[0] if self.slugs else None

    @property
    def matched(self) -> bool:
        return bool(self.slugs)


def resolve_needs(
    index,
    requirements,
    *,
    scope,
    project_type: str | None = None,
    area_m2: float | None = None,
    quality: Quality = Quality.LOW,
) -> list[ProjectNeed]:
    """
    Turn the model's requirements into needs the catalogue can answer.

    Every requirement the model produced becomes exactly one need, in the order
    it listed them. None is dropped for want of a product — a need nothing
    satisfies is still a need, and the project reports it as unmet. None is
    invented either: this function only ever *resolves* words against the file.

    A need's quantity is the model's when it stated one, and one otherwise. No
    rule is consulted to improve on that.
    """
    from app.catalog.selection import subcategories_for_terms

    needs: list[ProjectNeed] = []
    for position, requirement in enumerate(requirements, start=1):
        terms = tuple(requirement.terms) or _terms_from(requirement.description)
        slugs = tuple(
            subcategories_for_terms(
                index, terms, scope=scope, project_type=project_type, area_m2=area_m2
            )
        )
        floor = requirement.quality_min or quality or Quality.LOW
        quantity = int(requirement.quantity) if requirement.quantity is not None else 1
        needs.append(
            ProjectNeed(
                role=f"req_{position}",
                description=requirement.description,
                terms=terms,
                slugs=slugs,
                quantity=quantity,
                required=requirement.required,
                quality_min=floor,
            )
        )
    return needs


def _terms_from(description: str) -> tuple[str, ...]:
    """
    Fall back to the description when the model gave no search words.

    The description is the one thing it always produced, and the file's own
    words are in it as often as not ("کاشی و سرامیک"). Splitting it is
    arithmetic on text, not a translation table, and it keeps a need resolvable
    when the model was terse.
    """
    from app.catalog.store import fa_tokens

    return tuple(fa_tokens(description))


__all__ = ["ProjectNeed", "resolve_needs"]
