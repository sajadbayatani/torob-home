"""Turning a model failure into an HTTP response, in one place.

Two endpoints can call the model — ``/search/interpret`` and
``/projects/analyze`` — and they used to disagree: one answered 503 with a
readable message, the other let the exception escape and returned 500. A model
being unreachable is never an internal error, and a caller should be able to
tell "try again" from "the request was wrong".
"""

from __future__ import annotations

import logging

from pydantic import ValidationError

from app.api.deps import ApiError

logger = logging.getLogger("home_procurement.llm")

#: the LLM is not configured at all; a deployment problem, named as one
_NOT_CONFIGURED = "سرویس تفسیر نیت پیکربندی نشده است. تنظیمات LLM را کامل کنید."
#: a model that is up but answered something unusable
_BAD_SHAPE = "پاسخ مدل با ساختار مورد انتظار نخواند. لطفاً دوباره تلاش کنید."
#: the model could not be reached, or is busy: retrying later is the right move
_UNAVAILABLE = "تفسیر نیت در حال حاضر ممکن نیست. لطفاً کمی بعد دوباره تلاش کنید."
#: the model refuses the request itself; the fix is configuration, not a retry
_MISCONFIGURED = (
    "پیکربندی مدل زبانی نادرست است و درخواست به سرویس تفسیر نرسید. "
    "مدل تنظیم‌شده روی این سرویس قابل استفاده نیست؛ لطفاً LLM_MODEL را بررسی کنید."
)


def llm_error(exc: Exception) -> ApiError:
    """
    The right response for a failed model call.

    The distinction that matters: a *transient* failure says come back later, a
    *rejected* one says the model is wrong for this endpoint, and a *bad shape*
    says the model answered with the wrong structure. None of them is a 500.
    """
    from app.llm import LLMRejected

    from app.core.config import LLMNotConfigured

    if isinstance(exc, LLMNotConfigured):
        # a deployment problem the operator has to see, not a retry
        logger.error("LLM not configured: %s", exc)
        return ApiError(_NOT_CONFIGURED, 503)
    if isinstance(exc, LLMRejected):
        logger.error(
            "LLM configuration rejected: model=%s status=%s reason=%s",
            exc.model,
            exc.status,
            exc.reason,
        )
        return ApiError(_MISCONFIGURED, 502)
    if isinstance(exc, ValidationError):
        logger.warning(
            "LLM response failed validation: %s",
            exc.errors()[0].get("msg") if exc.errors() else "unknown",
        )
        return ApiError(_BAD_SHAPE, 503)
    logger.warning("LLM call failed: %s", exc)
    return ApiError(_UNAVAILABLE, 503)


__all__ = ["llm_error"]
