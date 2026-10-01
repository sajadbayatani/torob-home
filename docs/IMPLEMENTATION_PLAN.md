# Implementation Plan — Home Procurement Platform (MVP v0.1)

Status: as implemented. This document records the decisions taken *before* and
*during* the build, so the reasoning behind the code stays discoverable.

---

## 0. Repository inspection

The `torob-home` repository was **completely empty** at the start: no files, no
git history, no existing infrastructure.

Consequences:

- There was nothing to reuse and no conflict with the requested architecture.
- The whole product is built from scratch.
- The stack is exactly what the brief mandates: FastAPI + SQLAlchemy 2 + Pydantic v2
  + PostgreSQL + Alembic on the backend, Vue 3 + TypeScript + Vite + Router + Pinia
  + Tailwind on the frontend.

---

## 1. Key architectural decisions

| Topic | Decision | Why |
|---|---|---|
| Architecture style | Modular monolith with domain boundaries (`app/domains/*`) | Explicit requirement; avoids over-engineering |
| Domain boundaries | `catalog`, `sellers`, `search`, `projects`, `basket` | Each domain owns its models / schemas / service / router |
| LLM scope | **Intent interpretation only**; zero commercial data | Product principle: the model may not invent products, sellers or prices |
| Provider abstraction | `IntentInterpreter` protocol with two implementations: `RuleBasedInterpreter` (default, deterministic, no API key) and `LLMInterpreter` (OpenAI-compatible, key required, falls back to rules) | Local dev works with no key; swapping vendors is a factory change |
| LLM output validation | Pydantic with `extra="forbid"`; the schema contains no product/price field at all | "The AI cannot fabricate a product" is guaranteed at the type-system level |
| Money | `BIGINT` **Toman** integers; every total computed server-side | No floats, no client-trusted numbers |
| Price in a basket | `unit_price` is **never persisted** — read live from `offers.price` | Prices can never drift; the catalogue is always authoritative |
| Optimisation baseline | `unit_price_snapshot` is stored only to report what changed | Transparent change log |
| JSON usage | Only the intent snapshot (`intent_payload`); relationships stay relational | Core model stays normalised |
| Search | Normalised `search_text` column (Arabic ي/ك, ZWNJ, Persian/Arabic digits) + DB narrowing with `ILIKE` + in-process ranking | Persian-first, simple, and a clear path to trigram/Elasticsearch |
| Offer ranking | `OfferRankStrategy` protocol, default `PriceFirstOfferRanker` | Room for future criteria without touching call sites |
| Related products | Explicit `product_relations` rows + a category/project-rule fallback; the Persian reason comes from the relation template | The LLM never creates products |
| Budget optimisation | Deterministic greedy plan, explainable, with a project quality floor | Brief requires "deterministic and explainable" |
| Authentication | None (per the brief) | A simple `owner_token` on the basket is enough for the demo |
| Frontend | Central API layer in `src/api/*`; Pinia only for `search` and `basket` | Explicit requirement |
| RTL | `<html lang="fa" dir="rtl">` + Vazirmatn bundled via fontsource | Persian-first, no runtime CDN dependency |

---

## 2. Data model

```
brands ──< products >── categories (self-referencing parent)
              │
              ├──< product_attributes      (key / label / value / value_num / unit)
              ├──< offers >── sellers
              ├──< product_relations       (source ──▶ target, self-referencing)
              └──< basket_items >── baskets

project_templates ──< project_requirements >── categories
                              │
project_analyses ──> baskets (1:1)
```

- `categories`: `domain` (bathroom|kitchen), `kind`
  (fixture|surface|accessory|material|appliance|lighting|hardware), slug, `name_fa`.
- `products`: `brand_id`, `category_id`, `quality` (low|medium|high|ultra), `style`,
  `unit`, `reference_price`, normalised `search_text`.
- `product_relations`: `relation_type` ∈ {install_kit, compatible_fitting,
  required_material, accessory_pair, room_pair, alternative} + `weight` + `reason_fa`.
- `project_requirements`: `role`, `category_id`, `quantity_mode` ∈ {per_area, fixed},
  `multiplier`, `min_qty`, `max_qty`, `quality_min`, `required`, `reason_fa`, `sort_order`.
