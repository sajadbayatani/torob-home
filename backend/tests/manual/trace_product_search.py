"""Prints the real /products/search response for the reported queries."""
from pathlib import Path

ENRICHED = Path(__file__).resolve().parents[3] / "data" / "catalog" / "products_70_enriched.json"
QUERIES = [
    "دنبال یه ماشین لباسشویی تا ۳۰ تومن میگردم",
    "ماشین لباسشویی",
    "ماشین ظرفشویی",
    "ماشین",
    "شیر روشویی",
    "یخچال دوو",
]

def test_trace(client, session, monkeypatch):
    from app.catalog.store import reset_cache
    from app.core.config import get_settings
    monkeypatch.setenv("CATALOG_PATH", str(ENRICHED))
    get_settings.cache_clear(); reset_cache()

    for q in QUERIES:
        b = client.get("/api/v1/products/search", params={"q": q, "limit": 100}).json()
        print(f"\n### {q}")
        print(f"    total={b['total']}  detected_category={b['detected_category']}"
              f"  detected_domain={b['detected_domain']}  intent={b['intent']}")
        for row in b["items"]:
            p = row["product"]
            prices = [o["price"] for o in p["offers"] if o.get("available")]
            print(f"      {p['category']['id']:16s} min={min(prices):>12,} "
                  f"matched={row['matched_terms']}  {p['name'][:40]}")
    print("\n  facets.categories:",
          [(f['value'], f['count']) for f in b['facets']['categories']])
    monkeypatch.delenv("CATALOG_PATH", raising=False)
    get_settings.cache_clear(); reset_cache()
