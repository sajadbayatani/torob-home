"""The model is the one that was configured, and only that one.

The risk this guards against is quiet, not loud: a hardcoded id, a default, or a
fallback that retries against a different model all *work*, and nobody notices
until the bill or the rate-limit budget for an unconfigured model moves. So the
tests here are about what was **requested**, inspected on the wire.

The client has no model parameter at all. ``chat_json`` resolves the model once
from :meth:`Settings.require_model` and threads that same value through every
attempt, so there is no code path that could substitute another.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import LLMNotConfigured, get_settings
from tests.llm_stub import LLMStub

#: a model id nobody would pick by accident, so seeing it anywhere is a failure
CONFIGURED = "qwen/qwen3.8-27b:free"
OTHER = "google/gemini-2.0-flash-001"


@pytest.fixture
def configured_model(monkeypatch: pytest.MonkeyPatch) -> str:
    """Pin the configured model, and make the stub's default agree."""
    monkeypatch.setattr(get_settings(), "llm_model", CONFIGURED, raising=False)
    return CONFIGURED


def requested_models(llm: LLMStub) -> list[str]:
    return [call["model"] for call in llm.calls]


def script_project(
    llm: LLMStub,
    *,
    project_type: str = "renovation",
    area_m2: float | None = None,
    category: str = "bathroom",
) -> LLMStub:
    """A valid project answer, so the request reaches the model and replies.

    `category` is checked against the catalogue, so a reply that omits it is
    rejected before anything can be logged about the model.
    """
    llm.answer(
        intent="project_search",
        project={
            "type": project_type,
            "room": "سرویس بهداشتی",
            "area_m2": area_m2,
            "goal": "بازسازی سرویس بهداشتی",
            "constraints": [],
        },
        category=category,
    )
    return llm


