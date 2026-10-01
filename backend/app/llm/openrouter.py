"""OpenAI-compatible chat client (backend only).

One client, used by every LLM feature: the intent interpreter and the
complementary-product selector. Configuration comes entirely from the environment
via :class:`app.core.config.Settings`; nothing about the model, the endpoint or
the key is hardcoded here.

The key never leaves this process. No endpoint returns it, and the frontend never
receives it.

Reasoning models
----------------
A reasoning-capable model splits its reply in two, and the split is visible in the
response. Against the configured model, ``choices[0].message`` carries::

    content           the final answer          <- the only thing we parse
    reasoning         chain of thought          <- never parsed
    reasoning_details structured CoT blocks    <- never parsed
    refusal           a refusal, when it refuses

Those last two are *thinking*, not an answer, and parsing them would be both wrong
and unsafe: reasoning text is prose, and prose that happens to contain braces is
not a JSON object the model meant to hand over.

The other shape worth naming is a model that spends its whole token budget
thinking and never gets to the answer::

    finish_reason: "length"
    content:       null
    reasoning:     "..."

That is **not** a provider failure and **not** an empty answer — the request
succeeded. It is a token budget that was too small, so it is reported as
:class:`LLMTruncated` and retried with more room, before anyone is told the LLM
is down.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.enums import ReasoningEffort
from app.core.request_id import current as request_id
from app.llm.schema import response_format_for

logger = logging.getLogger("home_procurement.llm")

#: what the model said it could not help with, when it declines rather than answers
_REFUSAL_KEY = "refusal"
#: fields that hold the model's *answer*. Reasoning is deliberately absent.
_ANSWER_FIELDS = ("content", _REFUSAL_KEY)


class LLMUnavailable(RuntimeError):
    """No usable LLM: not configured, no network, or an unusable response."""


class LLMTruncated(LLMUnavailable):
    """
    The reply succeeded but the model ran out of budget before answering.

    Distinct from :class:`LLMUnavailable` on purpose: the request worked, so
    retrying with a larger budget is the right response and reporting an outage
    would be a lie.
    """


class LLMRefused(LLMUnavailable):
    """The model declined to answer, in its own words."""


class LLMRejected(LLMUnavailable):
    """
    The provider refused the request itself, and retrying will not help.

    A 4xx that survives the response-format fallback is a configuration problem,
    not a busy provider. The common case is a model that does not speak this
    endpoint at all — OpenRouter answers such a request with something like
    "is a decisions model and cannot be used with the chat/completions endpoint".
    Retrying that forever hides a one-line fix in `LLM_MODEL`, so it is reported
    as itself, with the provider's own reason attached.
    """

    def __init__(self, message: str, *, model: str, status: int, reason: str = "") -> None:
        super().__init__(message)
        self.model = model
        self.status = status
        #: what the provider said, verbatim and already truncated
        self.reason = reason


def is_configured() -> bool:
    """Whether an LLM call could be attempted at all."""
    return get_settings().llm_configured


def _endpoint() -> str:
    settings = get_settings()
    return f"{settings.llm_base_url.rstrip('/')}/chat/completions"


def _auth_headers() -> dict[str, str]:
    settings = get_settings()
    return {
        "Authorization": f"Bearer {settings.llm_api_key.strip()}",
        "Content-Type": "application/json",
        "HTTP-Referer": settings.llm_referer,
        "X-Title": settings.llm_title,
    }


def _safe_headers(headers: dict[str, str]) -> dict[str, str]:
    """Headers for a log line: the value is dropped, never the header name."""
    return {k: "<redacted>" for k in headers}


def _clip(value: Any, limit: int) -> str:
    """Render a payload field for a log line, capped so one trace cannot flood it."""
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, default=str)
    else:
        text = str(value)
    if limit and len(text) > limit:
        return f"{text[:limit]}… [+{len(text) - limit} chars truncated]"
    return text


def _log_exchange(
    *,
    direction: str,
    model: str,
    attempt: int,
    system: str,
    user: str,
    body: Any = None,
) -> None:
    """
    Write the full LLM exchange to the log, when asked to.

    A reasoning model puts most of its output in fields the application never
    reads — ``reasoning`` and ``reasoning_details`` — so without this there is no
    way to see why a model answered the way it did, or why it ran out of budget
    mid-thought. Both directions are logged, because half the problem is usually
    in the prompt.

    The API key is never part of this: only ``_safe_headers`` is ever logged, and
    it logs header *names* with the values replaced.
    """
    settings = get_settings()
    if not settings.llm_log_payloads:
        return
    limit = settings.llm_log_payload_limit
    tag = f"LLP {'request' if direction == 'out' else 'reply'} model={model} attempt={attempt}"
    logger.info("%s\n--- system prompt ---\n%s", tag, _clip(system, limit))
    logger.info("%s\n--- user prompt ---\n%s", tag, _clip(user, limit))
    if body is not None:
        logger.info("%s\n--- raw response body ---\n%s", tag, _clip(body, limit))


def _response_format(
    schema_model: type[BaseModel] | None, strict_schema: bool
) -> dict[str, Any]:
    """
    Ask for a JSON object, and for its shape when a schema was supplied.

    A provider that rejects ``json_schema`` is not an outage. The fallback is a
    *response format* change on the same model, never a different model.
    """
    if schema_model is not None and strict_schema:
        return response_format_for(schema_model)
    return {"type": "json_object"}


def chat_json(
    *,
    system: str,
    user: str,
    max_tokens: int | None = None,
    schema_model: type[BaseModel] | None = None,
    strict_schema: bool = True,
    reasoning_effort: ReasoningEffort | None = None,
) -> dict[str, Any]:
    """
    One logical call to **the configured model**, asked for a JSON object.

    There is no model argument, and that is the point. The model is resolved once
    from :meth:`Settings.require_model` and every attempt below reuses that same
    value, so a retry, a budget increase or a response-format fallback cannot
    address a different model even by accident. If ``LLM_MODEL`` is unset this
    raises :class:`~app.core.config.LLMNotConfigured` instead of choosing one.

    ``reasoning_effort`` is **opt-in and per call**. Left unset — the default, and
    what every caller but the search interpreter does — no ``reasoning`` field is
    sent at all, so the provider's own default applies and nothing about those
    calls changes. The interpreter passes its configured value; see
    ``LLM_REASONING_EFFORT``.
    """
    settings = get_settings()
    if not settings.llm_configured:
        settings.require_llm()
    model = settings.require_model()

    attempts = settings.llm_truncation_retries + 1
    budget = max_tokens or settings.llm_max_tokens
    for attempt in range(1, attempts + 1):
        try:
            return _attempt(
                model=model,
                system=system,
                user=user,
                max_tokens=budget,
                schema_model=schema_model,
                strict_schema=strict_schema,
                reasoning_effort=reasoning_effort,
                attempt=attempt,
            )
        except LLMTruncated:
            if attempt >= attempts:
                logger.warning(
                    "no final answer from model=%s after %s attempt(s); giving up",
                    model,
                    attempt,
                )
                raise
            grown = max(budget, settings.llm_max_tokens_on_truncation)
            logger.info(
                "model=%s used its %s-token budget without answering; "
                "attempt %s/%s retries on the same model with max_tokens=%s",
                model,
                budget,
                attempt,
                attempts - 1,
                grown,
            )
            budget = grown
    raise LLMTruncated(f"model {model} produced no answer within its budget")


def _attempt(
    *,
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    schema_model: type[BaseModel] | None,
    strict_schema: bool,
    attempt: int,
    reasoning_effort: ReasoningEffort | None = None,
) -> dict[str, Any]:
    """A single HTTP round trip. ``model`` is passed in and never derived here."""
    settings = get_settings()
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": settings.llm_temperature,
        "max_tokens": max_tokens,
        "response_format": _response_format(schema_model, strict_schema),
    }
    # Added only when the caller asked for it, and only when it differs from the
    # provider's own default, so a call that did not opt in sends a payload byte
    # for byte as it did before this parameter existed.
    if reasoning_effort is not None:
        payload["reasoning"] = {"effort": str(reasoning_effort)}

    # the id sent is the id configured, checked rather than assumed
    assert payload["model"] == settings.require_model(), "model must come from settings"

    format_type = (payload["response_format"] or {}).get("type")
    logger.info(
        "LLM request request_id=%s model=%s attempt=%s endpoint=%s "
        "response_format=%s max_tokens=%s reasoning_effort=%s headers=%s",
        request_id(),
        model,
        attempt,
        settings.llm_base_url.rstrip("/"),
        format_type,
        max_tokens,
        reasoning_effort or "provider-default",
        _safe_headers(_auth_headers()),
    )

    _log_exchange(
        direction="out", model=model, attempt=attempt, system=system, user=user
    )

    try:
        with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
            response = client.post(_endpoint(), headers=_auth_headers(), json=payload)
    except httpx.HTTPError as exc:  # network, timeout, DNS
        logger.warning("LLM transport error model=%s attempt=%s: %s", model, attempt, exc)
        raise LLMUnavailable(f"LLM request failed: {exc}") from exc

    if response.status_code in (400, 404, 415, 422) and strict_schema:
        # The provider will not take a json_schema. Retry the SAME model asking
        # for a plain JSON object. This changes the response format only; the
        # model is untouched, and it is not a model fallback.
        logger.info(
            "model=%s rejected json_schema (status=%s); retrying the same model "
            "with json_object",
            model,
            response.status_code,
        )
        payload["response_format"] = {"type": "json_object"}
        try:
            with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
                response = client.post(_endpoint(), headers=_auth_headers(), json=payload)
        except httpx.HTTPError as exc:
            logger.warning("LLM transport error model=%s attempt=%s: %s", model, attempt, exc)
            raise LLMUnavailable(f"LLM request failed: {exc}") from exc

    if response.status_code == 429:
        # A rate limit is this model's problem to be told about. Switching models
        # here would send traffic somewhere nobody configured, so it is surfaced.
        logger.warning(
            "model=%s attempt=%s rate limited (429); not switching model",
            model,
            attempt,
        )
        raise LLMUnavailable(f"LLM provider is rate limited for model {model}; retry shortly")

    if response.status_code != 200:
        # a 4xx that is still here after the format fallback is a configuration
        # problem: retrying cannot fix it, and saying "try again" would send the
        # operator looking in the wrong place
        if 400 <= response.status_code < 500:
            reason = _provider_reason(response)
            logger.error(
                "model=%s attempt=%s rejected by the provider (status=%s): %s",
                model,
                attempt,
                response.status_code,
                reason,
            )
            raise LLMRejected(
                f"the provider rejected the request for model {model} "
                f"(status {response.status_code})",
                model=model,
                status=response.status_code,
                reason=reason,
            )
        logger.warning(
            "model=%s attempt=%s unexpected status %s", model, attempt, response.status_code
        )
        raise LLMUnavailable(
            f"LLM endpoint returned {response.status_code} for model {model}: "
            f"{response.text[:200]}"
        )

    raw_text = response.text
    _log_exchange(
        direction="in", model=model, attempt=attempt, system=system, user=user,
        body=raw_text,
    )

    try:
        body = response.json()
    except json.JSONDecodeError as exc:
        raise LLMUnavailable("LLM endpoint returned a non-JSON body") from exc

    result = extract_json_object(body, model=model, attempt=attempt)
    metrics = _call_metrics(body)
    logger.info(
        "LLM reply request_id=%s model=%s attempt=%s finish_reason=%s "
        "prompt_tokens=%s cached_tokens=%s completion_tokens=%s prompt_ms=%s "
        "predicted_ms=%s tokens_per_second=%s",
        request_id(),
        model,
        attempt,
        ((body.get("choices") or [{}])[0] or {}).get("finish_reason"),
        metrics["prompt_tokens"],
        metrics["cached_tokens"],
        metrics["completion_tokens"],
        None if metrics["prompt_ms"] is None else round(metrics["prompt_ms"]),
        None if metrics["predicted_ms"] is None else round(metrics["predicted_ms"]),
        None if metrics["tokens_per_second"] is None else round(metrics["tokens_per_second"], 1),
    )
    return result


def extract_json_object(
    body: dict[str, Any], *, model: str = "", attempt: int | None = None
) -> dict[str, Any]:
    """
    Pull the model's final answer out of an OpenAI-compatible response body.

    Only the answer fields are read. ``reasoning`` and ``reasoning_details`` are
    present in every reply from a reasoning model and are ignored on purpose: they
    are the model's private working, not something it meant to hand over.
    """
    choices = body.get("choices") or []
    if not choices:
        raise LLMUnavailable("LLM returned no choices")

    choice = choices[0] or {}
    message = choice.get("message") or choice.get("delta") or {}
    finish_reason = choice.get("finish_reason")

    # what the reply looked like, for a failure message. Never the key, and never
    # the reasoning or the prompt.
    # which model actually answered, which we asked, and how hard we tried.
    # `body["model"]` can differ from the id requested (a provider may route to a
    # specific build), so both are recorded.
    meta = {
        "requested_model": model or None,
        "model": body.get("model") or None,
        "attempt": attempt,
        "finish_reason": finish_reason,
        "message_fields": sorted(message) if isinstance(message, dict) else [],
        "usage": _call_metrics(body),
    }

    if not isinstance(message, dict):
        raise LLMUnavailable(f"LLM returned an unexpected message: {meta}")

    truncated = finish_reason in ("length", "max_tokens")

    for field in _ANSWER_FIELDS:
        value = message.get(field)
        if isinstance(value, str) and value.strip():
            if field == _REFUSAL_KEY:
                raise LLMRefused(f"the model declined to answer: {value[:200]}")
            try:
                return parse_json_object(value, meta=meta)
            except LLMUnavailable:
                # Content that will not parse, from a reply the provider says ran
                # out of budget, is the same problem as no content at all: the
                # model was still talking when the budget ended. Reported as
                # truncation so the caller retries with more room.
                if truncated:
                    raise LLMTruncated(
                        "the model hit its token budget and the answer was cut off "
                        f"mid-JSON; raise llm_max_tokens. {meta}"
                    ) from None
                raise
        # an explicit refusal with content absent is still a refusal
        if field == _REFUSAL_KEY and isinstance(value, str) and value.strip() == "":
            continue

    # content was empty. The usual cause is a model that spent the whole budget
    # thinking, which is a sizing problem rather than an outage.
    if truncated:
        raise LLMTruncated(
            "the model used its whole token budget reasoning and produced no answer; "
            f"raise llm_max_tokens or lower reasoning. {meta}"
        )

    raise LLMUnavailable(
        "LLM returned a message with no final answer "
        f"(reasoning is never used as an answer): {meta}"
    )


def _provider_reason(response: httpx.Response) -> str:
    """
    The provider's own explanation, if it sent one.

    OpenRouter puts it in ``error.message``; a proxy may put it in ``detail``.
    The whole thing is truncated, and the key is never included.
    """
    try:
        body = response.json()
    except (json.JSONDecodeError, ValueError):
        return response.text[:200].strip()
    if not isinstance(body, dict):
        return response.text[:200].strip()
    error = body.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return error["message"][:300]
    if isinstance(error, str):
        return error[:300]
    for key in ("detail", "message"):
        if isinstance(body.get(key), str):
            return body[key][:300]
    return response.text[:200].strip()


def _call_metrics(body: dict[str, Any]) -> dict[str, Any]:
    """
    Everything needed to compare two inferences: sizes, timings, and why it stopped.

    OpenRouter and OpenAI-compatible servers disagree on where timings live —
    some put them in ``usage``, some in a sibling ``timings`` object — so both are
    read. Absent fields are simply missing rather than zero, so a server that
    reports no timings is not mistaken for a fast one.
    """
    usage = body.get("usage") or {}
    timings = body.get("timings") or {}
    if not isinstance(usage, dict):
        usage = {}
    if not isinstance(timings, dict):
        timings = {}
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
    out: dict[str, Any] = {
        "prompt_tokens": usage.get("prompt_tokens"),
        "cached_tokens": cached,
        "completion_tokens": usage.get("completion_tokens"),
        "prompt_ms": timings.get("prompt_ms"),
        "predicted_ms": timings.get("predicted_ms"),
        "tokens_per_second": timings.get("predicted_per_second"),
    }
    detail = usage.get("completion_tokens_details") or {}
    if isinstance(detail, dict) and detail.get("reasoning_tokens") is not None:
        out["reasoning_tokens"] = detail["reasoning_tokens"]
    return out


def parse_json_object(content: str, *, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Parse a JSON object, tolerating a ```json fence or surrounding prose."""
    where = f" {meta}" if meta else ""
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else text
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        # a model that wrapped the object in prose: take the outermost braces
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise LLMUnavailable(f"response was not a JSON object{where}") from exc
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError as inner:
            raise LLMUnavailable(f"response was not a JSON object{where}") from inner
    if not isinstance(parsed, dict):
        raise LLMUnavailable(f"response JSON was not an object{where}")
    return parsed


__all__ = [
    "LLMRefused",
    "LLMTruncated",
    "LLMUnavailable",
    "chat_json",
    "extract_json_object",
    "is_configured",
    "parse_json_object",
]
