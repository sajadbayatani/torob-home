"""A stubbed LLM endpoint, wired in at the HTTP boundary.

Tests must not reach the network, but they also must not bypass the code under
test. So this fixture patches ``httpx.Client.post`` — the exact call
``app.llm.openrouter`` makes — and returns a well-formed OpenAI-compatible
response. Everything above that line runs for real: the request is built from the
settings, the prompt is assembled from the catalogue, the reply is parsed,
validated against the schema, and checked against the taxonomy.

The stub records what it was asked, so a test can assert the prompt really
carried the catalogue taxonomy rather than a hardcoded phrase list.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

#: A plausible model answer. Individual tests override it to script a response.
DEFAULT_INTENT: dict[str, Any] = {
    "intent": "unknown",
    "category": None,
    "project": None,
    "search": None,
    "constraints": {"quality": None, "budget": None, "notes": []},
    "constraint_kind": "NONE",
    "confidence": 0.5,
    "explanations": [],
}


class LLMStub:
    """Records requests and replays scripted answers."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.reply: dict[str, Any] = json.loads(json.dumps(DEFAULT_INTENT))
        #: set to an exception instance to simulate a transport/provider failure
        self.raises: Exception | None = None
        #: set to a raw string to simulate a fenced or prose-wrapped reply
        self.raw: str | None = None
        #: a complete provider body, replayed verbatim. Used to reproduce the
        #: exact reasoning-model response shapes OpenRouter returns.
        self.body: dict[str, Any] | None = None
        #: an HTTP status to answer with instead of 200
        self.status: int | None = None
        #: Per-call answers, consumed in order, for the flows that call the model
        #: more than once (interpret, then reason). Each entry is a callable that
        #: receives the recorded call and returns the reply text, or an exception
        #: instance to raise. The intent JSON above is only correct for the first
        #: call, so a two-call test has to say what the second one should say.
        self.script: list[Any] = []

    def provider_body(
        self,
        *,
        content: str | None,
        reasoning: str | None = None,
        finish_reason: str = "stop",
        model: str = "test/reasoning-model",
        completion_tokens: int | None = None,
        reasoning_tokens: int | None = None,
        refusal: str | None = None,
    ) -> dict[str, Any]:
        """
        Replay a real OpenRouter response body.

        The shapes are the ones observed against reasoning-capable models:
        ``content`` carries the answer, ``reasoning`` and ``reasoning_details``
        carry the model's private thinking, and ``refusal`` is present but null.
        A model that runs out of budget answers ``content: null`` with
        ``finish_reason: "length"``.
        """
        message: dict[str, Any] = {
            "role": "assistant",
            "content": content,
            "refusal": refusal,
        }
        if reasoning is not None:
            message["reasoning"] = reasoning
            message["reasoning_details"] = [
                {"type": "reasoning.text", "text": reasoning, "format": "unknown"}
            ]
        usage: dict[str, Any] = {"completion_tokens": completion_tokens or 100}
        if reasoning_tokens is not None:
            usage["completion_tokens_details"] = {"reasoning_tokens": reasoning_tokens}
        self.body = {
            "id": "gen-test",
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": finish_reason,
                    "message": message,
                }
            ],
            "usage": usage,
        }
        return self.body

    def answer(self, **fields: Any) -> dict[str, Any]:
        """Set the answer the next call will receive."""
        self.reply = {**json.loads(json.dumps(DEFAULT_INTENT)), **fields}
        self._fill_requirements()
        return self.reply

    def _fill_requirements(self) -> None:
        """
        A project answer carries the project's requirements.

        The requirements are the interpreter's output now — a project used to get
        its needs from a template — so a stub that omitted them would produce a
        project with no requirements at all, which is a different scenario from
        the one most tests mean to describe.

        When a test names its own requirements they are left alone. Otherwise the
        stub does the minimum a real model does with a sentence it has partly
        understood: it reports the need in the user's own words, with the search
        terms taken from those words. There is no table mapping a room to a list
        of things here, and that is the point — if a test needs a specific need,
        it says which one.
        """
        project = self.reply.get("project")
        if not isinstance(project, dict) or self.reply.get("intent") != "project_search":
            return
        if project.get("requirements"):
            return
        source = " ".join(
            str(project.get(key) or "") for key in ("goal", "room")
        ).strip()
        if not source:
            return
        project["requirements"] = [
            {
                "description": source,
                "terms": _words(source),
                "quantity": None,
                "required": True,
                "quality_min": None,
            }
        ]

    def project(
        self,
        *,
        type: str | None = None,
        room: str | None = None,
        room_token: str | None = None,
        goal: str | None = None,
        area_m2: float | None = None,
        requirements: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Answer as a project request.

        ``requirements`` is the project's requirement list, which is the
        interpreter's most important output: a project used to get its needs from
        a template, so a test that does not say which needs it wants would get a
        project with none at all.
        """
        return self.answer(
            intent="project_search",
            project={
                "type": type,
                "room": room,
                "room_token": room_token,
                "area_m2": area_m2,
                "goal": goal,
                "constraints": [],
                "requirements": requirements or [],
            },
            **kwargs,
        )

    def product(self, *, terms: list[str] | None = None, **kwargs: Any) -> dict[str, Any]:
        """Answer as a product request."""
        return self.answer(
            intent="product_search",
            search={"text": None, "terms": terms or [], "brand": None, "color": None},
            **kwargs,
        )

    def bathroom_project(
        self,
        *,
        type: str = "renovation",
        area_m2: float | None = None,
        quality: str | None = None,
        budget: int | None = None,
        room: str | None = "سرویس بهداشتی",
        goal: str | None = None,
        confidence: float = 0.9,
        requirements: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """A bathroom project, as a model reading such a query would answer.

        ``requirements`` is what the project *needs*, which is the model's most
        important output now. A test that cares about which needs the project has
        passes them; one that does not lets the default derivation below stand.
        """
        return self.answer(
            intent="project_search",
            category="bathroom",
            project={
                "type": type,
                "room": room,
                "room_token": None,
                "area_m2": area_m2,
                "goal": goal or "بازسازی سرویس بهداشتی",
                "constraints": [],
                "requirements": requirements or [],
            },
            constraints={"quality": quality, "budget": budget, "notes": []},
            confidence=confidence,
            explanations=["کاربر از انجام یک کار در سرویس بهداشتی گفته است."],
        )

    def product_search(
        self,
        *,
        terms: list[str],
        brand: str | None = None,
        category: str | None = None,
        quality: str | None = None,
        color: str | None = None,
    ) -> dict[str, Any]:
        """A product request, as a model reading such a query would answer.

        No subcategories: the model does not name catalogue slugs, and the
        backend detects them from the catalogue's own labels.
        """
        return self.answer(
            intent="product_search",
            category=category,
            search={
                "text": " ".join(terms),
                "terms": terms,
                "brand": brand,
                "color": color,
            },
            constraints={"quality": quality, "budget": None, "notes": []},
            confidence=0.9,
        )

    def constraint_only(self, *, kind: str, budget: int | None = None, **extra: Any):
        """A query that names a constraint and nothing else."""
        return self.answer(
            intent="unknown",
            constraint_kind=kind,
            constraints={"quality": None, "budget": budget, "notes": []},
            **extra,
        )

    @property
    def last_prompt(self) -> str:
        return self.calls[-1]["user"] if self.calls else ""

    def taxonomy_in_prompt(self) -> set[str]:
        """Every subcategory slug the prompt actually offered the model."""
        prompt = self.last_prompt
        return {
            line.split("|")[0].strip().removeprefix("-").strip()
            for line in prompt.splitlines()
            if line.strip().startswith("-") and "|" in line
        }


def _words(text: str) -> list[str]:
    """The content words of a phrase, the way the catalogue tokeniser sees them."""
    from app.catalog.store import fa_tokens

    return [w for w in fa_tokens(text) if len(w) > 1][:6]


@pytest.fixture(autouse=True)
def llm(monkeypatch: pytest.MonkeyPatch) -> Iterator[LLMStub]:
    """Autouse: every test has an LLM, and no test has a network."""
    stub = LLMStub()
    real_post = httpx.Client.post

    def fake_post(self, url, *args, **kwargs):  # noqa: ANN001, ANN202
        # `TestClient` is itself an `httpx.Client`, so this patch also sees the
        # test's own API calls. Only the LLM endpoint is answered here; anything
        # else goes to the real transport.
        if not str(url).rstrip("/").endswith("/chat/completions"):
            return real_post(self, url, *args, **kwargs)

        payload = kwargs.get("json") or {}
        messages = payload.get("messages") or []
        user = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
        system = next((m.get("content", "") for m in messages if m.get("role") == "system"), "")
        stub.calls.append(
            {
                "url": str(url),
                "model": payload.get("model"),
                "temperature": payload.get("temperature"),
                "max_tokens": payload.get("max_tokens"),
                "system": system,
                "user": user,
                "headers": dict(kwargs.get("headers") or {}),
                "response_format": payload.get("response_format"),
                # recorded even when absent, so a test can tell "not sent" from
                # "sent as something else"
                "reasoning": payload.get("reasoning"),
            }
        )
        if stub.raises is not None:
            raise stub.raises
        if stub.script:
            step = stub.script.pop(0)
            if isinstance(step, BaseException):
                raise step
            if callable(step):
                step = step(stub.calls[-1])
            return httpx.Response(
                200,
                json={
                    "model": "test/model",
                    "choices": [{
                        "index": 0, "finish_reason": "stop",
                        "message": {"role": "assistant", "content": step, "refusal": None},
                    }],
                    "usage": {"completion_tokens": 42},
                },
                request=httpx.Request("POST", str(url)),
            )
        if stub.body is not None:
            return httpx.Response(
                stub.status or 200, json=stub.body, request=httpx.Request("POST", str(url))
            )
        content = stub.raw if stub.raw is not None else json.dumps(stub.reply, ensure_ascii=False)
        body = {
            "model": "test/model",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": content, "refusal": None},
                },
            ],
            "usage": {"completion_tokens": 42},
        }
        return httpx.Response(200, json=body, request=httpx.Request("POST", str(url)))

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    # the real client refuses to run without configuration, so the suite
    # provides it: these are test values, never a real key
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "llm_api_key", "test-key-not-real", raising=False)
    monkeypatch.setattr(settings, "llm_model", "test/model", raising=False)
    yield stub


__all__ = ["DEFAULT_INTENT", "LLMStub", "llm"]
