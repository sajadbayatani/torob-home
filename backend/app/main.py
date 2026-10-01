"""FastAPI application factory."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import api_router
from app.core.config import settings
from app.core.request_id import bind, new_request_id

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("home_procurement")

DESCRIPTION = """
این API نیت کاربر را تفسیر می‌کند و آن را به **فهرست انتخاب‌های قابل مقایسه** تبدیل می‌کند.

خرید روی این پلتفرم انجام نمی‌شود: کاربر محصول و فروشنده را انتخاب می‌کند و خرید را
خودش از فروشنده انجام می‌دهد.

قاعدهٔ کلیدی: موتور تفسیر (قانونی یا LLM) فقط «ساختار نیت» را تولید می‌کند.
محصول، فروشنده، قیمت، موجودی و روابط محصول همیشه از کاتالوگ PostgreSQL خوانده
می‌شوند؛ هیچ دادهٔ بازاری هرگز تولید نمی‌شود.

* `POST /api/v1/search/interpret` — تفسیر نیت
* `GET  /api/v1/products/search` — جستجوی محصول و مقایسه فروشندگان
* `POST /api/v1/projects/analyze` — تحلیل نیاز/پروژه و ساخت فهرست انتخاب‌ها
* `POST /api/v1/baskets/{id}/optimize` — بهینه‌سازی قطعی بودجه
"""

TAGS_METADATA = [
    {"name": "meta", "description": "وضعیت سرویس و متادیتای دامنه"},
    {"name": "search", "description": "تفسیر نیت کاربر"},
    {"name": "catalog", "description": "کاتالوگ محصولات، جستجو و روابط"},
    {"name": "sellers", "description": "فروشندگان و پیشنهادها (دادهٔ دمو)"},
    {"name": "projects", "description": "موتور نیاز/پروژه"},
    {"name": "basket", "description": "فهرست انتخاب‌های کاربر و بهینه‌سازی آن"},
]


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=DESCRIPTION,
        openapi_tags=TAGS_METADATA,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def tag_request(request: Request, call_next):
        """Give every request an id, so its log lines can be found."""
        rid = new_request_id()
        bind(rid)
        response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        return response

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:  # pragma: no cover
        logger.exception("unhandled error on %s", request.url.path)
        return JSONResponse(status_code=500, content={"detail": "خطای داخلی سرور"})

    app.include_router(api_router, prefix=settings.api_prefix)

    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {
            "service": settings.app_name,
            "docs": "/docs",
            "api": settings.api_prefix,
        }

    return app


app = create_app()
