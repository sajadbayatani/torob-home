"""
``LLM_REASONING_EFFORT``: how hard the interpreter is allowed to think.

The problem it exists for is in the runtime log: a reasoning model spent a whole
2000-token budget on a one-sentence interpretation and returned nothing, then the
retry at 6000 tokens had to go and do the same work again. Asking for less thinking
is the fix; raising the budget would have hidden it.

Two things are deliberately *not* changed, and are asserted here so a later change
cannot quietly make them:

* ``max_tokens`` — the budget is the operator's to set. This only changes how much
  of it gets used.
* the reasoning calls — candidate selection and the recommendation reasoning keep
  whatever the provider does by default, so their behaviour is untouched.

Every test here is about the *request that goes out*. No model is called.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import get_settings
from app.core.enums import ReasoningEffort
from app.llm import chat_json
from app.llm.openrouter import _attempt
from tests.llm_stub import LLMStub


@pytest.fixture
def effort(monkeypatch):
    """Set the effort, and put the settings cache back afterwards."""

    def set(value: str) -> None:
        monkeypatch.setenv("LLM_REASONING_EFFORT", value)
        get_settings.cache_clear()

    yield set
    get_settings.cache_clear()


def interpret(client: TestClient, llm: LLMStub, query: str = "یه نیاز دارم") -> dict:
    """Drive one interpretation and hand back the request that was sent."""
    llm.answer(intent="product_search", search={"text": "یخچال", "terms": ["یخچال"]})
    response = client.post("/api/v1/search/interpret", json={"query": query})
    assert response.status_code == 200, response.text
    return llm.calls[-1]


class TestTheSetting:
    def test_it_defaults_to_low(self, monkeypatch) -> None:
        """
        Cheap is the default, not an oversight.

        The whole reason the setting exists is that thinking hard about a
        one-sentence judgement tends to overrun the budget, so a deployment that
        sets nothing gets the behaviour that answers first time.
        """
        monkeypatch.delenv("LLM_REASONING_EFFORT", raising=False)
        get_settings.cache_clear()
        assert get_settings().llm_reasoning_effort == ReasoningEffort.LOW
        assert get_settings().llm_reasoning_effort == "low"

    @pytest.mark.parametrize("value", ["minimal", "low", "medium", "high"])
    def test_every_documented_effort_is_accepted(self, effort, value: str) -> None:
        effort(value)
        assert get_settings().llm_reasoning_effort == value

    @pytest.mark.parametrize("value", ["extreme", "LOW ", "max", "", "none", "lo"])
    def test_anything_else_is_refused_and_says_which_field(
        self, effort, value: str
    ) -> None:
        """
        Refused at startup, naming the field and the allowed values.

        Sending it anyway produces a provider error about a request this
        application did not know was malformed — an error that reads as a bad
        configuration over the network rather than a typo in a file next door.
        """
        effort(value)
        with pytest.raises(ValidationError) as caught:
            get_settings()
        message = str(caught.value)
        assert "llm_reasoning_effort" in message
        assert "minimal" in message and "high" in message

    def test_the_set_is_the_one_the_provider_documents(self) -> None:
        """
        Pinned to the four values, so this cannot grow by accident.

        An enum that silently gains a value would let a deployment send something
        the integration was never tested with.
        """
        assert [e.value for e in ReasoningEffort] == ["minimal", "low", "medium", "high"]


class TestTheInterpretationRequest:
    def test_it_sends_the_configured_effort(self, client: TestClient, llm, effort) -> None:
        effort("medium")
        call = interpret(client, llm)
        assert call["reasoning"] == {"effort": "medium"}

    def test_it_defaults_to_low_on_the_wire(
        self, client: TestClient, llm, monkeypatch
    ) -> None:
        monkeypatch.delenv("LLM_REASONING_EFFORT", raising=False)
        get_settings.cache_clear()
        call = interpret(client, llm)
        assert call["reasoning"] == {"effort": "low"}

    @pytest.mark.parametrize("value", ["minimal", "low", "medium", "high"])
    def test_each_effort_reaches_the_wire_unchanged(
        self, client: TestClient, llm, effort, value: str
    ) -> None:
        effort(value)
        assert interpret(client, llm)["reasoning"] == {"effort": value}

    def test_it_changes_neither_the_budget_nor_the_schema(
        self, client: TestClient, llm, effort
    ) -> None:
        """
        The two things this must not disturb.

        `max_tokens` is a separate decision — a bigger budget would hide the
        problem rather than address it — and the response format is how the answer
        is validated, so a change there would change what the interpreter accepts.
        """
        effort("high")
        call = interpret(client, llm)
        assert call["max_tokens"] == 2000
        assert call["response_format"]["type"] == "json_schema"
        assert call["model"] == "test/model"

    def test_the_effort_survives_the_truncation_retry(
        self, client: TestClient, llm, effort
    ) -> None:
        """
        A retry is the same request with more room — not a different one.

        The effort is read from settings on each attempt, so a second attempt must
        carry the same value; a retry that quietly stopped asking for it would be a
        different call wearing the same log line.
        """
        effort("low")
        llm.script = [  # run out of budget, then answer
                '{"intent":"unknown","category":null,"project":null,"search":null,'
                '"constraints":{"quality":null,"budget":null,"notes":[]},'
                '"constraint_kind":"NONE","confidence":0.5,"explanations":[]}',
            ]
        llm.answer(intent="product_search", search={"text": "یخچال", "terms": ["یخچال"]})
        client.post("/api/v1/search/interpret", json={"query": "یه نیاز دارم"})
        assert len(llm.calls) >= 1
        assert all(call["reasoning"] == {"effort": "low"} for call in llm.calls)


class TestOtherCallsAreUntouched:
    """
    The reasoning and recommendation calls do not send the field at all.

    This is what "apply it to the interpretation call for now" has to mean in code:
    not the same value everywhere, and not the same value everywhere by accident.
    A caller that does not pass the argument sends no ``reasoning`` key, so the
    provider's default applies and those payloads are unchanged.
    """

    def test_a_call_that_does_not_opt_in_sends_no_reasoning_field(self, llm) -> None:
        llm.script = ['{"ok": true}']
        chat_json(system="s", user="u")
        # recorded-but-absent, not present-and-empty: nothing was sent
        assert llm.calls[-1]["reasoning"] is None

    def test_the_project_reasoning_call_is_not_given_the_effort(self, llm) -> None:
        """
        Asserted on the call sites, because that is where the decision lives.

        Candidate selection and the recommendation reasoning both call
        ``chat_json`` without the argument; a test that only checked the client
        would still pass if someone added it to those calls.
        """
        import inspect

        from app.catalog import complementary
        from app.domains.projects import reasoning as project_reasoning

        for module, attribute in (
            (project_reasoning, "reason_project"),
            (complementary, "chat_json"),
        ):
            source = inspect.getsource(module)
            assert "reasoning_effort" not in source, (
                f"{module.__name__} must not send a reasoning effort; "
                "the client sends nothing when the argument is not passed"
            )
            assert attribute  # the module really is the one under test

    def test_only_the_interpreter_passes_it(self, llm) -> None:
        import inspect

        from app.domains.search import llm_interpreter

        source = inspect.getsource(llm_interpreter.LLMInterpreter._call)
        assert "reasoning_effort=settings.llm_reasoning_effort" in source


class TestThePayload:
    def test_the_field_is_built_exactly_as_documented(self) -> None:
        """
        ``{"effort": <value>}``, and nothing around it.

        OpenRouter takes the effort nested under ``reasoning``; a bare
        ``reasoning_effort`` key would be ignored by the provider and the setting
        would appear to work while doing nothing.
        """
        import json

        import app.llm.openrouter as openrouter
        from app.core.config import get_settings

        settings = get_settings()
        captured: dict = {}

        class _Recorder:
            def __init__(self, *_a, **_k) -> None:
                pass

            def __enter__(self) -> "_Recorder":
                return self

            def __exit__(self, *_e) -> None:
                return None

            def post(self, *_a, json=None, **_k):
                captured.update(json or {})
                raise RuntimeError("stop here")

        original = openrouter.httpx.Client
        openrouter.httpx.Client = _Recorder  # type: ignore[assignment]
        try:
            with pytest.raises(RuntimeError):
                _attempt(
                    # the id the settings hold, because the client asserts the
                    # model it sends is the one it was configured with
                    model=settings.require_model(),
                    system="s",
                    user="u",
                    max_tokens=2000,
                    schema_model=None,
                    strict_schema=True,
                    attempt=1,
                    reasoning_effort=ReasoningEffort.HIGH,
                )
        finally:
            openrouter.httpx.Client = original  # type: ignore[assignment]

        assert captured["reasoning"] == {"effort": "high"}
        # and the neighbouring settings are exactly as they were
        assert captured["max_tokens"] == 2000
        assert captured["temperature"] == settings.llm_temperature
        assert captured["model"] == settings.require_model()
        assert "response_format" in captured
        assert json.dumps(captured["reasoning"]) == '{"effort": "high"}'
