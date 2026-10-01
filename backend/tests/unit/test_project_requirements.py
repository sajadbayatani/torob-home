"""
Where a project's requirements come from.

The architecture this module pins: the interpreter understands the project, the
backend resolves those needs against the catalogue, and the model then reasons
over real products. A project template is an **optional preset** — a quantity
rule and a label — and never a project's requirement list.

Every intent here is constructed directly. No test in this module calls a model,
and none of them asserts anything about a query string: a test that wanted a
fridge before now has to *ask* for one.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import select

from app.catalog.store import get_catalog
from app.core.enums import Quality
from app.domains.projects.models import ProjectAnalysis, ProjectRequirement, ProjectTemplate
from app.domains.projects.service import ProjectEngine
from app.domains.search.schemas import InterpretedIntent, SemanticRequirement

ENRICHED_CATALOG = (
    Path(__file__).resolve().parents[3] / "data" / "catalog" / "products_70_enriched.json"
)

#: The rules a rulebook still contains. Naming them lets a test assert that none of
#: them arrived on their own.
TEMPLATE_ROLES = {
    "tiles", "install_materials", "toilet", "vanity", "faucet", "mirror", "accessories",
    "cabinet", "counter_top", "sink", "cooktop", "hood", "hardware", "lighting",
    "bed", "wardrobe", "sofa", "desk", "dining_table", "dining_chair", "decor",
    "refrigerator", "washing_machine", "dishwasher", "vacuum", "television", "microwave",
}


@pytest.fixture(scope="module")
def catalog_file(tmp_path_factory):
    """This module runs against the **enriched** catalogue.

    Resolving a need to a subcategory is entirely metadata-driven, and the
    session-wide fixture catalogue in ``conftest`` predates the enrichment: no
    product in it carries ``rooms`` or ``search_terms``. Against it nothing
    resolves and nothing can be asserted. The override is undone afterwards.
    """
    path = tmp_path_factory.mktemp("catalog-enriched") / "products.json"
    path.write_text(ENRICHED_CATALOG.read_text(encoding="utf-8"), encoding="utf-8")
    previous = os.environ.get("CATALOG_PATH")
    os.environ["CATALOG_PATH"] = str(path)
    from app.catalog.store import reset_cache
    from app.core.config import get_settings

    get_settings.cache_clear()
    reset_cache()
    yield path
    if previous is None:
        os.environ.pop("CATALOG_PATH", None)
    else:
        os.environ["CATALOG_PATH"] = previous
    get_settings.cache_clear()
    reset_cache()


def _intent(
    room: str | None = None,
    *,
    room_token: str | None = None,
    goal: str | None = None,
    requirements: list[SemanticRequirement] | None = None,
    area_m2: float | None = None,
    quality: Quality | None = None,
    budget: int | None = None,
    template_slug: str | None = None,
    project_type: str | None = None,
) -> InterpretedIntent:
    """A mocked interpretation, built the way the interpreter returns one."""
    return InterpretedIntent(
        intent="NEED_SEARCH",
        project_type=project_type,
        room=room,
        room_token=room_token,
        goal=goal,
        product_query=None,
        matched_subcategories=[],
        requirements={
            "quality": quality,
            "budget": budget,
            "area_m2": area_m2,
            "style": None,
        },
        constraint_kind="NONE",
        confidence=0.9,
        interpreter="llm",
        explanations=[],
        template_slug=template_slug,
        project_requirements=list(requirements or []),
    )


def _need(description: str, *terms: str) -> SemanticRequirement:
    return SemanticRequirement(description=description, terms=list(terms))


#: Exactly the query the runtime log reported, and the reading the interpreter
#: gave it: a hall, a gaming corner, and nothing invented.
GAMING_HALL = _intent(
    "هال", goal="گیم بازی کنم", requirements=[_need("فضایی برای گیم بازی", "میز", "صندلی")]
)


# --------------------------------------------------------------------------- #
# A. A project is buildable without a template
# --------------------------------------------------------------------------- #
def test_a_project_without_a_template_is_still_a_project(session):
    """The reported query, verbatim in substance.

    There is no rulebook for a gaming corner in a hall and no canonical room for
    «هال». Under the old architecture that combination was refused, or handed
    whichever template the database returned first — and the project came back
    80 m², medium quality, with a refrigerator in it. It is now a project because
    the interpreter said what it needed.
    """
    response = ProjectEngine().build(
        session, intent=GAMING_HALL, query="میخوام یه قسمت به گوشه ی هال خونه اضافه کنم"
    )
    analysis = response.analysis

    assert analysis.template_slug is None
    assert [c.label for c in analysis.categories] == ["فضایی برای گیم بازی"]
    assert analysis.area_m2 is None
    assert analysis.budget is None


def test_a_hall_project_does_not_need_a_room_token(session):
    """`room_token` is a scoping convenience, not a precondition.

    The catalogue carries no word for «هال», so the token is null and the scope
    is empty. That means "not narrowed by room" — the project's validity does not
    depend on the catalogue recognising its space.
    """
    response = ProjectEngine().build(session, intent=GAMING_HALL, query="هال")
    assert response.analysis.template_slug is None
    assert response.analysis.categories, "an unplaceable room is still a project"


# --------------------------------------------------------------------------- #
# B. The requirements are the interpretation's
# --------------------------------------------------------------------------- #
def test_the_project_has_exactly_the_needs_the_interpretation_stated(session):
    intent = _intent(
        "پذیرایی",
        room_token="living_room",
        goal="تغییر دکور",
        requirements=[_need("مبل راحتی", "مبل"), _need("نورپردازی", "چراغ")],
    )
    analysis = ProjectEngine().build(session, intent=intent).analysis

    assert [c.label for c in analysis.categories] == ["مبل راحتی", "نورپردازی"]
    # the backend's own keys, assigned in the order the interpreter listed them
    assert [c.role for c in analysis.categories] == ["req_1", "req_2"]


def test_a_stated_quantity_is_kept(session):
    intent = _intent(
        "پذیرایی",
        room_token="living_room",
        requirements=[
            SemanticRequirement(description="صندلی", terms=["صندلی"], quantity=4)
        ],
    )
    analysis = ProjectEngine().build(session, intent=intent).analysis
    assert analysis.categories[0].quantity == 4


def test_a_need_nothing_answers_is_kept_and_reported(session):
    """A need the catalogue cannot meet stays a need.

    Dropping it would hide what the user asked for; matching it to whatever is in
    stock would be inventing a requirement.
    """
    intent = _intent(
        "پذیرایی",
        room_token="living_room",
        requirements=[_need("مبل راحتی", "مبل"), _need("اسکی", "اسکی")],
    )
    analysis = ProjectEngine().build(session, intent=intent).analysis

    labels = [c.label for c in analysis.categories]
    assert labels == ["مبل راحتی", "اسکی"]
    assert [c.role for c in analysis.missing_categories] == ["req_2"]


# --------------------------------------------------------------------------- #
# C. Nothing leaks in from a template or an earlier project
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "slug",
    ["bathroom_renovation", "kitchen_renovation", "furniture_redesign", "appliance_renovation"],
)
def test_no_template_contributes_a_need_the_model_did_not_state(session, slug):
    """Every seeded rulebook, checked against a project that asked for one thing.

    A template used to be the requirement list, so naming a bathroom produced
    seven bathroom needs whether or not the sentence did.
    """
    intent = _intent(
        "پذیرایی",
        room_token="living_room",
        template_slug=slug,
        requirements=[_need("مبل راحتی", "مبل")],
    )
    analysis = ProjectEngine().build(session, intent=intent).analysis

    assert [c.label for c in analysis.categories] == ["مبل راحتی"]


def test_a_previous_project_cannot_leak_into_the_next_one(session):
    """A rich project, then the reported one, in the same session."""
    engine = ProjectEngine()
    first = engine.build(
        session,
        intent=_intent(
            "پذیرایی",
            room_token="living_room",
            area_m2=80.0,
            quality=Quality.HIGH,
            requirements=[_need("مبل راحتی", "مبل")],
        ),
    )
    assert first.analysis.area_m2 == 80.0
    assert first.analysis.quality == Quality.HIGH

    second = engine.build(session, intent=GAMING_HALL, query="هال")

    assert second.analysis.area_m2 is None, "nobody stated an area the second time"
    assert second.analysis.quality != Quality.HIGH
    assert [c.label for c in second.analysis.categories] == ["فضایی برای گیم بازی"]

    stored = session.scalars(select(ProjectAnalysis)).all()
    assert len(stored) == 2
    assert stored[0].area_m2 == 80.0, "the first project's state stays its own"
    assert stored[1].area_m2 is None


def test_a_template_cannot_introduce_a_room_the_model_did_not_name(session):
    """The rulebook is a preset. It may refine a quantity; it may not add a need.

    The strongest form of this used to be a *room filter* over a template's
    rules, which is how a bedroom project kept a bed while a living-room project
    kept a sofa — decided by the room name, not by the sentence.
    """
    intent = _intent(
        "پذیرایی",
        room_token="living_room",
        template_slug="furniture_redesign",
        requirements=[_need("مبل راحتی", "مبل")],
    )
    analysis = ProjectEngine().build(session, intent=intent).analysis
    labels = {c.label for c in analysis.categories}
    assert labels == {"مبل راحتی"}


# --------------------------------------------------------------------------- #
# D and E. Unknown rooms, and nulls that stay null
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "room",
    ["هال", "هال خونه", "فضای کنار پذیرایی", "گوشه سالن", "فضای گیم", "زیرزمین"],
)
def test_an_unmapped_room_stays_a_valid_project(session, room):
    """No canonical room, and still a project.

    The system does not reject a project because it cannot place the space, and it
    does not fall back to another project's rulebook. Both of those were the
    state-leakage bug.
    """
    intent = _intent(room, requirements=[_need("مبل راحتی", "مبل")])
    analysis = ProjectEngine().build(session, intent=intent).analysis
    assert analysis.template_slug is None
    assert [c.label for c in analysis.categories] == ["مبل راحتی"]


def test_absent_values_are_not_inherited(session):
    """Area, budget, quality and style: none of them comes from a template.

    `default_area_m2` on the appliance rulebook is 80, and applying it to an
    unrelated project is precisely how a hall arrived 80 m². Area now stays null.
    """
    analysis = ProjectEngine().build(session, intent=GAMING_HALL).analysis
    assert analysis.area_m2 is None
    assert analysis.budget is None
    assert analysis.style is None
    # quality cannot be absent — it is the floor everything is judged against — so
    # it falls to a neutral middle, never to a rulebook's opinion
    assert analysis.quality == Quality.MEDIUM

    appliance = analysis_area_of_rulebook("appliance_renovation", session)
    assert appliance == 80.0, "the rulebook still has its default; nothing consults it"


def analysis_area_of_rulebook(slug: str, session) -> float | None:
    """A rulebook's own default area, read directly. Nothing in the pipeline uses it."""
    template = session.scalar(select(ProjectTemplate).where(ProjectTemplate.slug == slug))
    return float(template.default_area_m2) if template and template.default_area_m2 else None


