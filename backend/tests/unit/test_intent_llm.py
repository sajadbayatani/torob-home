"""The intent interpreter is a model, not a word list.

Two things are proven here, and they are the whole point of the rewrite.

**Wording is irrelevant.** A set of phrasings that mean the same thing must all
reach the same intent. These tests cannot pass by phrase matching, because the
app contains no phrases to match: the response is decided by what the model is
scripted to say, and the same answer drives every phrasing.

**The pipeline is real.** The tests are driven through the HTTP boundary, so the
client is built from settings, the prompt is assembled from the catalogue, the
reply is parsed, validated against the schema, and checked against the taxonomy.
The last class asserts the prompt actually contained the catalogue, and that no
Persian phrase table has crept back into the search domain.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from tests.llm_stub import LLMStub

#: Three ways of asking for the same bathroom work. None of them is a phrase the
#: application knows; "قصد دارم" and "نوسازی" in particular were never listed.
BATHROOM_PHRASINGS = [
    "میخوام سرویس بهداشتی رو بازسازی کنم",
    "قصد دارم حمام و دستشویی رو نوسازی کنم",
    "میخوام دکوراسیون سرویس بهداشتی رو عوض کنم",
]

#: Three ways of asking about a bedroom. "دکوراسیون اتاق خواب" was never a
#: project marker in the old lexicon, which is why it used to fall through.
BEDROOM_PHRASINGS = [
    "میخوام دکوراسیون اتاق خوابم رو تغییر بدم",
    "اتاق خوابم نیاز به تغییر دکوراسیون داره",
    "برای اتاق خواب جدید چه چیزهایی لازمه؟",
]

#: Ways of asking for one product.
PRODUCT_PHRASINGS = [
    "یه شیر توالت خوب میخوام",
    "شیر توالت مدل X",
    "شیر توالت سفید",
    "یخچال سامسونگ",
]


def interpret(client: TestClient, query: str) -> dict:
    response = client.post("/api/v1/search/interpret", json={"query": query})
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------------- #
# the same meaning, different words
# --------------------------------------------------------------------------- #
class TestParaphrases:
    @pytest.mark.parametrize("query", BATHROOM_PHRASINGS)
    def test_bathroom_work_is_a_project(
        self, client: TestClient, llm: LLMStub, query: str
    ) -> None:
        llm.bathroom_project(type="renovation")
        body = interpret(client, query)

        assert body["intent"] == "NEED_SEARCH"
        assert body["domain"] == "bathroom"
        assert body["project_type"] == "renovation"
        assert body["interpreter"] == "llm"

    @pytest.mark.parametrize("query", BATHROOM_PHRASINGS)
    def test_bathroom_phrasings_agree(
        self, client: TestClient, llm: LLMStub, query: str
    ) -> None:
        """The same model answer must produce the same decision, whatever the words."""
        # a project names no subcategories at all: the template decides those
        llm.bathroom_project(type="renovation")
        body = interpret(client, query)
        assert body["matched_subcategories"] == []
        assert body["domain"] == "bathroom"

    @pytest.mark.parametrize("query", BEDROOM_PHRASINGS)
    def test_bedroom_work_is_a_project(
        self, client: TestClient, llm: LLMStub, query: str
    ) -> None:
        """A bedroom is furniture, and the catalogue stocks furniture."""
        llm.answer(
            intent="project_search",
            project={
                "type": "redesign",
                "room": "اتاق خواب",
                "area_m2": None,
                "goal": "تغییر دکوراسیون اتاق خواب",
                "constraints": [],
            },
            category="furniture",
        )
        body = interpret(client, query)

        assert body["intent"] == "NEED_SEARCH"
        assert body["domain"] == "furniture"
        assert body["project_type"] == "redesign"
        assert body["room"] == "اتاق خواب"
        # the model names no slugs, so none can be invalid
        assert body["matched_subcategories"] == []

    @pytest.mark.parametrize("query", PRODUCT_PHRASINGS)
    def test_a_product_request_is_a_product_search(
        self, client: TestClient, llm: LLMStub, query: str
    ) -> None:
        llm.product_search(terms=["شیر توالت"])
        body = interpret(client, query)
        assert body["intent"] == "PRODUCT_SEARCH"

    def test_a_bare_budget_is_neither(
        self, client: TestClient, llm: LLMStub
    ) -> None:
        llm.constraint_only(kind="BUDGET", budget=55_000_000)
        body = interpret(client, "بودجه من ۵۵ میلیون است")
        assert body["intent"] == "UNKNOWN"
        assert body["requirements"]["budget"] == 55_000_000

    def test_the_wording_alone_decides_nothing(self, client: TestClient, llm: LLMStub) -> None:
        """The same sentence can be read either way, and the model decides.

        A phrase-based interpreter cannot do this: it would return the same
        answer for this query no matter what the model was told. Here the reply
        is changed and the outcome changes with it.
        """
        query = "میخوام سرویس بهداشتی رو بازسازی کنم"

        llm.bathroom_project(type="renovation")
        assert interpret(client, query)["intent"] == "NEED_SEARCH"

        llm.constraint_only(kind="BUDGET", budget=10_000_000)
        assert interpret(client, query)["intent"] == "UNKNOWN"

        llm.product_search(terms=["سرویس بهداشتی"])
        assert interpret(client, query)["intent"] == "PRODUCT_SEARCH"


# --------------------------------------------------------------------------- #
# the model is shown the catalogue, and cannot invent past it
# --------------------------------------------------------------------------- #
class TestTaxonomyIsTheVocabulary:
    def test_the_prompt_carries_only_the_real_categories(
        self, client: TestClient, llm: LLMStub
    ) -> None:
        """
        The model is shown the categories, and nothing else from the catalogue.

        It used to be shown 22 subcategory slugs and 35 brand names, then answered
        a category where a subcategory was asked for. It is not asked about
        subcategories now, so it is not shown them.
        """
        from app.catalog.store import get_catalog

        llm.bathroom_project()
        interpret(client, "یه نیاز دارم")

        prompt = llm.last_prompt
        for slug, _ in get_catalog().categories():
            assert slug in prompt
        for subcategory in get_catalog().subcategory_slugs():
            assert subcategory not in prompt, "subcategories must not be in the prompt"
        for brand, _ in get_catalog().brands():
            assert brand not in prompt, "brands must not be in the prompt"

    def test_the_prompt_is_small(self, client: TestClient, llm: LLMStub) -> None:
        """A prompt for one sentence should not be thousands of characters.

        The ceiling has moved twice, both times for the same reason and both times
        for the same reason in fact: the instructions that decide *what a project
        needs* are the whole point of this model, and they are not negotiable, so
        the budget is raised rather than the content cut.

        1. The prompt began asking the model for the project's **requirements** at
           all — previously nothing asked it, and a template decided instead.
        2. The requirement contract was then stated properly: a need is derived
           from the goal rather than quoted from it, ``terms`` is a concrete
           generic category concept, and the abstractions that resolve to nothing
           («تجهیزات», «لوازم») are named as invalid. A vague contract is what
           produced unusable needs, so it was replaced with a precise one.
        3. The prompt then contradicted itself about quality — it asked for the
           user's own wording in a field the schema holds to a closed enum — so
           the four-step mapping from Persian wording to canonical value had to be
           stated, and the model told to emit the JSON at once rather than think
           its way to it. Both are instructions, not examples; nothing was added
           that the model could copy instead of deciding.

        What must stay small is the *user* prompt: it grows with the catalogue, and
        that is where an unbounded prompt would come from. It is checked separately
        against a fixture catalogue with no room metadata, so it is the headers and
        not the vocabulary that is being measured.
        """
        from app.domains.search.llm_interpreter import SYSTEM_PROMPT

        llm.bathroom_project()
        interpret(client, "یه نیاز دارم")
        # The ceiling catches runaway growth, not difficulty: what decides how long
        # a call takes is the *completion*, and this is a fixed small object. The
        # lines added for quality normalisation and for answering immediately are
        # both load-bearing, so the budget moved rather than either being cut.
        assert len(SYSTEM_PROMPT) + len(llm.last_prompt) < 6000
        # and the taxonomy-driven part is still small
        assert len(llm.last_prompt) < 900, "the user prompt must not scale with the catalogue"

    def test_a_category_the_catalogue_lacks_is_dropped(
        self, client: TestClient, llm: LLMStub
    ) -> None:
        """A category is the only reference the model may name, and it is checked."""
        llm.answer(
            intent="project_search",
            category="garden",
            project={"type": "renovation", "room": "باغ", "area_m2": None,
                     "goal": "بازسازی", "constraints": []},
        )
        body = interpret(client, "میخوام باغ رو بازسازی کنم")

        # not coerced into something that exists. The category is dropped, and
        # with it the domain, but the intent the model gave is kept: an
        # unresolvable reference is not a reason to doubt that this is a project.
        assert body["intent"] == "NEED_SEARCH"
        assert body["domain"] is None
        assert any("کاتالوگ ما نیست" in e for e in body["explanations"])

    def test_the_model_cannot_return_a_product(self, client: TestClient, llm: LLMStub) -> None:
        """The schema has no field a product could arrive in."""
        llm.answer(
            intent="product_search",
            search={"text": "شیر روشویی", "terms": ["شیر روشویی"],
                    "brand": None, "color": None},
            # a model that tries to smuggle catalogue data through
            subcategories=["sink-faucet"],
            products=[{"id": "11111111-1111-4111-8111-111111111111", "price": 1}],
        )
        # the strict schema rejects the extra key outright
        with pytest.raises(Exception):
            from app.domains.search.llm_schema import LLMIntentResponse

            LLMIntentResponse.model_validate(llm.reply)

    def test_an_unknown_intent_is_rejected(self) -> None:
        from pydantic import ValidationError

        from app.domains.search.llm_schema import LLMIntentResponse

        with pytest.raises(ValidationError):
            LLMIntentResponse.model_validate({"intent": "buy_now"})

    def test_a_project_claim_with_no_category_keeps_its_intent(
        self, client: TestClient, llm: LLMStub
    ) -> None:
        """A project with no category behind it is still a project.

        This used to be downgraded to UNKNOWN, and UNKNOWN falls back to the
        catalogue — so a project sentence was answered with unrelated products.
        The intent survives; the unresolved category is reported instead, and it
        is the project flow that decides whether it can be placed.
        """
        llm.answer(intent="project_search", project=None, category=None)
        body = interpret(client, "یه کاری می‌خوام بکنم")

        assert body["intent"] == "NEED_SEARCH"
        assert body["domain"] is None
        assert any("پروژه" in e for e in body["explanations"])


# --------------------------------------------------------------------------- #
# the pipeline itself
# --------------------------------------------------------------------------- #
class TestPipelineIsInvoked:
    def test_the_endpoint_calls_the_model(
        self, client: TestClient, llm: LLMStub
    ) -> None:
        llm.bathroom_project()
        interpret(client, "بازسازی سرویس بهداشتی")
        assert len(llm.calls) == 1

    def test_the_request_is_built_from_the_environment(
        self, client: TestClient, llm: LLMStub
    ) -> None:
        from app.core.config import get_settings

        settings = get_settings()
        llm.bathroom_project()
        interpret(client, "بازسازی سرویس بهداشتی")

        call = llm.calls[0]
        assert call["model"] == settings.llm_model
        assert call["temperature"] == settings.llm_temperature
        assert call["max_tokens"] == settings.llm_max_tokens
        assert call["url"].endswith("/chat/completions")
        assert call["headers"]["Authorization"] == "Bearer test-key-not-real"

    def test_every_query_goes_through_the_model(
        self, client: TestClient, llm: LLMStub
    ) -> None:
        """No query is answered without asking, however short or odd it is."""
        for query in ["الف", "؟؟", "۱۲۳", "x y z z z z z"]:
            llm.answer(intent="unknown")
            response = client.post("/api/v1/search/interpret", json={"query": query})
            if response.status_code == 200:
                assert llm.calls, f"{query!r} was answered without a model call"

    def test_a_fenced_reply_is_still_read(
        self, client: TestClient, llm: LLMStub
    ) -> None:
        """Real models wrap JSON in fences and sometimes in prose."""
        import json

        llm.bathroom_project(type="renovation")
        body = llm.reply
        llm.raw = f"```json\n{json.dumps(body, ensure_ascii=False)}\n```"
        result = interpret(client, "بازسازی سرویس بهداشتی")
        assert result["intent"] == "NEED_SEARCH"

    def test_prose_wrapped_json_is_recovered(
        self, client: TestClient, llm: LLMStub
    ) -> None:
        import json

        llm.bathroom_project(type="renovation")
        llm.raw = (
            "درخواست شما یک پروژهٔ بازسازی است:\n"
            + json.dumps(llm.reply, ensure_ascii=False)
            + "\nامیدوارم مفید باشد."
        )
        result = interpret(client, "بازسازی سرویس بهداشتی")
        assert result["intent"] == "NEED_SEARCH"

    def test_a_provider_failure_surfaces_instead_of_guessing(
        self, client: TestClient, llm: LLMStub
    ) -> None:
        """No keyword fallback: a broken model is an error, not a wrong answer."""
        import httpx

        llm.raises = httpx.ConnectError("no route to host")
        response = client.post("/api/v1/search/interpret", json={"query": "بازسازی"})
        assert response.status_code == 503

    def test_a_missing_key_fails_by_name(
        self, client: TestClient, llm: LLMStub, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.core.config import LLMNotConfigured, get_settings

        monkeypatch.setattr(get_settings(), "llm_api_key", "")
        with pytest.raises(LLMNotConfigured) as excinfo:
            get_settings().require_llm()
        assert "LLM_API_KEY" in str(excinfo.value)

    def test_a_malformed_reply_is_refused(
        self, client: TestClient, llm: LLMStub
    ) -> None:
        llm.raw = "I am not going to answer with JSON."
        response = client.post("/api/v1/search/interpret", json={"query": "بازسازی"})
        assert response.status_code == 503


# --------------------------------------------------------------------------- #
# the structural guarantee: no phrase table
# --------------------------------------------------------------------------- #
class TestNoHardcodedDetection:
    def test_the_old_interpreters_are_gone(self) -> None:
        import importlib

        for module in ("app.domains.search.lexicon", "app.domains.search.rules_interpreter"):
            with pytest.raises(ModuleNotFoundError):
                importlib.import_module(module)

    def test_the_search_domain_holds_no_persian_phrase_table(self) -> None:
        """
        Guard against the regression this change exists to prevent.

        A list of Persian phrases in the search domain is the shape of the bug:
        it looks like understanding and behaves like grep. Prompts legitimately
        contain Persian — the model has to be addressed in the user's language —
        so what is forbidden is *data*: a dict or list literal of phrases used
        for matching, which is what `lexicon.py` was.
        """
        import ast
        import pathlib

        offenders: list[str] = []
        for path in sorted(pathlib.Path("app/domains/search").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Dict, ast.List, ast.Tuple, ast.Set)):
                    continue
                elements = (
                    list(node.keys) if isinstance(node, ast.Dict) else node.elts
                )
                strings = [
                    e.value
                    for e in elements
                    if isinstance(e, ast.Constant)
                    and isinstance(e.value, str)
                    and any("\u0600" <= ch <= "\u06ff" for ch in e.value)
                ]
                # two or more Persian phrases in one literal is a lookup table
                if len(strings) >= 2:
                    offenders.append(f"{path.name}:{node.lineno} {strings[:4]}")

        assert not offenders, "Persian phrase tables found:\n" + "\n".join(offenders)

    def test_the_taxonomy_comes_from_the_catalogue_file(self) -> None:
        """Not from a constant: add a product and the model's vocabulary grows."""
        from app.catalog.store import build_index
        from app.domains.search.taxonomy import build_taxonomy
        from tests.fixtures import CATALOG

        index = build_index(CATALOG, source=None)
        taxonomy = build_taxonomy(index)

        assert taxonomy.subcategory_slugs == index.subcategory_slugs()
        assert {view.slug for view in taxonomy.subcategories} == {
            slug for slug, _ in index.subcategories()
        }
        # and the real catalogue's labels, not invented ones
        assert taxonomy.label_of("sink-faucet") == index.subcategory_label("sink-faucet")


