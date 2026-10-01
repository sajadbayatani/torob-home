"""Search API: intent interpretation.

Every query goes through the interpreter, which is a model. There is no
keyword-matching path: if the model is unreachable or answers with something
unusable, the request fails with 503 rather than being answered from a word list.
A search that silently stops understanding is worse than one that says it cannot.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.core.config import LLMNotConfigured
from app.domains.search.schemas import (
    MAX_QUERY_LENGTH,
    InterpretRequest,
    InterpretResponse,
    SearchRouteResponse,
)
from app.domains.search.service import SearchService
from app.llm import LLMRejected, LLMUnavailable

logger = logging.getLogger("home_procurement.search")

router = APIRouter(prefix="/search", tags=["search"])


@router.get(
    "/route",
    response_model=SearchRouteResponse,
    summary="مسیر جستجو، بدون مدل زبانی",
    description=(
        "تصمیم نخست سامانه برای هر جستجو، کاملاً قطعی و بدون هیچ فراخوانی مدل. "
        "اگر پاسخ `product` باشد، جستجو مستقیماً از کاتالوگ پاسخ داده می‌شود و "
        "هزینهٔ مدل صفر است. اگر `llm` باشد، یعنی کاتالوگ نتوانسته مطمئن شود و "
        "درخواست به `/search/interpret` سپرده می‌شود؛ حدس زدن عمداً انجام نمی‌شود."
    ),
)
def route(
    # named `q`, not `query`, to match `/products/search` — a caller that can
    # search can route, without having to learn a second spelling
    q: str = Query(..., min_length=1, max_length=MAX_QUERY_LENGTH),
) -> SearchRouteResponse:
    verdict = SearchService().route(q)
    return SearchRouteResponse(
        route="product" if verdict.is_product else "llm",
        is_product=verdict.is_product,
        explained=list(verdict.explained),
        unexplained=list(verdict.unexplained),
        reason=verdict.reason,
    )


@router.post(
    "/interpret",
    response_model=InterpretResponse,
    summary="تفسیر نیت کاربر (Product Search یا Need Search)",
    description=(
        "ورودی: پرسش طبیعی کاربر. خروجی: **فقط ساختار نیت** — بدون هیچ محصول، "
        "فروشنده، قیمت یا موجودی. مدل، فهرست دسته‌های واقعی کاتالوگ را می‌بیند و "
        "نیت کاربر را به همان دسته‌ها نگاشت می‌کند؛ هر دسته‌ای که در کاتالوگ نباشد "
        "جداگانه به‌عنوان کمبود گزارش می‌شود و هرگز محصولی ساخته نمی‌شود."
    ),
)
async def interpret(
    payload: InterpretRequest,
    session: Session = Depends(db_session),
) -> InterpretResponse:
    from pydantic import ValidationError

    from app.llm.errors import llm_error

    service = SearchService()
    try:
        intent = await service.interpret(payload.query, session)
    except (ValidationError, LLMNotConfigured, LLMRejected, LLMUnavailable) as exc:
        raise llm_error(exc) from exc
    return InterpretResponse.from_intent(intent)