- `basket_items`: `product_id`, `offer_id`, `quantity`, `role`, `origin`, `is_locked`,
  `unit_price_snapshot`, `reason_fa`, `replaced_item_id`.
- Every table carries `data_source` (and sellers carry `is_demo`) so demo data is
  always identifiable.

---

## 3. The need / project engine

Rules live in `project_requirements`, not in UI code. Current templates:

| Template | Rules (role: mode × multiplier) |
|---|---|
| `bathroom_renovation` | `tiles` per_area × 3.2 · `install_materials` per_area × 1.25 · `toilet` 1 · `vanity` 1 · `faucet` 1 · `mirror` 1 · `accessories` 5 |
| `bathroom_new_build` | `tiles` × 3.4 · `install_materials` × 1.4 · `toilet` 1 · `vanity` 1 · `faucet` 1 · `mirror` 1 · `lighting` 1 |
| `bathroom_redesign` | `tiles` × 3.0 · `vanity` 1 · `faucet` 1 · `mirror` 1 · `lighting` 1 · `accessories` 5 (no louvre/lining work) |
| `kitchen_renovation` | `cabinet` × 0.6 · `counter_top` × 0.65 · `sink` 1 · `faucet` 1 · `cooktop` 1 · `hood` 1 · `hardware` 2 · `lighting` 1 |
| `kitchen_new_build` | `cabinet` × 0.65 · `counter_top` × 0.7 · `sink` 1 · `faucet` 1 · `cooktop` 1 · `hood` 1 · `hardware` 3 · `appliance` 1 |
| `kitchen_redesign` | `cabinet` × 0.6 · `counter_top` × 0.65 · `hardware` 2 · `lighting` 2 |

Worked example — `bathroom_renovation` + `area_m2 = 12` + `quality = medium`:

```
tiles               per_area  12 × 3.2  → 39 m²   @ 690,000  = 26,910,000
install_materials   per_area  12 × 1.25 → 15 packs @ 890,000 = 13,350,000
toilet              fixed 1            @ 15,400,000            = 15,400,000
vanity              fixed 1            @  9,800,000            =  9,800,000
faucet              fixed 1            @  2,150,000            =  2,150,000
mirror              fixed 1            @  2,400,000            =  2,400,000
accessories         fixed 5            @    780,000 × 5        =  3,900,000
                                                          total = 73,910,000 Toman
```

Product selection is deterministic, with this preference order:
1. purchasable products only (an item must be orderable to enter the basket);
2. the requested style, as a *soft* preference (never a hard filter);
3. the smallest quality-tier distance to the requested quality;
4. the lowest `reference_price`; then product id as a stable tiebreaker.

Offer selection: cheapest purchasable offer of the chosen product.

---

## 4. Budget optimisation

Pure function (`plan_optimization`) over plain dataclasses, so it is unit-testable
without a database:

1. If the total already fits the budget, do nothing.
2. Otherwise repeatedly apply the single swap with the **largest saving**; ties are
   broken by the **smaller quality loss**, then by a stable role key — therefore
   the plan is fully deterministic.
3. Each item is swapped at most once; locked items are never touched.
4. Hard guarantees: a candidate must be **cheaper**, must not be cheaper than the
   requirement's `quality_min` floor, and may not be a quality *upgrade* unless
   it is also cheaper (which is simply a win).

Applied to the worked example with `target_budget = 55,000,000`:

```
tiles               → economy tiles      saving 10,140,000   (medium → low)
install_materials   → economy install kit saving  5,550,000  (medium → low)
toilet              → economy toilet      saving  5,200,000   (medium → low)
73,910,000 → 53,020,000 Toman  (saved 20,890,000, within budget)
```

---

## 5. Execution order used

1. Repository skeleton, docker-compose, env template, README.
2. Backend: `core` → `db` → models → Alembic → domains → seed → tests.
3. Frontend: Vite/TS/Tailwind shell → API layer → stores → views → tests.
4. Run tests, typecheck and production builds.
5. Boot the whole stack with docker compose and verify both demo scenarios.
6. Tune the seed prices until the demo lands on the numbers from the brief
   (≈74M → within 55M).

---

## 6. Deliberately out of scope for v0.1

Authentication, payments, real checkout, seller onboarding, crawlers, ML training,
microservices, an event bus, multi-zone deployment, multi-language i18n, and — most
importantly — **any commercial data produced by an LLM**.
