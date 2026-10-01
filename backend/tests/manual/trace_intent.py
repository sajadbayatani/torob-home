"""Prints what /search/interpret answers, and what the model was asked."""
from pathlib import Path
from fastapi.testclient import TestClient
from tests.llm_stub import LLMStub

ENRICHED = Path(__file__).resolve().parents[3] / "data" / "catalog" / "products_70_enriched.json"
CASES = [
    ("یه ماشین ظرفشویی لوکس میخوام", "ultra"),
    ("یه ماشین ظرفشویی باکیفیت میخوام", "high"),
    ("یه ماشین ظرفشویی کیفیت متوسط میخوام", "medium"),
    ("یه ماشین ظرفشویی ارزان میخوام", "low"),
]

def test_trace(client: TestClient, session, llm: LLMStub, monkeypatch) -> None:
    from app.catalog.store import reset_cache
    from app.core.config import get_settings
    from app.domains.search.llm_interpreter import SYSTEM_PROMPT
    monkeypatch.setenv("CATALOG_PATH", str(ENRICHED))
    get_settings.cache_clear(); reset_cache()

    for query, quality in CASES:
        llm.product(terms=["ماشین ظرفشویی"],
                    constraints={"quality": quality, "budget": None, "notes": []})
        r = client.post("/api/v1/search/interpret", json={"query": query})
        b = r.json()
        q = b.get("product_query") or {}
        print(f"\n### {query}   (model answered quality={quality!r})")
        print(f"    HTTP {r.status_code}")
        print(f"    intent      = {b.get('intent')}")
        print(f"    terms       = {q.get('text')!r}  tokens={q.get('tokens')}")
        print(f"    subcategory = {q.get('category_slug')!r}  domain={b.get('domain')!r}")
        print(f"    quality     = {b['requirements']['quality']!r}"
              f"   (user said: {query.split('میخوام')[0].split('ماشین ظرفشویی')[-1].strip()!r})")
    print(f"\n  system prompt chars: {len(SYSTEM_PROMPT)}")
    monkeypatch.delenv("CATALOG_PATH", raising=False)
    get_settings.cache_clear(); reset_cache()