# --------------------------------------------------------------------------- #
# exactly what was configured
# --------------------------------------------------------------------------- #
class TestModelComesFromConfiguration:
    def test_the_configured_id_is_sent_verbatim(
        self, client: TestClient, llm: LLMStub, configured_model: str
    ) -> None:
        script_project(llm)
        client.post("/api/v1/search/interpret", json={"query": "یه نیاز دارم"})
        assert requested_models(llm) == [CONFIGURED]

    @pytest.mark.parametrize(
        "model",
        [
            "qwen/qwen3.8-27b:free",
            "some-vendor/some-model:v1",
            "anthropic/claude-3.5-sonnet",
            "a-model-with-no-slash",
            "vendor/model:with:colons",
        ],
    )
    def test_any_configured_id_is_used_as_is(
        self, client: TestClient, llm: LLMStub, monkeypatch: pytest.MonkeyPatch, model: str
    ) -> None:
        """The setting is not validated, rewritten, or normalised."""
        monkeypatch.setattr(get_settings(), "llm_model", model, raising=False)
        script_project(llm)
        client.post("/api/v1/search/interpret", json={"query": "یه نیاز"})
        assert requested_models(llm) == [model]

    def test_surrounding_whitespace_is_trimmed_not_rewritten(
        self, client: TestClient, llm: LLMStub, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(get_settings(), "llm_model", f"  {CONFIGURED}  ", raising=False)
        script_project(llm)
        client.post("/api/v1/search/interpret", json={"query": "یه نیاز"})
        assert requested_models(llm) == [CONFIGURED]

    def test_the_complementary_selector_uses_the_same_model(
        self, client: TestClient, llm: LLMStub, configured_model: str
    ) -> None:
        """A second feature, one model: no per-feature override."""
        script_project(llm, area_m2=12)
        body = client.post(
            "/api/v1/projects/analyze",
            json={"query": "بازسازی سرویس بهداشتی ۱۲ متری"},
        ).json()
        client.get(f"/api/v1/projects/{body['analysis']['id']}/complementary")

        assert requested_models(llm), "the complementary call should have happened"
        assert set(requested_models(llm)) == {CONFIGURED}

    def test_the_client_takes_no_model_argument(self) -> None:
        """Not configurable per call, so it cannot be overridden per feature."""
        import inspect

        from app.llm import chat_json

        assert "model" not in inspect.signature(chat_json).parameters


# --------------------------------------------------------------------------- #
# a missing model is a configuration error
# --------------------------------------------------------------------------- #
class TestMissingModel:
    @pytest.mark.parametrize("value", ["", "   ", "\n"])
    def test_no_model_means_no_request(
        self, client: TestClient, llm: LLMStub, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        monkeypatch.setattr(get_settings(), "llm_model", value, raising=False)
        response = client.post("/api/v1/search/interpret", json={"query": "بازسازی"})
        assert response.status_code == 503
        assert llm.calls == [], "nothing may be sent when no model is configured"

    def test_the_error_names_the_variable(
        self, client: TestClient, llm: LLMStub, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(get_settings(), "llm_model", "", raising=False)
        with pytest.raises(LLMNotConfigured) as excinfo:
            get_settings().require_model()
        message = str(excinfo.value)
        assert "LLM_MODEL" in message
        # and it says it will not choose one, rather than quietly doing so
        assert "will not choose" in message

    def test_a_blank_model_with_a_valid_key_still_refuses(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = get_settings()
        monkeypatch.setattr(settings, "llm_api_key", "a-key", raising=False)
        monkeypatch.setattr(settings, "llm_model", "  ", raising=False)
        with pytest.raises(LLMNotConfigured):
            settings.require_model()

    def test_settings_expose_no_fallback_field(self) -> None:
        """There is no second model setting to configure, by design."""
        fields = set(get_settings().model_fields)
        assert "llm_model" in fields
        for forbidden in (
            "llm_fallback_model",
            "openrouter_model",
            "openrouter_fallback_model",
            "llm_models",
        ):
            assert forbidden not in fields


# --------------------------------------------------------------------------- #
# every retry stays on the same model
# --------------------------------------------------------------------------- #
class TestRetriesUseTheSameModel:
    def _truncating_then_answering(
        self, monkeypatch: pytest.MonkeyPatch, llm: LLMStub
    ) -> None:
        """First reply is cut off mid-thought; the second answers."""
        import httpx

        real_post = httpx.Client.post
        state = {"n": 0}

        def fake_post(self, url, *args, **kwargs):  # noqa: ANN001, ANN202
            if not str(url).rstrip("/").endswith("/chat/completions"):
                return real_post(self, url, *args, **kwargs)
            state["n"] += 1
            llm.calls.append(
                {
                    "model": (kwargs.get("json") or {}).get("model"),
                    "max_tokens": (kwargs.get("json") or {}).get("max_tokens"),
                    "response_format": (kwargs.get("json") or {}).get("response_format"),
                    "url": str(url),
                }
            )
            request = httpx.Request("POST", str(url))
            if state["n"] == 1:
                return httpx.Response(
                    200,
                    json={"choices": [{"finish_reason": "length",
                                       "message": {"content": None, "reasoning": "thinking"}}]},
                    request=request,
                )
            return httpx.Response(
                200,
                json={"choices": [{"finish_reason": "stop",
                                   "message": {"content": '{"intent": "unknown"}'}}]},
                request=request,
            )

        monkeypatch.setattr(httpx.Client, "post", fake_post)

    def test_truncation_retry_uses_the_same_model(
        self, monkeypatch: pytest.MonkeyPatch, llm: LLMStub, configured_model: str
    ) -> None:
        self._truncating_then_answering(monkeypatch, llm)
        from app.llm import chat_json

        chat_json(system="s", user="u")

        assert len(llm.calls) == 2
        assert requested_models(llm) == [CONFIGURED, CONFIGURED]
        # the retry really did ask for more room, on the same model
        assert llm.calls[1]["max_tokens"] > llm.calls[0]["max_tokens"]

    def test_rate_limit_is_never_retried_against_another_model(
        self, monkeypatch: pytest.MonkeyPatch, llm: LLMStub, configured_model: str
    ) -> None:
        """A 429 for this model stays a 429 for this model."""
        import httpx

        real_post = httpx.Client.post

        def fake_post(self, url, *args, **kwargs):  # noqa: ANN001, ANN202
            if not str(url).rstrip("/").endswith("/chat/completions"):
                return real_post(self, url, *args, **kwargs)
            llm.calls.append({"model": (kwargs.get("json") or {}).get("model"), "url": str(url)})
            return httpx.Response(
                429,
                json={"error": {"message": f"{CONFIGURED} is temporarily rate-limited"}},
                request=httpx.Request("POST", str(url)),
            )

        monkeypatch.setattr(httpx.Client, "post", fake_post)
        from app.llm import LLMUnavailable, chat_json

        with pytest.raises(LLMUnavailable) as excinfo:
            chat_json(system="s", user="u")

        assert "rate limited" in str(excinfo.value)
        assert len(llm.calls) == 1, "a rate limit must not trigger a second request"
        assert requested_models(llm) == [CONFIGURED]

    def test_a_rate_limited_model_surfaces_as_503(
        self, client: TestClient, llm: LLMStub, monkeypatch: pytest.MonkeyPatch,
        configured_model: str
    ) -> None:
        import httpx

        real_post = httpx.Client.post

        def fake_post(self, url, *args, **kwargs):  # noqa: ANN001, ANN202
            if not str(url).rstrip("/").endswith("/chat/completions"):
                return real_post(self, url, *args, **kwargs)
            llm.calls.append({"model": (kwargs.get("json") or {}).get("model"), "url": str(url)})
            return httpx.Response(429, json={"error": {"message": "rate limited"}},
                                 request=httpx.Request("POST", str(url)))

        monkeypatch.setattr(httpx.Client, "post", fake_post)
        response = client.post("/api/v1/search/interpret", json={"query": "بازسازی"})

        assert response.status_code == 503
        assert set(requested_models(llm)) <= {CONFIGURED}

    def test_json_schema_fallback_uses_the_same_model(
        self, monkeypatch: pytest.MonkeyPatch, llm: LLMStub, configured_model: str
    ) -> None:
        """A rejected schema is a format change, never a model change."""
        import httpx

        real_post = httpx.Client.post
        formats: list[str] = []

        def fake_post(self, url, *args, **kwargs):  # noqa: ANN001, ANN202
            if not str(url).rstrip("/").endswith("/chat/completions"):
                return real_post(self, url, *args, **kwargs)
            payload = kwargs.get("json") or {}
            fmt = (payload.get("response_format") or {}).get("type")
            formats.append(fmt)
            llm.calls.append({"model": payload.get("model"), "response_format": fmt})
            request = httpx.Request("POST", str(url))
            if fmt == "json_schema":
                return httpx.Response(
                    400, json={"error": {"message": "json_schema unsupported"}}, request=request
                )
            return httpx.Response(
                200,
                json={"choices": [{"finish_reason": "stop",
                                   "message": {"content": '{"intent": "unknown"}'}}]},
                request=request,
            )

        monkeypatch.setattr(httpx.Client, "post", fake_post)
        from app.llm import chat_json
        from app.domains.search.llm_schema import LLMIntentResponse

        chat_json(system="s", user="u", schema_model=LLMIntentResponse)

        assert formats == ["json_schema", "json_object"]
        assert requested_models(llm) == [CONFIGURED, CONFIGURED]

    def test_a_server_error_does_not_try_another_model(
        self, monkeypatch: pytest.MonkeyPatch, llm: LLMStub, configured_model: str
    ) -> None:
        import httpx

        real_post = httpx.Client.post

        def fake_post(self, url, *args, **kwargs):  # noqa: ANN001, ANN202
            if not str(url).rstrip("/").endswith("/chat/completions"):
                return real_post(self, url, *args, **kwargs)
            llm.calls.append({"model": (kwargs.get("json") or {}).get("model")})
            return httpx.Response(
                503, json={"error": {"message": "upstream unavailable"}},
                request=httpx.Request("POST", str(url)),
            )

        monkeypatch.setattr(httpx.Client, "post", fake_post)
        from app.llm import LLMUnavailable, chat_json

        with pytest.raises(LLMUnavailable):
            chat_json(system="s", user="u")
        assert requested_models(llm) == [CONFIGURED]


# --------------------------------------------------------------------------- #
# nothing unconfigured is ever contacted
# --------------------------------------------------------------------------- #
class TestNoUnconfiguredModel:
    def test_the_source_names_no_model(self) -> None:
        """
        No model id may appear in the application source.

        A literal model id in Python is a fallback waiting to happen: it starts
        working the day the configured model is rate-limited. Prompts legitimately
        contain Persian, so what is forbidden here is a model *identifier*.
        """
        import ast
        import pathlib
        import re

        # e.g. "vendor/model" or "vendor/model:free"
        model_id = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.:-]+$")
        offenders: list[str] = []
        for path in sorted(pathlib.Path("app").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                    continue
                value = node.value.strip()
                if model_id.match(value) and ":" in value:
                    offenders.append(f"{path}:{node.lineno} {value}")
        assert not offenders, "model identifiers hardcoded in source:\n" + "\n".join(offenders)

    def test_no_code_chooses_a_model(self) -> None:
        """No list of models to try, and no loop that varies the model."""
        import pathlib
        import re

        suspicious = re.compile(
            r"(fallback_?models?|models?_to_try|try_?models?|alternate_?model|"
            r"secondary_?model|backup_?model|default_?model)",
            re.IGNORECASE,
        )
        offenders: list[str] = []
        for path in sorted(pathlib.Path("app").rglob("*.py")):
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if suspicious.search(line) and not line.lstrip().startswith("#"):
                    offenders.append(f"{path}:{number} {line.strip()}")
        assert not offenders, "model fallback machinery found:\n" + "\n".join(offenders)

    def test_the_model_field_has_no_default(self) -> None:
        """An empty default means "refuse", not "pick something"."""
        field = get_settings().model_fields["llm_model"]
        assert field.default == ""

    def test_only_one_place_reads_the_setting(self) -> None:
        """`require_model` is the single door; nothing reads the raw field."""
        import pathlib

        readers = []
        for path in sorted(pathlib.Path("app").rglob("*.py")):
            if path.name == "config.py":
                continue
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if "llm_model" in line and "require_model" not in line:
                    readers.append(f"{path}:{number} {line.strip()}")
        assert not readers, "llm_model read outside the settings layer:\n" + "\n".join(readers)


# --------------------------------------------------------------------------- #
# request logging
# --------------------------------------------------------------------------- #
class TestRequestLogging:
    def test_the_log_names_the_model_and_the_attempt(
        self, client: TestClient, llm: LLMStub, configured_model: str,
        caplog: pytest.LogCaptureFixture
    ) -> None:
        script_project(llm)
        with caplog.at_level("INFO", logger="home_procurement.llm"):
            client.post("/api/v1/search/interpret", json={"query": "یه نیاز"})

        logged = caplog.text
        assert CONFIGURED in logged
        assert "attempt=1" in logged

    def test_a_reply_logs_the_finish_reason(
        self, client: TestClient, llm: LLMStub, configured_model: str,
        caplog: pytest.LogCaptureFixture
    ) -> None:
        script_project(llm)
        with caplog.at_level("INFO", logger="home_procurement.llm"):
            client.post("/api/v1/search/interpret", json={"query": "یه نیاز"})

        assert "finish_reason=stop" in caplog.text

    def test_a_rate_limit_logs_status_and_model(
        self, client: TestClient, llm: LLMStub, monkeypatch: pytest.MonkeyPatch,
        configured_model: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        import httpx

        real_post = httpx.Client.post

        def fake_post(self, url, *args, **kwargs):  # noqa: ANN001, ANN202
            if not str(url).rstrip("/").endswith("/chat/completions"):
                return real_post(self, url, *args, **kwargs)
            llm.calls.append({"model": (kwargs.get("json") or {}).get("model")})
            return httpx.Response(429, json={"error": {"message": "rate limited"}},
                                 request=httpx.Request("POST", str(url)))

        monkeypatch.setattr(httpx.Client, "post", fake_post)
        with caplog.at_level("WARNING", logger="home_procurement.llm"):
            client.post("/api/v1/search/interpret", json={"query": "بازسازی"})

        logged = caplog.text
        assert "429" in logged
        assert CONFIGURED in logged
        assert "not switching model" in logged

    def test_the_key_never_reaches_the_log(
        self, client: TestClient, llm: LLMStub, configured_model: str,
        monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        secret = "sk-or-v1-super-secret-value"
        monkeypatch.setattr(get_settings(), "llm_api_key", secret, raising=False)
        script_project(llm)

        with caplog.at_level("DEBUG", logger="home_procurement.llm"):
            client.post("/api/v1/search/interpret", json={"query": "یه نیاز"})

        assert secret not in caplog.text
        assert "<redacted>" in caplog.text
