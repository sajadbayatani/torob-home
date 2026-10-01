"""Deriving a JSON Schema a structured-output provider will accept.

Pydantic emits a correct JSON Schema, but it uses ``$defs``/``$ref`` for nested
models. Providers that implement strict structured outputs generally expect a
self-contained schema, so the references are inlined here.

The schema is a *request to the provider*, not a guarantee. Free and small models
accept a ``json_schema`` and then answer with something that does not match it,
which is exactly what was observed against the configured model. So this module
produces the best-effort shape, and the Pydantic model in the caller stays the
authority: every reply is validated regardless of what was requested.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

#: JSON Schema keywords a provider may reject, dropped rather than fought over
_UNSUPPORTED = frozenset({"$defs", "definitions", "$id", "$schema", "default", "examples"})


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """
    Replace every ``$ref`` with the definition it points at, recursively.

    Self-referential definitions would recurse forever, so a definition that is
    already being expanded is emitted as a plain object. The Pydantic models this
    is used with are not recursive, so that case does not arise in practice; the
    guard exists so a future model cannot hang the process.
    """
    defs = schema.get("$defs") or schema.get("definitions") or {}

    def resolve(node: Any, seen: frozenset[str]) -> Any:
        if isinstance(node, list):
            return [resolve(item, seen) for item in node]
        if not isinstance(node, dict):
            return node

        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/"):
            name = ref.rsplit("/", 1)[-1]
            if name in seen or name not in defs:
                return {"type": "object"}
            return resolve(defs[name], seen | {name})

        out: dict[str, Any] = {}
        for key, value in node.items():
            if key in _UNSUPPORTED:
                continue
            out[key] = resolve(value, seen)
        # strict structured outputs require this on every object
        if out.get("type") == "object" and "additionalProperties" not in out:
            out["additionalProperties"] = False
        return out

    return resolve(schema, frozenset())


def response_format_for(model: BaseModel, *, name: str = "response") -> dict[str, Any]:
    """
    The ``response_format`` body for a Pydantic model.

    Providers that do not support strict schemas still accept ``json_schema`` and
    ignore the constraints, so a fallback to ``json_object`` is kept by the caller
    for the ones that reject the key outright.
    """
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "strict": True,
            "schema": inline_refs(model.model_json_schema()),
        },
    }


__all__ = ["inline_refs", "response_format_for"]
