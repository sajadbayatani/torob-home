"""Application configuration.

Every LLM setting is read from the environment. Nothing about the model, the
endpoint, the site metadata or the key is written in this file: the defaults
below are *defaults*, and a deployment supplies the real values. The key is
backend-only — no endpoint returns it and the frontend never sees it.

The LLM layer is configured in one namespace (``llm_*``) and used by both the
intent interpreter and the complementary-product selector, so there is a single
place to reason about and a single place to rotate a key.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.enums import ReasoningEffort


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Home Procurement Platform API"
    app_version: str = "0.1.0"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"

    # Product catalogue -----------------------------------------------------
    # The product catalogue is a JSON file owned by the backend. It is read from
    # disk on demand (re-read when the file changes), not stored in the database.
    # The path is resolved relative to the backend package when relative.
    # `products_70_enriched.json` is the canonical catalogue: same products as
    # before plus the per-product `metadata` block, used as-is.
    catalog_path: str = "../data/catalog/products_70_enriched.json"

    #: Where products come from. ``local`` is the enriched JSON file and behaves
    #: exactly as it always has; ``torob_mcp`` asks Torob's own MCP server instead.
    #: The default is the file, so a deployment that sets nothing is unaffected.
    product_source: str = "local"
    #: Read only when the source is ``torob_mcp``. Never defaulted to a URL in
    #: code: a deployment that asks for Torob names the server it means.
    torob_mcp_url: str = ""

    database_url: str = "postgresql+psycopg://torob:torob@localhost:5432/torob_home"
    test_database_url: str | None = None
    db_echo: bool = False

    # LLM (backend only) ----------------------------------------------------
    # Any OpenAI-compatible chat-completions endpoint. The intent interpreter
    # and the complementary-product selector both go through this one client.
    llm_api_key: str = ""
    #: no vendor is assumed here either: an empty value means the feature refuses
    #: to run rather than sending traffic somewhere nobody chose
    llm_base_url: str = ""
    #: The single source of truth for which model is ever contacted.
    #:
    #: There is no default and no fallback, deliberately. An empty value here
    #: means the feature refuses to run; it never means "pick something". A
    #: silent default would send traffic to a model nobody chose and nobody is
    #: watching the bill for, which is exactly what a hardcoded id does.
    llm_model: str = Field(default="", min_length=0, max_length=200)
    llm_timeout_seconds: float = Field(default=650.0, gt=0)
    #: 0 keeps the model deterministic, which intent extraction wants
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    #: How hard the model may think before answering. Only the *interpretation*
    #: call sends this; the reasoning calls leave it unset, so this changes what
    #: the interpreter costs and nothing else.
    #:
    #: ``low`` by default. Search interpretation is a small structured task, and a
    #: reasoning model that thinks at length about it tends to spend its whole token
    #: budget before answering — which is the failure the truncation retry exists to
    #: paper over. This makes the cheap path the configured one.
    llm_reasoning_effort: ReasoningEffort = Field(default=ReasoningEffort.LOW)

    llm_max_tokens: int = Field(default=2000, gt=0)
    #: A reasoning model spends tokens before it answers. When it runs out mid-thought
    #: it returns no answer at all, so the request is retried with this much more
    #: room rather than being reported as an outage.
    llm_max_tokens_on_truncation: int = Field(default=6000, gt=0)
    #: attempts when the model ran out of budget rather than failing
    llm_truncation_retries: int = Field(default=1, ge=0, le=3)
    #: sent as HTTP-Referer / X-Title; some providers require them to be present
    llm_referer: str = "https://torob.com"
    llm_title: str = "Home Procurement"
    #: Log the full LLM exchange: the prompt sent and the whole reply, including
    #: the model's `reasoning` and `reasoning_details`, which are otherwise
    #: invisible and are the only way to debug why a model answered as it did.
    #:
    #: Off by default because the prompt contains the user's own words, and this
    #: is a home-procurement app: people type rooms, areas and budgets, and some
    #: will type an address. Turn it on while debugging, off again in production.
    #: The API key is redacted either way.
    llm_log_payloads: bool = False
    #: per-field cap on a logged payload, so one long reasoning trace cannot
    #: flood the log. Set to 0 for no limit.
    llm_log_payload_limit: int = Field(default=20_000, ge=0)

    # Intent interpreter ----------------------------------------------------
    # The interpreter is the LLM. There is no phrase-matching fallback: a query
    # that the model cannot read is reported as an error rather than guessed at
    # with hardcoded keywords.
    intent_taxonomy_max_brands: int = Field(default=40, gt=0)

    # Complementary products ------------------------------------------------
    #: how many products the LLM is shown, and how many it may return
    complementary_candidate_limit: int = Field(default=24, gt=0)
    complementary_max_results: int = Field(default=6, gt=0)

    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:8888",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ]

    @property
    def effective_test_database_url(self) -> str:
        return self.test_database_url or self.database_url

    @property
    def llm_configured(self) -> bool:
        """Whether an LLM call could be attempted at all."""
        return bool(self.llm_api_key.strip() and self.llm_model.strip())

    def require_model(self) -> str:
        """
        The configured model, or a configuration error.

        Every outbound request takes its model from here and nowhere else, so
        there is exactly one place a model id can enter the process, and no way
        for a retry or a fallback to quietly address a different one.
        """
        model = self.llm_model.strip()
        if not model:
            raise LLMNotConfigured(
                "LLM_MODEL is not set; the application will not choose a model for you. "
                "Set LLM_MODEL to the exact model id your provider should be asked for, "
                "for example LLM_MODEL=qwen/qwen3.8-27b:free"
            )
        return model

    def require_llm(self) -> None:
        """
        Fail loudly, and by name, when the LLM is not configured.

        Called by the intent interpreter rather than silently degrading, so a
        missing key is a startup/deployment problem the operator sees instead of
        a search that mysteriously stops understanding anything.
        """
        missing = [
            name
            for name, value in (
                ("LLM_API_KEY", self.llm_api_key),
                ("LLM_MODEL", self.llm_model),
                ("LLM_BASE_URL", self.llm_base_url),
                ("LLM_REASONING_EFFORT", self.llm_reasoning_effort)
            )
            if not value.strip()
        ]
        if missing:
            raise LLMNotConfigured(
                "LLM is not configured; set " + " and ".join(missing) + " in the environment."
            )


class LLMNotConfigured(RuntimeError):
    """The LLM feature was used without the environment it needs."""


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
