"""Intent interpreter abstraction.

The rest of the system only ever talks to :class:`IntentInterpreter`, so the
provider is a factory change in :mod:`app.domains.search.service` and not a
change in any domain logic. Swapping the model, or the vendor, does not touch a
single domain module.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domains.search.schemas import InterpretedIntent


@runtime_checkable
class IntentInterpreter(Protocol):
    """Turns a natural-language query into *structure only*.

    Implementations must never produce products, sellers, prices, offers,
    availability or specifications — those come from the catalogue only.
    """

    @property
    def name(self) -> str: ...  # pragma: no cover - protocol

    async def interpret(self, query: str) -> InterpretedIntent:  # pragma: no cover - protocol
        ...


class InterpreterError(RuntimeError):
    """Raised when a provider cannot produce a valid interpretation."""