# --------------------------------------------------------------------------- #
# The project requirement contract
# --------------------------------------------------------------------------- #
class TestProjectRequirementContract:
    """
    The prompt must plan procurement, and must not carry a checklist.

    A model cannot be tested deterministically without calling one, so these
    assert the two things that *are* deterministic: the contract the prompt
    states, and the absence of anything that would let a fixed list stand in for
    a rule. That absence is the point — the previous version of this prompt
    listed the nouns to look for and demonstrated the behaviour on one project,
    which is what produced the same requirements regardless of the sentence.
    """

    @staticmethod
    def _prompt() -> str:
        from app.domains.search.llm_interpreter import SYSTEM_PROMPT

        return SYSTEM_PROMPT

    def test_facts_and_requirements_are_declared_as_two_contracts(self) -> None:
        """The distinction the whole failure came from.

        Project *facts* are transcription and must stay grounded. Project
        *requirements* are planning and are explicitly not: a user describing a
        job is asking what has to be obtained to finish it.
        """
        prompt = self._prompt()
        assert "دو چیز متفاوت است و قاطی نکن" in prompt
        assert "فقط همان چیزی است که کاربر گفته" in prompt
        assert "برنامهٔ خریدِ لازم برای رسیدن به نتیجهٔ خواسته‌شده" in prompt
        assert "لازم نیست کاربر آن را نام برده باشد" in prompt
        assert "این برنامه‌ریزی معنایی است" in prompt

    def test_the_outcome_drives_the_decomposition(self) -> None:
        prompt = self._prompt()
        assert "نتیجهٔ خواسته‌شده چیست و دامنه‌اش چقدر است" in prompt
        assert "برای رسیدن به آن نتیجه، چه چیزهایی باید تهیه یا انجام شود" in prompt
        # scope-sensitive granularity, and no target count
        assert "همان‌قدر کلی بمان" in prompt
        assert "تعداد نیازها را هدف نکن" in prompt

    def test_requirements_are_kept_for_relevance_not_justified_by_quoting_the_user(self) -> None:
        """
        The gate that emptied this field is gone.

        A bed for a bedroom redesign is both what the job needs and what bedrooms
        contain, so "did the user ask for this, or is it just usual in the room?"
        has no good answer and a model asked it returns nothing. Relevance to the
        requested outcome is the test that can actually be answered.
        """
        prompt = self._prompt()
        assert "ربط داشته باشد" in prompt
        assert "چیزی که برای رسیدن به نتیجهٔ این کار تهیه می‌شود" in prompt
        assert "عادتِ همان اتاق" not in prompt
        assert "فقط عادت" not in prompt

    def test_an_empty_requirements_array_is_the_exceptional_case(self) -> None:
        prompt = self._prompt()
        assert "requirements خالی تقریباً همیشه غلط است" in prompt
        assert "فقط وقتی درست است که جمله هیچ پروژه‌ای توصیف نکند" in prompt
        # and the case that must never justify an empty array
        assert "حتی اگر کاربر هیچ اسمی نبرده باشد" in prompt

    def test_inferring_needs_is_permitted_and_bounded(self) -> None:
        """Permission on one side, a real limit on the other."""
        prompt = self._prompt()
        # permission
        assert "نام دستهٔ کالا را بنویس" in prompt
        # bounded: no umbrella words, no detail the sentence did not justify
        for banned in ("تجهیزات، لوازم، وسایل، فضای یا دکوراسیون",):
            assert banned in prompt, "umbrella words are named as things not to emit"
        assert "نیاز کلی را به اجزایش بشکن" in prompt
        # bounded: no specific product
        assert "نام برند، مدل، فروشنده، قیمت، مشخصهٔ فنی یا شناسهٔ کاتالوگ ننویس" in prompt
        # bounded: no invented user constraints
        assert "quantity فقط اگر کاربر گفته" in prompt
        assert "quality_min هم فقط اگر گفته" in prompt

    def test_catalog_availability_cannot_drive_generation(self) -> None:
        prompt = self._prompt()
        assert "موجود بودن در کاتالوگ ملاک نیست" in prompt
        assert "نیازِ بی‌محصول هم نیازِ درست است" in prompt

    def test_the_prompt_carries_no_project_checklist(self) -> None:
        """No noun list, and no worked project example."""
        prompt = self._prompt()
        for banned in (
            "میز، صندلی، تخت،",
            "مبل، سینک، شیر",
            "میز برای فضای گیمینگ",
            "میز گیمینگ ارگونومیک",
            "تخت، کمد، چراغ، پرده",
            "نمایشگر",
            "توالت، سینک، شیر",
        ):
            assert banned not in prompt, f"{banned!r} is a checklist, not a rule"

    def test_the_room_is_never_a_requirement_source(self) -> None:
        """Room-token normalisation may exist; a room→needs list may not."""
        prompt = self._prompt()
        assert "شناسه‌های مجاز room_token" in prompt
        assert "اتاق" in prompt  # the token contract is still there
        # and no rule anywhere keys requirements off the room
        assert "برای اتاق خواب" not in prompt
        assert "اتاق حمام" not in prompt

    def test_the_schema_accepts_a_decomposition_and_refuses_a_product(self) -> None:
        """Whatever decomposition arrives, the contract holds it to a need."""
        from app.domains.search.schemas import SemanticRequirement

        needs = [
            SemanticRequirement(description="تخت خواب", terms=["تخت"]),
            SemanticRequirement(description="کمد لباس", terms=["کمد"], required=False),
        ]
        assert [n.terms for n in needs] == [["تخت"], ["کمد"]]
        assert needs[1].required is False
        # A requirement may not carry anything a product would: the interpreter
        # decomposes, it never selects.
        for forbidden in (
            {"description": "تخت", "terms": ["تخت"], "brand": "ایکس ویژن"},
            {"description": "تخت", "terms": ["تخت"], "price": 5_000_000},
            {"description": "تخت", "terms": ["تخت"], "product_id": "abc"},
            {"description": "تخت", "terms": ["تخت"], "slug": "bed"},
        ):
            with pytest.raises(ValidationError) as caught:
                SemanticRequirement.model_validate(forbidden)
            assert "extra_forbidden" in str(caught.value)
