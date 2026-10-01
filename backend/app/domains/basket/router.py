"""Basket API: create, inspect, edit items, optimise budget."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import ApiError, commit, db_session
from app.domains.basket.schemas import (
    BasketCreateRequest,
    BasketItemCreate,
    BasketItemOut,
    BasketItemUpdate,
    BasketOut,
    OptimizationResult,
    OptimizeRequest,
)
from app.domains.basket.service import (
    BasketError,
    add_item,
    create_basket,
    delete_basket,
    find_item_out,
    load_basket,
    remove_item,
    serialize_basket,
    update_item,
)

router = APIRouter(prefix="/baskets", tags=["basket"])


def _guard(exc: BasketError) -> ApiError:
    return ApiError(exc.message, exc.status_code)


@router.post(
    "",
    response_model=BasketOut,
    status_code=201,
    summary="ساخت فهرست انتخاب‌ها (خالی یا با یک محصول)",
)
def create(payload: BasketCreateRequest, session: Session = Depends(db_session)) -> BasketOut:
    try:
        basket = create_basket(session, payload)
        payload_out = serialize_basket(session, basket)
    except BasketError as exc:
        session.rollback()
        raise _guard(exc) from exc
    commit(session)
    return payload_out


@router.get(
    "/{basket_id}",
    response_model=BasketOut,
    summary="فهرست انتخاب‌ها با محاسبهٔ مجدد همهٔ مبالغ توسط سرور",
)
def get_basket(basket_id: UUID, session: Session = Depends(db_session)) -> BasketOut:
    try:
        basket = load_basket(session, basket_id)
    except BasketError as exc:
        raise _guard(exc) from exc
    return serialize_basket(session, basket)


@router.post(
    "/{basket_id}/items",
    response_model=BasketItemOut,
    status_code=201,
    summary="افزودن محصول به فهرست انتخاب‌ها",
)
def add(
    basket_id: UUID, payload: BasketItemCreate, session: Session = Depends(db_session)
) -> BasketItemOut:
    try:
        basket = load_basket(session, basket_id)
        item = add_item(session, basket, payload)
        out = find_item_out(serialize_basket(session, basket), item.id)
    except BasketError as exc:
        session.rollback()
        raise _guard(exc) from exc
    commit(session)
    return out


@router.patch(
    "/{basket_id}/items/{item_id}",
    response_model=BasketItemOut,
    summary="ویرایش تعداد/فروشنده/قفل‌کردن قلم",
)
def update(
    basket_id: UUID,
    item_id: UUID,
    payload: BasketItemUpdate,
    session: Session = Depends(db_session),
) -> BasketItemOut:
    try:
        basket = load_basket(session, basket_id)
        item = update_item(session, basket, item_id, payload)
        out = find_item_out(serialize_basket(session, basket), item.id)
    except BasketError as exc:
        session.rollback()
        raise _guard(exc) from exc
    commit(session)
    return out


# 204 means "no body", and a `-> None` return would otherwise have FastAPI build a
# response model for it, which it asserts against at import time.
@router.delete(
    "/{basket_id}/items/{item_id}",
    status_code=204,
    response_model=None,
    summary="حذف محصول از فهرست انتخاب‌ها",
)
def delete(basket_id: UUID, item_id: UUID, session: Session = Depends(db_session)) -> None:
    try:
        basket = load_basket(session, basket_id)
        remove_item(session, basket, item_id)
    except BasketError as exc:
        session.rollback()
        raise _guard(exc) from exc
    commit(session)
    return None


@router.delete(
    "/{basket_id}",
    status_code=204,
    response_model=None,
    summary="حذف کل فهرست انتخاب‌ها (همراه با تحلیل پروژه)",
    description=(
        "فهرست انتخاب‌ها و قلم‌های آن حذف می‌شوند، و اگر فهرست انتخاب‌ها متعلق به یک تحلیل پروژه باشد خودِ "
        "تحلیل هم حذف می‌شود؛ بنابراین عنوان و پرسش پروژه دیگر باقی نمی‌ماند."
    ),
)
def clear(
    basket_id: UUID, session: Session = Depends(db_session)
) -> None:
    try:
        basket = load_basket(session, basket_id)
        delete_basket(session, basket)
    except BasketError as exc:
        session.rollback()
        raise _guard(exc) from exc
    commit(session)
    return None


@router.post(
    "/{basket_id}/optimize",
    response_model=OptimizationResult,
    summary="بهینه‌سازی قطعی فهرست انتخاب‌ها برای رسیدن به بودجه",
    description=(
        "بدون LLM. کالگوریتم حریصانه و قابل توضیح: بیشترین صرفه‌جویی، سپس کمترین افت کیفیت. "
        "کیفیت هرگز زیر کف قالب پروژه نمی‌رود و مجموع هزینه هرگز افزایش نمی‌یابد."
    ),
)
async def optimize(
    basket_id: UUID,
    payload: OptimizeRequest,
    session: Session = Depends(db_session),
) -> OptimizationResult:
    from app.catalog import get_catalog
    from app.domains.basket.optimizer import optimize_basket
    from app.domains.search.schemas import InterpretedIntent

    try:
        basket = load_basket(session, basket_id)
    except BasketError as exc:
        raise _guard(exc) from exc

    # A project basket already knows its own context, so its stored intent is
    # used directly: the model is not asked again, and the target budget comes
    # from the project rather than from a re-read of the query.
    intent = (
        InterpretedIntent.model_validate(basket.intent_payload)
        if basket.intent_payload
        else None
    )

    target_budget = payload.target_budget or (
        intent.requirements.budget if intent is not None else None
    )
    # Deliberately **not** a fallback to `SearchService().interpret(payload.query)`.
    # It was there, and it was wrong twice over. Optimising a list is not reading a
    # sentence: the list and the project that produced it already hold everything
    # this needs, and re-sending the user's original query through the interpretation
    # prompt spends a model call to rediscover a budget the request should have
    # carried. It also meant a plain "optimise my list" click could fail with an
    # interpretation error the user had no way to act on.
    #
    # With no ceiling from the request and none on the stored project, the honest
    # answer is the one below: there is no budget to optimise against.
    basket_snapshot = serialize_basket(session, basket)
    if target_budget is None:
        # No ceiling was ever set, so there is nothing to optimise against. This
        # is a real answer, not a failure: the action reports it and leaves the
        # basket exactly as it is, instead of erroring and leaving the button
        # with nothing to show.
        return OptimizationResult(
            original_total=basket_snapshot.total,
            target_budget=None,
            can_optimize=False,
            over_budget=False,
            optimized_total=basket_snapshot.total,
            saved=0,
            within_budget=True,
            unfilled_gap=0,
            changes=[],
            applied=False,
            basket=basket_snapshot,
            explanation=(
                "برای این فهرست انتخاب‌ها بودجهٔ هدفی تعیین نشده است؛ بدون سقف، چیزی برای "
                "کاهش وجود ندارد. اگر بودجه‌ای در نظر دارید، همان را وارد کنید."
            ),
            trade_offs=[],
        )

    from app.catalog.selection import build_room_scope

    result = optimize_basket(
        session,
        basket,
        target_budget,
        apply=payload.apply,
        allow_quality_downgrade=payload.allow_quality_downgrade,
        scope=build_room_scope(get_catalog(), intent.room) if intent is not None else None,
        project_type=(
            intent.project_type.value if intent is not None and intent.project_type else None
        ),
        area_m2=intent.requirements.area_m2 if intent is not None else None,
    )
    basket = load_basket(session, basket_id)
    result.basket = serialize_basket(session, basket)
    commit(session)
    return result


@router.post(
    "/{basket_id}/budget",
    response_model=BasketOut,
    summary="ثبت بودجهٔ هدف روی فهرست انتخاب‌ها",
)
def set_budget(
    basket_id: UUID,
    budget: int = Query(..., ge=0),
    session: Session = Depends(db_session),
) -> BasketOut:
    from app.domains.basket.service import set_target_budget

    try:
        basket = load_basket(session, basket_id)
        basket = set_target_budget(session, basket, budget)
        out = serialize_basket(session, basket)
    except BasketError as exc:
        session.rollback()
        raise _guard(exc) from exc
    commit(session)
    return out