def test_a_template_contributes_no_quantity_arithmetic_either(session):
    """
    What a rulebook is still allowed to do: nothing, here.

    A template used to compute quantities as well as list needs — a 12 m² room
    took 39 m² of tile by a 3.2-per-square-metre rule. Keeping that as a "preset"
    looks harmless and is not: every rule carrying that arithmetic is keyed on a
    rulebook *role* with no catalogue subcategory, so there is nothing to match a
    resolved need against, and every rule that did name a subcategory was a plain
    "one of these". Reconnecting it would mean matching the model's words to
    rulebook roles, which is a mapping by another name.

    So a quantity is what the model stated, or one. This test pins that, and pins
    the reason, so the loss is visible rather than rediscovered.
    """
    from app.seed.dataset import PROJECT_TEMPLATES

    arithmetic = [
        (t["slug"], r)
        for t in PROJECT_TEMPLATES
        for r in t["requirements"]
        if r["quantity_mode"] != "fixed" or str(r["min_qty"]) not in ("0", "0.0")
    ]
    assert arithmetic, "the seeded rulebooks still contain quantity rules"
    # every one of them is keyed on a role the catalogue cannot address, which is
    # exactly why none of them can be applied to a model-stated need
    assert all(r["category"] is None for _slug, r in arithmetic if r["quantity_mode"] == "per_area")

    intent = _intent(
        "سرویس بهداشتی",
        room_token="bathroom",
        area_m2=12.0,
        template_slug="bathroom_renovation",
        requirements=[_need("توالت", "توالت")],
    )
    analysis = ProjectEngine().build(session, intent=intent).analysis
    assert [c.label for c in analysis.categories] == ["توالت"]
    assert analysis.categories[0].quantity == 1, "no rule adjusted it"


