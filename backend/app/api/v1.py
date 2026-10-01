"""API v1 router aggregation + meta endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import settings
from app.core.enums import (
    QUALITY_FA,
    STYLE_FA,
    Availability,
    CategoryKind,
    Domain,
    Intent,
    ProjectType,
    Quality,
    RelationType,
)
from app.db.session import get_session_factory
from app.domains.basket.router import router as basket_router
from app.domains.catalog.router import router as catalog_router
from app.domains.projects.router import router as projects_router
from app.domains.search.router import router as search_router
from app.domains.sellers.router import router as sellers_router

meta_router = APIRouter(tags=["meta"])

DEMO_DISCLAIMER = (
    "همهٔ محصولات، فروشندگان، قیمت‌ها و موجودی‌ها در این نسخه **دادهٔ دمو و seed** هستند "
    "و به فروشندگان واقعی مربوط نیستند."
)


@meta_router.get("/health", summary="سلامت سرویس و اتصال پایگاه‌داده")
def health() -> dict:
    db_ok = False
    try:
        with get_session_factory()() as session:
            session.execute(text("select 1"))
            db_ok = True
    except Exception:  # noqa: BLE001 - health must never raise
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "app": settings.app_name,
        "version": settings.app_version,
        "database": "up" if db_ok else "down",
        # never the key, the model or the endpoint: only whether one is set
        "llm": "configured" if settings.llm_configured else "not_configured",
        "demo_data": True,
        "note": DEMO_DISCLAIMER,
    }


@meta_router.get("/meta/enums", summary="واژگان دامنه (برای رابط کاربری)")
def enums() -> dict:
    return {
        "intents": [i.value for i in Intent],
        "domains": [{"value": d.value, "label": DOMAIN_FA[d]} for d in Domain],
        "project_types": [{"value": p.value, "label": PROJECT_FA[p]} for p in ProjectType],
        "qualities": [{"value": q.value, "label": QUALITY_FA[q], "rank": q.rank} for q in Quality],
        "styles": [{"value": k, "label": v} for k, v in STYLE_FA.items()],
        "category_kinds": [k.value for k in CategoryKind],
        "availability": [a.value for a in Availability],
        "relation_types": [r.value for r in RelationType],
        "currency": {"code": "IRT", "label": "تومان"},
    }


@meta_router.get("/meta/demo", summary="راهنمای سناریوهای دمو")
def demo_scenarios() -> dict:
    return {
        "disclaimer": DEMO_DISCLAIMER,
        "scenarios": [
            {
                "name": "product_search",
                "query": "شیر توکار برند X",
                "expected_intent": Intent.PRODUCT_SEARCH.value,
            },
            {
                "name": "need_search",
                "query": "بازسازی سرویس بهداشتی ۱۲ متری، کیفیت متوسط",
                "expected_intent": Intent.NEED_SEARCH.value,
            },
            {
                "name": "budget_update",
                "query": "بودجه من ۵۵ میلیون است",
                "expected_intent": "BUDGET constraint",
            },
        ],
    }


DOMAIN_FA = {Domain.BATHROOM: "سرویس بهداشتی", Domain.KITCHEN: "آشپزخانه"}
PROJECT_FA = {
    ProjectType.RENOVATION: "بازسازی",
    ProjectType.NEW_BUILD: "نوسازی",
    ProjectType.REDESIGN: "بازطراحی",
    ProjectType.REPAIR: "تعمیر",
}

api_router = APIRouter()
api_router.include_router(meta_router)
api_router.include_router(search_router)
api_router.include_router(catalog_router)
api_router.include_router(sellers_router)
api_router.include_router(projects_router)
api_router.include_router(basket_router)
