"""
End-to-end trace of the two reported queries, for a human to read.

Not a test: it prints what each stage produced so the pipeline can be checked
against the running code rather than against a description of it. Run with

    .venv/bin/python -m pytest tests/manual/trace_reported_queries.py -q -s

The model is scripted, so this is the real pipeline with the one real-LLM step
replaced by what a model was reported to have returned. No provider is called.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

ENRICHED = (
    Path(__file__).resolve().parents[3] / "data" / "catalog" / "products_70_enriched.json"
)

#: Exactly the requirements the report said the model produced for the bedroom.
REPORTED_BEDROOM = [
    {"description": "رنگ دیوار", "terms": ["رنگ دیوار"]},
    {"description": "کفپوش", "terms": ["کفپوش"]},
    {"description": "پرده", "terms": ["پرده"]},
    {"description": "چراغ سقفی", "terms": ["چراغ سقفی"]},
    {"description": "اکسسوری دکوراسیونی", "terms": ["اکسسوری دکوراسیونی"]},
]

#: The same room, with the things a bedroom redesign actually needs to buy.
BEDROOM_WITH_FURNITURE = [
    {"description": "تخت خواب", "terms": ["تخت خواب"]},
    {"description": "کمد لباس", "terms": ["کمد لباس"]},
    {"description": "رنگ دیوار", "terms": ["رنگ دیوار"]},
    {"description": "کفپوش", "terms": ["کفپوش"]},
    {"description": "پرده", "terms": ["پرده"]},
]

BATHROOM = [
    {"description": "توالت", "terms": ["توالت"]},
    {"description": "روشویی", "terms": ["روشویی"]},
    {"description": "آینه سرویس", "terms": ["آینه"]},
    {"description": "شیر", "terms": ["شیر"]},
    {"description": "کاشی و سرامیک", "terms": ["کاشی"]},
]


def show(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def report(response_json: dict, catalog_path) -> None:
    from app.catalog.selection import build_room_scope, subcategories_for_terms
    from app.catalog.store import read_index
    from app.core.text import normalize_persian

    index = read_index(Path(catalog_path))
    analysis = response_json["analysis"]
    interpretation = analysis["interpretation"]
    room = interpretation.get("room")
    scope = build_room_scope(index, room)
    project_type = analysis.get("project_type")
    area = analysis.get("area_m2")

    print(f"query          : {analysis.get('title')}")
    print(f"room / type    : {room!r} / {project_type} / {area} m2")
    print(f"reasoning      : {analysis.get('reasoning_status')}")
    print(f"estimated total: {analysis['estimated_total']:,} toman")

    print("\n-- 1. LLM semantic requirements")
    for requirement in interpretation.get("project_requirements") or []:
        print(f"   • {requirement['description']}  terms={requirement['terms']}")

    print("\n-- 2. requirement -> canonical catalog subcategory")
    for requirement in interpretation.get("project_requirements") or []:
        slugs = subcategories_for_terms(
            index,
            requirement["terms"],
            scope=scope,
            project_type=project_type,
            area_m2=area,
        )
        labelled = ", ".join(
            f"{slug} ({normalize_persian(index.subcategory_label(slug))})" for slug in slugs
        )
        print(f"   • {requirement['description']:24s} -> {labelled or '(nothing in the file)'}")

    print("\n-- 3. matched / unmatched requirements")
    matched = [c["label"] for c in analysis["candidates"]]
    missing = [
        f"{c['label']} ({c.get('note') or 'no match'})"
        for c in analysis["missing_categories"]
    ]
    print(f"   matched   ({len(set(matched))}): {sorted(set(matched)) or '-'}")
    print(f"   unmatched ({len(missing)}): {missing or '-'}")

    print("\n-- 4/5. products actually returned, and the candidate count")
    print(f"   candidates: {len(analysis['candidates'])}")
    for candidate in analysis["candidates"]:
        product = candidate["product"]
        print(
            f"   • [{candidate['label']}] {product['name']}"
            f"  — {product.get('subcategory')}  "
            f"{candidate['unit_price']:,}  ({candidate['seller_name']})"
        )
    print(f"   basket items: {len(response_json['basket'].get('items') or [])}")


def test_trace_reported_queries(client: TestClient, llm, session, monkeypatch) -> None:
    """
    ``reasoning_status`` is reported honestly either way: when the model declines
    the project the deterministic products are still returned, and that is the
    path worth tracing here, since it contains no second model to confuse the
    reading. The scripted stub answers the stage-2 prompt with an intent payload,
    which the reasoning stage rejects, so the fallback runs.
    """
    import os

    from app.catalog.store import reset_cache
    from app.core.config import get_settings

    path = str(Path(ENRICHED).resolve())
    os.environ["CATALOG_PATH"] = path
    get_settings.cache_clear()
    reset_cache()

    def bedroom(requirements, room="اتاق خواب", goal="تغییر دکوراسیون اتاق خواب"):
        llm.answer(
            intent="project_search",
            category="furniture",
            project={
                "type": "redesign",
                "room": room,
                "room_token": "bedroom",
                "area_m2": 12.0,
                "goal": goal,
                "constraints": [],
                "requirements": requirements,
            },
            constraints={"quality": None, "budget": None, "notes": []},
            confidence=0.9,
            explanations=["کاربر خواستهٔ اتاق خوابش را تغییر دکوراسیون کند."],
        )

    show("A. bedroom, the requirements the report gave verbatim")
    bedroom(REPORTED_BEDROOM)
    body = client.post(
        "/api/v1/projects/analyze",
        json={"query": "اتاق خواب ۱۲متری‌ام رو می‌خوام تغییر دکوراسیون بدم"},
    ).json()
    report(body, path)

    show("B. the same room, with the purchases a redesign needs")
    bedroom(BEDROOM_WITH_FURNITURE)
    body = client.post(
        "/api/v1/projects/analyze",
        json={"query": "اتاق خواب ۱۲متری‌ام رو می‌خوام تغییر دکوراسیون بدم"},
    ).json()
    report(body, path)

    show("C. bathroom renovation")
    llm.bathroom_project(area_m2=12.0, quality="medium", requirements=BATHROOM)
    body = client.post(
        "/api/v1/projects/analyze",
        json={"query": "بازسازی سرویس بهداشتی ۱۲ متری، کیفیت متوسط"},
    ).json()
    report(body, path)

    os.environ.pop("CATALOG_PATH", None)
    get_settings.cache_clear()
    reset_cache()