# --------------------------------------------------------------------------- #
# F. The flows that had to keep working
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "room, room_token, area, project_type, needs, expected",
    [
        ("اتاق خواب", "bedroom", 12.0, "redesign",
         [("تخت خواب", "تخت"), ("کمد لباس", "کمد")], {"تخت خواب", "کمد لباس"}),
        ("آشپزخانه", "kitchen", 10.0, "renovation",
         [("کابینت", "کابینت"), ("سینک", "سینک")], {"کابینت", "سینک"}),
        ("پذیرایی", "living_room", None, "redesign",
         [("مبل راحتی", "مبل")], {"مبل راحتی"}),
    ],
)
def test_existing_projects_build_from_their_needs(
    session, room, room_token, area, project_type, needs, expected
):
    intent = _intent(
        room,
        room_token=room_token,
        area_m2=area,
        project_type=project_type,
        requirements=[_need(d, *t) for d, t in needs],
    )
    analysis = ProjectEngine().build(session, intent=intent).analysis
    assert {c.label for c in analysis.categories} == expected
    assert analysis.area_m2 == area
    # whatever the catalogue can cover is offered, and it is a real product
    for candidate in analysis.candidates:
        assert candidate.unit_price > 0
        assert candidate.offer is not None


def test_a_bedroom_project_never_asks_for_a_sofa(session):
    """The room filter used to guarantee this by trimming a rulebook.

    It is guaranteed now by the needs being what the model said, and the room
    deciding only which products may answer them.
    """
    intent = _intent(
        "اتاق خواب",
        room_token="bedroom",
        area_m2=12.0,
        project_type="redesign",
        requirements=[_need("تخت خواب", "تخت")],
    )
    analysis = ProjectEngine().build(session, intent=intent).analysis
    labels = {c.label for c in analysis.categories}
    assert labels == {"تخت خواب"}
    for candidate in analysis.candidates:
        assert "bedroom" in set(
            get_catalog().get(candidate.product.id).metadata.get("rooms") or ()
        )


