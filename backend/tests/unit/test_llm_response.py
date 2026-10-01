"""Reading the model's final answer out of a reasoning-model response.

The shapes here were captured from real OpenRouter replies from reasoning-capable
models, not invented. A reasoning model splits its reply in two::

    content            the answer          <- the only field parsed
    reasoning          chain of thought    <- never parsed
    reasoning_details  CoT blocks          <- never parsed
    refusal            present, usually null

and a model that runs out of budget mid-thought replies with no answer at all::

    finish_reason: "length"
    content:       null
    reasoning:     "..."

The second case is the bug this file exists for. The request *succeeded*; the
model simply spent its whole budget thinking. Treating that as an LLM failure
turns a sizing problem into an outage, and hides the fact that raising
``LLM_MAX_TOKENS`` fixes it.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.llm import LLMRefused, LLMTruncated, LLMUnavailable, chat_json
from app.llm.openrouter import extract_json_object, parse_json_object
from app.domains.search.llm_schema import LLMIntentResponse
from tests.llm_stub import LLMStub

ANSWER = {
    "intent": "product_search",
    "category": "bathroom",
    "project": None,
    "search": {"text": "شیر توالت", "terms": ["شیر توالت"], "brand": None, "color": None},
    "constraints": {"quality": None, "budget": None, "notes": []},
    "constraint_kind": "NONE",
    "confidence": 0.9,
    "explanations": ["کاربر یک محصول مشخص می‌خواهد."],
}

#: a real chain of thought, of the kind these models emit
THINKING = (
    "Okay, the user wants a toilet flush valve. Let me reason about this step by "
    "step. First, the category is plumbing, then the subcategory... Actually, "
    'maybe I should output {"intent": "project_search"} instead, no, that is wrong.'
)


def body(**kwargs) -> dict:
    return extract_json_object(kwargs["raw_body"], model="test/model")


# --------------------------------------------------------------------------- #
# the ordinary case
# --------------------------------------------------------------------------- #
class TestNormalResponse:
    def test_reads_the_answer_from_content(self) -> None:
        raw = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(ANSWER)}}]}
        assert body(raw_body=raw) == ANSWER

    def test_a_plain_content_string_still_works(self) -> None:
        raw = {"choices": [{"message": {"role": "assistant", "content": '{"a": 1}'}}]}
        assert body(raw_body=raw) == {"a": 1}

    def test_the_endpoint_produces_a_validated_intent(
        self, client: TestClient, llm: LLMStub
    ) -> None:
        llm.provider_body(content=json.dumps(ANSWER, ensure_ascii=False))
        response = client.post(
            "/api/v1/search/interpret", json={"query": "یه شیر توالت خوب میخوام"}
        )
        assert response.status_code == 200
        result = response.json()
        assert result["intent"] == "PRODUCT_SEARCH"
        assert result["matched_subcategories"] == ["toilet"]


# --------------------------------------------------------------------------- #
# reasoning alongside a real answer
# --------------------------------------------------------------------------- #
class TestReasoningWithContent:
    def test_content_wins_over_reasoning(self) -> None:
        """The thinking can even contain JSON; it must not be read."""
        raw = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(ANSWER),
                        "reasoning": THINKING,
                        "reasoning_details": [
                            {"type": "reasoning.text", "text": THINKING}
                        ],
                        "refusal": None,
                    },
                }
            ]
        }
        assert body(raw_body=raw) == ANSWER

    def test_a_json_decoy_in_the_reasoning_is_ignored(self) -> None:
        """This is the failure the old parser could have had."""
        decoy = {"intent": "project_search", "project": {"type": "renovation"}}
        raw = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": json.dumps(ANSWER),
                        "reasoning": f"I considered {json.dumps(decoy)} but that is wrong.",
                    },
                }
            ]
        }
        result = body(raw_body=raw)
        assert result["intent"] == "product_search"
        assert result["project"] is None

    def test_the_endpoint_handles_it_end_to_end(
        self, client: TestClient, llm: LLMStub
    ) -> None:
        llm.provider_body(
            content=json.dumps(ANSWER, ensure_ascii=False),
            reasoning=THINKING,
            reasoning_tokens=1648,
            completion_tokens=1752,
        )
        response = client.post(
            "/api/v1/search/interpret", json={"query": "یه شیر توالت خوب میخوام"}
        )
        assert response.status_code == 200
        assert response.json()["intent"] == "PRODUCT_SEARCH"


# --------------------------------------------------------------------------- #
# reasoning only: the reported bug
# --------------------------------------------------------------------------- #
class TestReasoningOnly:
    #: exactly the response that produced "LLM returned an empty message"
    TRUNCATED = {
        "model": "test/reasoning-model",
        "choices": [
            {
                "finish_reason": "length",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "refusal": None,
                    "reasoning": THINKING,
                    "reasoning_details": [
                        {"type": "reasoning.text", "text": THINKING}
                    ],
                },
            }
        ],
        "usage": {"completion_tokens": 2000, "completion_tokens_details": {"reasoning_tokens": 2270}},
    }

    def test_is_a_truncation_not_an_outage(self) -> None:
        """The request worked; the model just ran out of budget thinking."""
        with pytest.raises(LLMTruncated) as excinfo:
            body(raw_body=self.TRUNCATED)
        assert "budget" in str(excinfo.value)

    def test_empty_string_content_is_also_a_truncation(self) -> None:
        raw = {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {"content": "", "reasoning": THINKING},
                }
            ]
        }
        with pytest.raises(LLMTruncated):
            body(raw_body=raw)

    def test_the_reasoning_is_never_used_as_the_answer(self) -> None:
        """Even when the reasoning happens to contain a brace, it is not the answer."""
        with pytest.raises(LLMTruncated):
            body(raw_body=self.TRUNCATED)

    def test_a_missing_key_is_reported_by_name(self) -> None:
        """An absent answer is not automatically a truncation."""
        raw = {"choices": [{"finish_reason": "stop", "message": {"content": None}}]}
        with pytest.raises(LLMUnavailable) as excinfo:
            body(raw_body=raw)
        assert not isinstance(excinfo.value, LLMTruncated)
        assert "no final answer" in str(excinfo.value)

    def test_a_truncated_reply_is_retried_with_a_bigger_budget(self) -> None:
        """The first attempt runs out mid-thought; the second is given more room."""
        import httpx

        budgets: list[int] = []
        real_post = httpx.Client.post

        def fake_post(self, url, *args, **kwargs):  # noqa: ANN001, ANN202
            if not str(url).rstrip("/").endswith("/chat/completions"):
                return real_post(self, url, *args, **kwargs)
            payload = kwargs.get("json") or {}
            budgets.append(payload.get("max_tokens"))
            request = httpx.Request("POST", str(url))
            if len(budgets) == 1:
                return httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "finish_reason": "length",
                                "message": {"content": None, "reasoning": THINKING},
                            }
                        ],
                        "usage": {"completion_tokens": payload.get("max_tokens")},
                    },
                    request=request,
                )
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"finish_reason": "stop", "message": {"content": json.dumps(ANSWER)}}
                    ]
                },
                request=request,
            )

        httpx.Client.post = fake_post
        try:
            from app.core.config import get_settings
            from app.domains.search.llm_interpreter import LLMInterpreter

            settings = get_settings()
            result = LLMInterpreter()._call(system="s", user="u")

            assert result == ANSWER
            # the retry really did ask for more room
            assert len(budgets) == 2
            assert budgets[1] > budgets[0]
            assert budgets[0] == settings.llm_max_tokens
            assert budgets[1] == settings.llm_max_tokens_on_truncation
        finally:
            httpx.Client.post = real_post

    def test_the_retry_is_bounded(self) -> None:
        """A model that never answers must not loop forever."""
        import httpx

        calls = 0
        real_post = httpx.Client.post

        def fake_post(self, url, *args, **kwargs):  # noqa: ANN001, ANN202
            nonlocal calls
            if not str(url).rstrip("/").endswith("/chat/completions"):
                return real_post(self, url, *args, **kwargs)
            calls += 1
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "length",
                            "message": {"content": None, "reasoning": THINKING},
                        }
                    ]
                },
                request=httpx.Request("POST", str(url)),
            )

        httpx.Client.post = fake_post
        try:
            from app.core.config import get_settings
            from app.domains.search.llm_interpreter import LLMInterpreter

            with pytest.raises(LLMTruncated):
                LLMInterpreter()._call(system="s", user="u")
            assert calls == get_settings().llm_truncation_retries + 1
        finally:
            httpx.Client.post = real_post

    def test_a_healthy_reply_is_not_retried(
        self, client: TestClient, llm: LLMStub
    ) -> None:
        llm.provider_body(content=json.dumps(ANSWER, ensure_ascii=False))
        client.post("/api/v1/search/interpret", json={"query": "یه شیر توالت"})
        assert len(llm.calls) == 1


# --------------------------------------------------------------------------- #
# refusals and malformed content
# --------------------------------------------------------------------------- #
class TestRefusal:
    def test_a_refusal_is_its_own_error(self) -> None:
        raw = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": None, "refusal": "I cannot help with that."},
                }
            ]
        }
        with pytest.raises(LLMRefused) as excinfo:
            body(raw_body=raw)
        assert "cannot help" in str(excinfo.value)


class TestMalformedContent:
    def test_text_that_is_not_json_is_an_error(self) -> None:
        raw = {"choices": [{"message": {"content": "I am not going to answer."}}]}
        with pytest.raises(LLMUnavailable) as excinfo:
            body(raw_body=raw)
        assert "not a JSON object" in str(excinfo.value)

    def test_broken_json_is_an_error(self) -> None:
        raw = {"choices": [{"message": {"content": '{"intent": "product_search",}'}}]}
        with pytest.raises(LLMUnavailable):
            body(raw_body=raw)

    def test_a_json_array_is_not_an_object(self) -> None:
        raw = {"choices": [{"message": {"content": "[1, 2, 3]"}}]}
        with pytest.raises(LLMUnavailable) as excinfo:
            body(raw_body=raw)
        assert "not an object" in str(excinfo.value)

    def test_a_fenced_reply_is_still_read(self) -> None:
        raw = {"choices": [{"message": {"content": f"```json\n{json.dumps(ANSWER)}\n```"}}]}
        assert body(raw_body=raw) == ANSWER

    def test_prose_around_the_object_is_still_read(self) -> None:
        text = "درخواست شما یک جست‌وجوی محصول است:\n" + json.dumps(ANSWER) + "\nامیدوارم مفید باشد."
        raw = {"choices": [{"message": {"content": text}}]}
        assert body(raw_body=raw) == ANSWER


# --------------------------------------------------------------------------- #
# the schema is the last line of defence
# --------------------------------------------------------------------------- #
class TestSchemaValidationIsTheBoundary:
    def test_well_formed_json_that_is_the_wrong_shape_is_rejected(self) -> None:
        """A free model will happily answer with the wrong keys."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            LLMIntentResponse.model_validate({"intent": "buy_now"})

    def test_a_free_model_ignoring_the_enum_is_caught(self) -> None:
        """Observed for real: a small free model returned "Plumbing Fixture"."""
        from pydantic import ValidationError

        bad = {**ANSWER, "intent": "Plumbing Fixture"}
        with pytest.raises(ValidationError):
            LLMIntentResponse.model_validate(bad)

    def test_smuggled_catalogue_data_is_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            LLMIntentResponse.model_validate({**ANSWER, "products": [{"id": "x"}]})

    def test_the_endpoint_refuses_a_reply_that_fails_validation(
        self, client: TestClient, llm: LLMStub
    ) -> None:
        llm.provider_body(content=json.dumps({**ANSWER, "intent": "buy_now"}))
        response = client.post("/api/v1/search/interpret", json={"query": "یه چیزی"})
        assert response.status_code == 503


