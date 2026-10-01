"""
Two failures from the runtime logs, and what is actually assertable about them.

**Quality.** The prompt told the model to write ``quality`` "the way the user
said it" while the schema holds the field to a closed enum, so «یه ماشین
ظرفشویی لوکس میخوام» came back with ``quality: "لوکs"``, failed validation, and
the endpoint answered 503. The enum is correct and stays strict — a free-text
quality would propagate a Persian adjective into a ladder that is compared
numerically. The fix is to make the model produce the canonical value, which means
the mapping has to be *in the prompt*, because the model is the only thing that
can read «لوکس».

**Token budget.** A model was seen to spend a whole 2000-token budget and return
nothing, then retry the same model at 6000. The retry is not the defect and is
left alone; the client distinguishes truncation from failure correctly and the
provider's ``finish_reason`` is read. What was wrong is what the model was given.

A model cannot be tested without calling one, and these tests call none. So they
assert the two things that *are* deterministic and that caused the failures: the
contract the prompt states, and the schema's behaviour. That the model now obeys
the contract is a fact about the model, and is the one thing here that has to be
confirmed against a live run.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.enums import Quality
from app.domains.search.llm_interpreter import SYSTEM_PROMPT
from app.domains.search.llm_schema import Constraints, LLMIntentResponse
from tests.llm_stub import LLMStub

LUXURY_QUERY = "یه ماشین ظرفشویی لوکس میخوام"


@pytest.fixture
def real_catalog(monkeypatch):
    """The enriched file, which is the one that carries room metadata."""
    import os
    from pathlib import Path

    from app.catalog.store import reset_cache
    from app.core.config import get_settings

    path = Path(__file__).resolve().parents[3] / "data" / "catalog" / "products_70_enriched.json"
    previous = os.environ.get("CATALOG_PATH")
    monkeypatch.setenv("CATALOG_PATH", str(path))
    get_settings.cache_clear()
    reset_cache()
    yield path
    if previous is None:
        os.environ.pop("CATALOG_PATH", None)
    else:
        os.environ["CATALOG_PATH"] = previous
    get_settings.cache_clear()
    reset_cache()


def _constraints(quality: str | None) -> dict:
    """
    The ``constraints`` block, as the model must send it.

    ``quality`` lives *inside* ``constraints``, not beside it. That is the whole
    shape of the bug: a field in the wrong place is an extra field, and a strict
    schema refuses it, so a perfectly good interpretation is thrown away with a
    503 and nothing in the log says where.
    """
    return {"quality": quality, "budget": None, "notes": []}


# --------------------------------------------------------------------------- #
# Problem 1 — quality
# --------------------------------------------------------------------------- #
class TestQualityIsCanonical:
    """
    The mapping has to be stated, because nothing else can supply it.

    The backend cannot read «لوکس» out of the query: by the time it sees the
    answer, the model has already decided what was asked for, and a field that
    failed to validate is a field that no longer exists. The wording-to-value
    step happens in the model, so the rule lives in the prompt.
    """

    def test_the_prompt_states_the_mapping(self) -> None:
        for value in Quality:
            assert value.value in SYSTEM_PROMPT, f"{value.value} is never offered"

    @pytest.mark.parametrize(
        ("wording", "expected"),
        [
            ("اقتصادی", "low"), ("معمولی", "low"), ("پایه", "low"), ("ارزان", "low"),
            ("متوسط", "medium"),
            ("خوب", "high"), ("باکیفیت", "high"), ("مرغوب", "high"),
            ("لوکس", "ultra"), ("پریمیوم", "ultra"),
            ("بسیار باکیفیت", "ultra"), ("حرفه‌ای", "ultra"),
        ],
    )
    def test_every_wording_of_the_mapping_is_named(self, wording: str, expected: str) -> None:
        """Each Persian word is bound to the value it must produce.

        Asserted one word at a time because a single ``in`` check over the whole
        prompt would pass on any of them being present anywhere.
        """
        line = next(
            (ln for ln in SYSTEM_PROMPT.splitlines() if f"{expected}" in ln and "=" in ln),
            "",
        )
        assert line, f"no line offers {expected}"
        assert wording in line, f"{wording!r} is not mapped to {expected}"

    def test_the_prompt_does_not_ask_for_the_users_wording(self) -> None:
        """The contradiction that caused the 503 must be gone.

        The prompt used to say project facts are written exactly as the user said
        them, naming ``quality`` in that list, in the same breath as a schema that
        only accepts four values. A model obeying that instruction necessarily
        fails validation.
        """
        for line in SYSTEM_PROMPT.splitlines():
            if "همان‌طور بنویس که کاربر گفته" in line:
                assert "quality" not in line, (
                    "quality must not be listed among the fields copied verbatim"
                )

    def test_the_prompt_says_quality_is_an_exception(self) -> None:
        assert "برای quality نگاشت پایین‌تر آمده" in SYSTEM_PROMPT
        assert "مقدار استانداردش را بنویس، نه لفظ کاربر را" in SYSTEM_PROMPT

    def test_the_prompt_separates_the_schema_value_from_the_explanation(self) -> None:
        """The user's word belongs in the prose, not in the field.

        «لوکس» is what the shopper said and is worth saying back to them; it is
        not a value the ladder can hold. Both halves are required.
        """
        assert "لفظ اصلی کاربر را فقط در explanations فارسی بیاور" in SYSTEM_PROMPT
        assert "explanations حداکثر ۲ مورد، کوتاه و فارسی" in SYSTEM_PROMPT


class TestQualityValidationStaysStrict:
    """
    The schema is the guard, and this is what stops it being weakened.

    The temptation when a field keeps failing validation is to accept a string.
    That would move a Persian adjective into a ladder compared with ``<`` and
    ``>=`` all over the optimiser, so the enum holds and the model is told what to
    put in it.
    """

    @pytest.mark.parametrize("value", ["low", "medium", "high", "ultra"])
    def test_the_canonical_values_are_accepted(self, value: str) -> None:
        assert Constraints(quality=value).quality.value == value

    @pytest.mark.parametrize(
        "value", ["لوکس", "خوب", "متوسط", "economical", "luxury", "premium", "", "LOW!"]
    )
    def test_anything_else_is_rejected(self, value: str) -> None:
        with pytest.raises(ValidationError):
            Constraints(quality=value)

    def test_an_arbitrary_string_is_rejected_for_a_requirement_too(self) -> None:
        """``quality_min`` is the same ladder and gets the same treatment."""
        from app.domains.search.llm_schema import SemanticRequirement

        assert SemanticRequirement(description="تخت", terms=["تخت"], quality_min="high")
        with pytest.raises(ValidationError):
            SemanticRequirement(description="تخت", terms=["تخت"], quality_min="لوکس")

    def test_the_ladder_is_still_ordered(self) -> None:
        assert [q.value for q in Quality] == ["low", "medium", "high", "ultra"]


class TestTheLuxuryQueryIsAnswered:
    """Case 1 of the report, driven through the real endpoint."""

    def test_a_luxury_product_query_answers_with_ultra(
        self, client: TestClient, llm: LLMStub, real_catalog
    ) -> None:
        """
        The model answered correctly and the pipeline threw the answer away.

        ``intent`` and ``terms`` were right, and ``quality: "لوکس"`` was the one
        field the schema could not hold, so the whole interpretation was rejected
        and the endpoint answered 503 — for a query about a dishwasher.
        """
        llm.product(terms=["ماشین ظرفشویی"], constraints=_constraints("ultra"))
        response = client.post("/api/v1/search/interpret", json={"query": LUXURY_QUERY})
        assert response.status_code == 200, response.text
        body = response.json()

        # The endpoint reports the enum by name, as the rest of the API does.
        assert body["intent"] == "PRODUCT_SEARCH"
        query = body["product_query"]
        assert "ماشین ظرفشویی" in query["text"]
        assert set(query["tokens"]) >= {"ماشین", "ظرفشویی"}
        assert query["quality"] == "ultra"
        assert body["requirements"]["quality"] == "ultra", (
            "the field carries the canonical value, not the Persian adjective"
        )
        # and the query was still understood as the product it names
        assert query["category_slug"] == "dishwasher"

    def test_the_explanation_may_still_use_the_users_word(
        self, client: TestClient, llm: LLMStub, real_catalog
    ) -> None:
        """
        The distinction the report asked for, kept honest.

        The structured field carries ``ultra``; the Persian prose may say «لوکس».
        Nothing in the response requires the user's wording to survive, so this
        asserts the *field* is canonical and leaves the prose alone rather than
        demanding the model quote the user back.
        """
        llm.product(terms=["ماشین ظرفشویی"], constraints=_constraints("ultra"))
        body = client.post(
            "/api/v1/search/interpret", json={"query": LUXURY_QUERY}
        ).json()
        assert body["requirements"]["quality"] == Quality.ULTRA.value
        assert isinstance(body.get("explanations", []), list)

    @pytest.mark.parametrize(
        ("query", "quality"),
        [
            ("یه ماشین ظرفشویی لوکس میخوام", "ultra"),
            ("یه ماشین ظرفشویی باکیفیت میخوام", "high"),
            ("یه ماشین ظرفشویی کیفیت متوسط میخوام", "medium"),
            ("یه ماشین ظرفشویی ارزان میخوام", "low"),
        ],
    )
    def test_each_rung_of_the_ladder_survives_validation(
        self, client: TestClient, llm: LLMStub, real_catalog, query: str, quality: str
    ) -> None:
        """
        One case per rung, driven through the endpoint.

        What is being checked is that a canonical value at every rung reaches the
        client intact — that none of the four is rejected the way "لوکس" was. The
        model is scripted, so this does not prove the model produces them; that is
        the live check.
        """
        llm.product(terms=["ماشین ظرفشویی"], constraints=_constraints(quality))
        response = client.post("/api/v1/search/interpret", json={"query": query})
        assert response.status_code == 200, response.text
        assert response.json()["requirements"]["quality"] == quality


class TestTheSchemaCarriesTheEnum:
    def test_the_provider_is_sent_a_closed_set(self) -> None:
        """
        ``response_format=json_schema`` is what puts the four values in front of
        the model, so the enum has to survive into the JSON Schema and not only
        into Python. A missing ``enum`` here is why a model free to write «لوکس»
        did.
        """
        schema = Constraints.model_json_schema()
        definition = schema["$defs"]["Quality"]
        assert definition["enum"] == ["low", "medium", "high", "ultra"]
        # and the field really is a reference to it, not a bare string
        assert schema["properties"]["quality"]["anyOf"][0]["$ref"].endswith(
            "/Quality"
        )

    def test_the_whole_response_is_still_small(self) -> None:
        """A small schema is part of why the answer is quick."""
        properties = LLMIntentResponse.model_json_schema()["properties"]
        assert set(properties) == {
            "intent", "category", "category_raw", "project", "search",
            "constraints", "constraint_kind", "confidence", "explanations",
        }


class TestTheCategoryVocabulary:
    """
    The report asked whether the prompt and the catalogue disagree on
    ``appliance`` vs ``appliances``.

    They do not, and that is worth pinning: the file writes the plural, the API
    speaks the singular, and the folding happens in one place so the prompt can
    only ever be given a value the schema accepts. A prompt that offered
    ``appliances`` would fail ``Domain`` validation — the same failure as the
    quality field, by a different route.
    """

    def test_the_prompt_offers_only_values_the_enum_accepts(
        self, client: TestClient, llm: LLMStub
    ) -> None:
        from app.core.enums import Domain
        from app.domains.search.taxonomy import build_taxonomy

        valid = {d.value for d in Domain}
        for slug, _label in build_taxonomy().categories:
            assert slug in valid, f"{slug!r} is offered but Domain would reject it"

    def test_the_singular_is_what_crosses_into_the_api(
        self, client: TestClient, llm: LLMStub, real_catalog
    ) -> None:
        llm.product(terms=["ماشین ظرفشویی"], category="appliance",
                       constraints=_constraints(None))
        body = client.post(
            "/api/v1/search/interpret", json={"query": LUXURY_QUERY}
        ).json()
        assert body["domain"] == "appliance"

    def test_both_spellings_name_one_category(self) -> None:
        from app.catalog.store import canonical_category
        from app.core.enums import domain_from

        assert canonical_category("appliances") == canonical_category("appliance")
        assert domain_from("appliances") is domain_from("appliance")


# --------------------------------------------------------------------------- #
# Problem 2 — the model spends its budget and answers nothing
# --------------------------------------------------------------------------- #
class TestTheAnswerIsAskedForDirectly:
    """
    The retry is not the bug, so these are the levers that are.

    ``chat_json`` reads ``finish_reason`` and reports truncation separately from
    failure, then retries the *same* model with a larger budget. That is correct
    behaviour for a model that genuinely needed more room, and it is left
    untouched. It is also what a model that thinks its way past its budget looks
    like, which is why the request is what changed.
    """

    def test_the_prompt_says_to_emit_the_json_at_once(self) -> None:
        assert "همین حالا JSON را بنویس" in SYSTEM_PROMPT

    def test_the_prompt_forbids_reasoning_aloud(self) -> None:
        # The wording changed when the prompt had to stop asking for reasoning:
        # the old line invited the model to "do a small structural job: write an
        # analysis, a rationale or a note first", which is what it then did inside
        # the JSON. The demand is the same, only the contradiction is gone.
        for phrase in (
            "همین حالا JSON را بنویس.",
            "تحلیل، استدلال، برنامه‌ریزی یا یادداشت ننویس.",
            "هیچ reasoning یا prose تولید نکن.",
            "فقط و فقط یک JSON object",
            "پیش از JSON و پس از آن هیچ متنی ننویس",
        ):
            assert phrase in SYSTEM_PROMPT, f"{phrase!r} is missing"

    def test_the_only_permitted_prose_is_a_schema_field(self) -> None:
        """Reasoning must not be asked for in a field either.

        ``explanations`` is the one place Persian is wanted, and it is capped. A
        model told to "explain" and given an unbounded list will use it as a
        scratchpad, which is the same budget drain by another route.
        """
        assert "تنها prose مجاز، همان explanations کوتاه فارسی" in SYSTEM_PROMPT
        assert "explanations حداکثر ۲ مورد" in SYSTEM_PROMPT

    def test_the_retry_is_left_intact(self, monkeypatch) -> None:
        """
        One retry, same model, larger budget — and nothing added.

        Asserted because the tempting fix for a truncating model is another retry
        or a bigger default budget, and both would hide the cause rather than
        address it.
        """
        from app.core.config import get_settings

        settings = get_settings()
        assert settings.llm_truncation_retries == 1
        assert settings.llm_max_tokens == 2000
        assert settings.llm_max_tokens_on_truncation == 6000

    def test_truncation_is_reported_as_truncation_not_failure(self) -> None:
        """The client already distinguishes the two; that is why there is a retry."""
        from app.llm import LLMTruncated
        from app.llm.openrouter import extract_json_object

        body = {
            "model": "m",
            "choices": [
                {"finish_reason": "length", "message": {"content": "   "}}
            ],
        }
        with pytest.raises(LLMTruncated):
            extract_json_object(body, model="m")

    def test_a_whole_answer_is_not_reported_as_truncation(self) -> None:
        """Empty content with the budget intact is a different failure."""
        from app.llm import LLMTruncated
        from app.llm.openrouter import extract_json_object

        body = {
            "model": "m",
            "choices": [{"finish_reason": "stop", "message": {"content": ""}}],
        }
        with pytest.raises(Exception) as caught:
            extract_json_object(body, model="m")
        assert not isinstance(caught.value, LLMTruncated)


class TestThePromptDoesNotMisleadTheModel:
    """
    The room evidence handed the model was partly a list of brands.

    ``room_vocabulary`` is built from product names, and a product name carries
    its maker, so «دوو» and «پاکشوما» were presented as words that place a
    product in the utility room, and «ظرفشویی» was offered as a utility-room word
    for a query about a dishwasher. The model is given evidence that contradicts
    the sentence in front of it and spends its budget working out which to
    believe. Brands are their own column in the file, so the fix reads that
    column instead of listing any name.
    """

    def test_no_room_evidence_word_is_a_brand_or_model(self, real_catalog) -> None:
        from app.catalog.store import get_catalog
        from app.domains.search.taxonomy import build_taxonomy

        brands = get_catalog().brand_tokens()
        assert brands, "the file records brands, which is what makes this checkable"
        for room, words in build_taxonomy().rooms:
            leaked = sorted(word for word in words if word in brands)
            assert not leaked, f"{room} is described by brands {leaked}"

    def test_the_room_evidence_still_names_rooms(self, real_catalog) -> None:
        """Dropping brands must not empty the evidence out."""
        from app.domains.search.taxonomy import build_taxonomy

        rooms = dict(build_taxonomy().rooms)
        assert rooms, "there is still evidence to give"
        assert any(words for words in rooms.values())

    def test_the_user_prompt_stays_small(self, client: TestClient, llm: LLMStub) -> None:
        """
        The guard against unbounded growth, which is where a bloat regression
        would arrive: the user prompt is built from the catalogue, so it is the
        part that can grow without anyone editing it.
        """
        llm.bathroom_project()
        client.post("/api/v1/search/interpret", json={"query": "یه نیاز دارم"})
        assert len(llm.last_prompt) < 900