# --------------------------------------------------------------------------- #
# G. Product search never reaches any of this
# --------------------------------------------------------------------------- #
def test_product_search_never_touches_a_template(session):
    """A product search has no project, so it has no requirements to resolve.

    This is the boundary worth pinning: the refactor added a resolution step that
    reads project templates, and a search must not be able to reach it.
    """
    from app.core.enums import Intent
    from app.domains.search.schemas import ProductQuery

    intent = InterpretedIntent(
        intent=Intent.PRODUCT_SEARCH,
        product_query=ProductQuery(text="شیر توالت خوب", tokens=["شیر", "توالت"]),
        matched_subcategories=[],
        requirements={"quality": None, "budget": None, "area_m2": None, "style": None},
        constraint_kind="NONE",
        confidence=0.9,
        interpreter="llm",
        explanations=[],
        # deliberately carrying a template slug: nothing downstream of a product
        # search may act on it
        template_slug="bathroom_renovation",
        project_requirements=[],
    )
    assert intent.template_slug == "bathroom_renovation"
    assert intent.project_requirements == []

    from app.domains.projects.needs import resolve_needs

    scope, _ = __import__(
        "app.domains.projects.service", fromlist=["project_scope"]
    ).project_scope(get_catalog(), intent)
    assert resolve_needs(get_catalog(), intent.project_requirements, scope=scope) == []


def test_the_project_tables_are_still_seeded_and_readable(session):
    """The templates are presets now, not history to be deleted.

    They are still rows, still queryable, and an admin surface can still read
    them. What changed is that the recommendation path does not require one.
    """
    templates = session.scalars(select(ProjectTemplate)).all()
    assert templates, "the preset tables are still populated"
    rules = session.scalars(select(ProjectRequirement)).all()
    assert rules
    assert {r.role for r in rules} & TEMPLATE_ROLES


# --------------------------------------------------------------------------- #
# The optimiser reads the project's own quality floors
# --------------------------------------------------------------------------- #
def test_the_optimiser_reads_floors_from_the_projects_needs(session):
    """A consequence of moving the requirements, and easy to leave behind.

    The optimiser asks the project analysis what quality floor each role has, so
    it can refuse to plan a swap that would drop below the floor the user asked
    for. It used to read those floors from the template's rules — a different
    list, from a different source, and empty for any project that matched no
    rulebook at all.
    """
    from app.domains.basket.optimizer import _quality_floors

    engine = ProjectEngine()
    response = engine.build(
        session,
        intent=_intent(
            "پذیرایی",
            room_token="living_room",
            quality=Quality.HIGH,
            requirements=[_need("مبل راحتی", "مبل")],
        ),
    )
    basket_id = response.analysis.basket_id
    assert basket_id is not None

    basket = session.get(
        __import__("app.domains.basket.models", fromlist=["Basket"]).Basket, basket_id
    )
    floors = _quality_floors(session, basket)
    assert floors, "the project stated a floor, so the optimiser must see it"
    assert set(floors) == {"req_1"}
    assert all(isinstance(floor, Quality) for floor in floors.values())