# --------------------------------------------------------------------------- #
# what gets asked for, and what gets logged
# --------------------------------------------------------------------------- #
class TestRequestAndLogging:
    def test_a_json_schema_is_requested(self, client: TestClient, llm: LLMStub) -> None:
        llm.provider_body(content=json.dumps(ANSWER, ensure_ascii=False))
        client.post("/api/v1/search/interpret", json={"query": "یه شیر توالت"})

        body = llm.calls[0]
        assert body["response_format"]["type"] == "json_schema"
        schema = body["response_format"]["json_schema"]["schema"]
        assert schema["additionalProperties"] is False
        # self-contained: providers that reject $defs get a schema that works
        assert "$defs" not in json.dumps(schema)
        assert "$ref" not in json.dumps(schema)
        assert schema["properties"]["intent"]["enum"] == [
            "product_search",
            "project_search",
            "unknown",
        ]

    def test_a_provider_that_rejects_the_schema_still_works(
        self, client: TestClient, llm: LLMStub, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Response formatting is not worth failing a search over."""
        import httpx

        seen: list[dict] = []
        real_post = httpx.Client.post

        def fake_post(self, url, *args, **kwargs):  # noqa: ANN001, ANN202
            # `TestClient` is an `httpx.Client`; only the LLM endpoint is ours
            if not str(url).rstrip("/").endswith("/chat/completions"):
                return real_post(self, url, *args, **kwargs)
            fmt = (kwargs.get("json") or {}).get("response_format") or {}
            seen.append(fmt.get("type"))
            request = httpx.Request("POST", str(url))
            if fmt.get("type") == "json_schema":
                return httpx.Response(
                    400,
                    json={"error": {"message": "response_format json_schema unsupported"}},
                    request=request,
                )
            return httpx.Response(
                200,
                json={"choices": [{"finish_reason": "stop",
                                   "message": {"content": json.dumps(ANSWER)}}]},
                request=request,
            )

        monkeypatch.setattr(httpx.Client, "post", fake_post)
        try:
            response = client.post(
                "/api/v1/search/interpret", json={"query": "یه شیر توالت"}
            )
            assert response.status_code == 200
            assert seen == ["json_schema", "json_object"]
        finally:
            httpx.Client.post = real_post

    def test_the_prompt_forbids_prose_around_the_json(
        self, client: TestClient, llm: LLMStub
    ) -> None:
        llm.provider_body(content=json.dumps(ANSWER, ensure_ascii=False))
        client.post("/api/v1/search/interpret", json={"query": "یه شیر توالت"})

        system = llm.calls[0]["system"]
        assert "markdown" in system
        assert "فقط" in system  # "only"

    def test_a_failure_logs_metadata_and_never_the_key(
        self, client: TestClient, llm: LLMStub, caplog: pytest.LogCaptureFixture
    ) -> None:
        from app.core.config import get_settings

        secret = get_settings().llm_api_key
        llm.provider_body(
            content=None,
            reasoning=THINKING,
            finish_reason="length",
            completion_tokens=2000,
            reasoning_tokens=1990,
        )

        with caplog.at_level("WARNING"):
            response = client.post("/api/v1/search/interpret", json={"query": "یه نیاز"})

        assert response.status_code == 503
        logged = caplog.text
        # the useful diagnosis is there
        assert "reasoning_tokens" in logged
        assert "length" in logged
        # and nothing sensitive is
        assert secret not in logged
        assert "Authorization" not in logged
        assert THINKING[:40] not in logged

    def test_the_response_is_not_echoed_into_a_user_facing_error(
        self, client: TestClient, llm: LLMStub
    ) -> None:
        llm.raw = "I cannot answer that."
        response = client.post("/api/v1/search/interpret", json={"query": "یه نیاز"})
        assert response.status_code == 503
        assert "I cannot answer that." not in response.text


# --------------------------------------------------------------------------- #
# parse_json_object on its own
# --------------------------------------------------------------------------- #
class TestParseJsonObject:
    @pytest.mark.parametrize(
        "text",
        [
            '{"a": 1}',
            '  {"a": 1}  ',
            '```json\n{"a": 1}\n```',
            '```\n{"a": 1}\n```',
            'prose {"a": 1} more prose',
        ],
    )
    def test_accepts_the_shapes_models_actually_send(self, text: str) -> None:
        assert parse_json_object(text) == {"a": 1}

    @pytest.mark.parametrize("text", ["not json", "", "[]", "null", "42"])
    def test_refuses_the_shapes_it_must(self, text: str) -> None:
        with pytest.raises(LLMUnavailable):
            parse_json_object(text)


# --------------------------------------------------------------------------- #
# cut off mid-JSON is the same problem as no answer
# --------------------------------------------------------------------------- #
class TestTruncatedMidAnswer:
    """A reply the provider says ran out of budget, whatever state it is in."""

    def test_prose_cut_off_by_the_budget_is_a_truncation(self) -> None:
        """Observed for real: content held prose, `finish_reason` was "length"."""
        raw = {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {
                        "content": "Let me think about this. First, the user wants a "
                        "bathroom renovation, so the project type is renovation and",
                        "reasoning": THINKING,
                    },
                }
            ]
        }
        with pytest.raises(LLMTruncated) as excinfo:
            body(raw_body=raw)
        assert "llm_max_tokens" in str(excinfo.value)

    def test_json_cut_off_mid_object_is_a_truncation(self) -> None:
        raw = {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {"content": '{"intent": "project_search", "catalog": {"sub'},
                }
            ]
        }
        with pytest.raises(LLMTruncated):
            body(raw_body=raw)

    def test_unparseable_content_that_finished_is_still_an_error(self) -> None:
        """`finish_reason: stop` means the model chose to say that."""
        raw = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": "I am not going to answer with JSON."},
                }
            ]
        }
        with pytest.raises(LLMUnavailable) as excinfo:
            body(raw_body=raw)
        assert not isinstance(excinfo.value, LLMTruncated)

    def test_the_retry_recovers_from_a_mid_answer_truncation(self) -> None:
        import httpx

        budgets: list[int] = []
        real_post = httpx.Client.post

        def fake_post(self, url, *args, **kwargs):  # noqa: ANN001, ANN202
            if not str(url).rstrip("/").endswith("/chat/completions"):
                return real_post(self, url, *args, **kwargs)
            payload = kwargs.get("json") or {}
            budgets.append(payload.get("max_tokens"))
            request = httpx.Request("POST", str(url))
            if len(budgets) == 1:
                return httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "finish_reason": "length",
                                "message": {"content": "I was thinking about"},
                            }
                        ]
                    },
                    request=request,
                )
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"finish_reason": "stop", "message": {"content": json.dumps(ANSWER)}}
                    ]
                },
                request=request,
            )

        httpx.Client.post = fake_post
        try:
            from app.domains.search.llm_interpreter import LLMInterpreter

            assert LLMInterpreter()._call(system="s", user="u") == ANSWER
            assert len(budgets) == 2 and budgets[1] > budgets[0]
        finally:
            httpx.Client.post = real_post


# --------------------------------------------------------------------------- #
# a provider that refuses the request itself
# --------------------------------------------------------------------------- #
class TestProviderRejection:
    """
    A 4xx that survives the response-format fallback is a configuration fault.

    The real case: OpenRouter answers a request for a *decisions* model on
    /chat/completions with "is a decisions model and cannot be used with the
    chat/completions endpoint". Retrying that forever hides a one-line fix in
    LLM_MODEL, so it is reported as itself, with the provider's own reason.
    """

    REASON = (
        "respan/span-01-lite:free is a decisions model and cannot be used with the "
        "chat/completions endpoint. Use the /api/alpha/decisions endpoint instead."
    )

    def _rejecting(
        self, monkeypatch: pytest.MonkeyPatch, llm: LLMStub, status: int = 400
    ) -> None:
        import httpx

        real_post = httpx.Client.post
        reason = self.REASON  # `self` inside the fake is the httpx.Client

        def fake_post(client, url, *args, **kwargs):  # noqa: ANN001, ANN202
            if not str(url).rstrip("/").endswith("/chat/completions"):
                return real_post(client, url, *args, **kwargs)
            llm.calls.append({"model": (kwargs.get("json") or {}).get("model")})
            return httpx.Response(
                status,
                json={"error": {"message": reason, "code": status}, "user_id": "u"},
                request=httpx.Request("POST", str(url)),
            )

        monkeypatch.setattr(httpx.Client, "post", fake_post)

    def test_is_reported_as_a_rejection_not_an_outage(
        self, monkeypatch: pytest.MonkeyPatch, llm: LLMStub
    ) -> None:
        from app.llm import LLMRejected

        self._rejecting(monkeypatch, llm)
        with pytest.raises(LLMRejected) as excinfo:
            chat_json(system="s", user="u")
        assert excinfo.value.status == 400
        assert self.REASON in excinfo.value.reason

    def test_the_provider_reason_is_extracted(self) -> None:
        import httpx

        from app.llm.openrouter import _provider_reason

        response = httpx.Response(
            400, json={"error": {"message": self.REASON, "code": 400}}
        )
        assert _provider_reason(response) == self.REASON

    def test_it_is_not_retried_as_an_outage(
        self, monkeypatch: pytest.MonkeyPatch, llm: LLMStub
    ) -> None:
        """One format probe, then the rejection surfaces. No budget retry loop."""
        from app.llm import LLMRejected

        self._rejecting(monkeypatch, llm)
        with pytest.raises(LLMRejected):
            chat_json(system="s", user="u", schema_model=LLMIntentResponse)
        # the json_schema attempt and the json_object attempt, and nothing else
        assert len(llm.calls) == 2

    def test_the_model_is_never_changed_to_escape_it(
        self, monkeypatch: pytest.MonkeyPatch, llm: LLMStub
    ) -> None:
        """A rejection is a reason to fix LLM_MODEL, not to try another model."""
        from app.llm import LLMRejected

        self._rejecting(monkeypatch, llm)
        with pytest.raises(LLMRejected):
            chat_json(system="s", user="u")
        assert {c["model"] for c in llm.calls} == {get_settings().llm_model}

    def test_the_endpoint_reports_a_configuration_fault(
        self, client: TestClient, llm: LLMStub, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._rejecting(monkeypatch, llm)
        response = client.post("/api/v1/search/interpret", json={"query": "بازسازی"})

        # not the 503 "try again later", which would send the operator chasing
        # a transient problem that will never resolve
        assert response.status_code == 502
        assert "پیکربندی" in response.json()["detail"]

    def test_the_response_does_not_leak_provider_internals(
        self, client: TestClient, llm: LLMStub, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The user-facing message stays generic; the reason is for the log."""
        self._rejecting(monkeypatch, llm)
        response = client.post("/api/v1/search/interpret", json={"query": "بازسازی"})
        assert "decisions model" not in response.text
        assert "span-01-lite" not in response.text

    def test_a_5xx_is_still_a_transient_outage(
        self, monkeypatch: pytest.MonkeyPatch, llm: LLMStub
    ) -> None:
        """The rejection path is for 4xx only; a provider outage stays retryable."""
        from app.llm import LLMRejected, LLMUnavailable

        import httpx

        real_post = httpx.Client.post

        def fake_post(self, url, *args, **kwargs):  # noqa: ANN001, ANN202
            if not str(url).rstrip("/").endswith("/chat/completions"):
                return real_post(self, url, *args, **kwargs)
            return httpx.Response(
                503, json={"error": {"message": "upstream unavailable"}},
                request=httpx.Request("POST", str(url)),
            )

        monkeypatch.setattr(httpx.Client, "post", fake_post)
        with pytest.raises(LLMUnavailable) as excinfo:
            chat_json(system="s", user="u")
        assert not isinstance(excinfo.value, LLMRejected)

    def test_a_non_json_error_body_does_not_crash(
        self, monkeypatch: pytest.MonkeyPatch, llm: LLMStub
    ) -> None:
        from app.llm import LLMRejected

        import httpx

        real_post = httpx.Client.post

        def fake_post(self, url, *args, **kwargs):  # noqa: ANN001, ANN202
            if not str(url).rstrip("/").endswith("/chat/completions"):
                return real_post(self, url, *args, **kwargs)
            return httpx.Response(
                400, text="<html>Bad Request</html>",
                request=httpx.Request("POST", str(url)),
            )

        monkeypatch.setattr(httpx.Client, "post", fake_post)
        with pytest.raises(LLMRejected) as excinfo:
            chat_json(system="s", user="u")
        assert "Bad Request" in excinfo.value.reason