def test_the_optimiser_needs_no_template_to_do_that(session):
    """The same project with no rulebook at all still yields its floors."""
    from app.domains.basket.models import Basket
    from app.domains.basket.optimizer import _quality_floors

    response = ProjectEngine().build(
        session,
        intent=_intent(
            "هال", quality=Quality.HIGH,
            requirements=[_need("فضایی برای گیم بازی", "میز", "صندلی")],
        ),
    )
    basket = session.get(Basket, response.analysis.basket_id)
    floors = _quality_floors(session, basket)
    assert set(floors) == {"req_1"}


# --------------------------------------------------------------------------- #
# A decomposition is carried through, never second-guessed or replaced
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "room, room_token, goal, needs",
    [
        # four unrelated projects, four different decompositions
        ("هال", "living_room", "فضای گیمینگ در گوشه هال",
         [("میز", ["میز"]), ("صندلی", ["صندلی"]), ("روشنایی", ["چراغ"])]),
        ("اتاق خواب", "bedroom", "تغییر دکوراسیون اتاق خواب",
         [("تخت خواب", ["تخت"])]),
        ("سرویس بهداشتی", "bathroom", "نوسازی سرویس بهداشتی",
         [("توالت", ["توالت"]), ("سینک", ["سینک"]), ("شیر", ["شیر"])]),
        ("بالکن", None, "ساخت گلخانه کوچک در بالکن",
         [("گلدان", ["گلدان"])]),
    ],
    ids=["gaming-corner", "bedroom", "bathroom", "balcony"],
)
def test_each_project_carries_exactly_its_own_decomposition(
    session, room, room_token, goal, needs
):
    """
    The project's needs are the model's, whatever room it is in.

    A template would show up here immediately: four different sentences would
    produce overlapping or identical lists, because a rulebook lists by project
    type and these four are not the same project. Distinct sets across unrelated
    rooms is the observable signature of requirements coming from the
    interpretation.
    """
    from app.domains.search.schemas import SemanticRequirement

    intent = _intent(
        room,
        room_token=room_token,
        goal=goal,
        requirements=[
            SemanticRequirement(description=d, terms=t) for d, t in needs
        ],
    )
    analysis = ProjectEngine().build(session, intent=intent).analysis

    assert [c.label for c in analysis.categories] == [d for d, _t in needs]
    # no role outside the declaration arrived, from anywhere
    assert {c.role for c in analysis.categories} == {
        f"req_{i}" for i in range(1, len(needs) + 1)
    }
    # and the stored snapshot — what a reload replays — is the same list. Read
    # from the row rather than the response: `needs` is deliberately not part of
    # the API contract.
    stored = session.scalars(
        select(ProjectAnalysis).where(ProjectAnalysis.id == analysis.id)
    ).one()
    assert [row["description"] for row in stored.needs] == [d for d, _t in needs]
    assert [row["role"] for row in stored.needs] == [
        f"req_{i}" for i in range(1, len(needs) + 1)
    ]


def test_no_requirement_ever_arrives_that_the_interpretation_did_not_state(session):
    """
    The strongest available form of "no hardcoded mapping".

    A single requirement is stated, and the project is built in a room that has a
    rulebook of its own with six rules. If anything anywhere still consulted it,
    the other five would appear.
    """
    intent = _intent(
        "سرویس بهداشتی",
        room_token="bathroom",
        template_slug="bathroom_renovation",
        requirements=[SemanticRequirement(description="توالت", terms=["توالت"])],
    )
    analysis = ProjectEngine().build(session, intent=intent).analysis

    assert [c.label for c in analysis.categories] == ["توالت"]
    for absent in ("کاشی و سرامیک", "مصالح نصب", "روشویی", "شیر", "آینه", "اکسسوری"):
        assert absent not in {c.label for c in analysis.categories}


def test_an_unmatched_requirement_is_still_the_projects_own(session):
    """
    A need the catalogue cannot answer is still a need.

    This is the layer the current work deliberately did not touch: the
    interpretation is free to name a real project need the file does not stock,
    and the requirement must survive that with its description intact rather than
    being replaced by something the file happens to carry.
    """
    intent = _intent(
        "بالکن",
        goal="گلخانه کوچک در بالکن",
        requirements=[
            SemanticRequirement(description="گلدان", terms=["گلدان"]),
            SemanticRequirement(description="خاک گلدانی", terms=["خاک"]),
        ],
    )
    analysis = ProjectEngine().build(session, intent=intent).analysis

    assert [c.label for c in analysis.categories] == ["گلدان", "خاک گلدانی"]
    assert analysis.candidates == []
    assert [c.role for c in analysis.missing_categories] == ["req_1", "req_2"]
