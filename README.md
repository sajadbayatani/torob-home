# Khaneh-Yar — Home Procurement Platform (MVP v0.1)

An intent-driven home-shopping platform: it understands **what a person wants to
accomplish in their home**, turns that intent into a purchasable basket, and lets
them compare and optimise how that basket is sourced.

```
user query → intent interpretation → requirements → catalogue products → smart basket → seller comparison & budget optimisation
```

This release intentionally focuses on two domains: **bathroom** and **kitchen**.
The product UI is Persian and RTL-first.

---

## 1. The core product rule

> The interpretation engine (rule-based or LLM) produces **structure only**.
> Products, sellers, prices, availability and product relationships are always read
> from the PostgreSQL catalogue.

This rule is enforced in code, not just in convention:

- `InterpretedIntent` (`backend/app/domains/search/schemas.py`) has **no field** for a
  product, seller, price, offer or specification — the interpreter is structurally
  unable to represent invented catalogue data.
- Every request/response schema uses `extra="forbid"`, so an LLM cannot smuggle extra
  data through.
- If a product is not in the catalogue, the API returns "not found". Nothing is ever
  invented to fill a gap.
- No monetary total is ever produced by an LLM. All money is computed on the server.

---

## 2. Architecture

### Backend — FastAPI, SQLAlchemy 2, Pydantic v2, PostgreSQL, Alembic

```
backend/app/
├── main.py                      # FastAPI app factory
├── core/                        # settings, domain enums, Persian text utilities
├── db/                          # engine, session factory, declarative base
├── api/v1.py                    # router aggregation + domain metadata
├── domains/
│   ├── catalog/                 # categories, brands, products, attributes, relations, search
│   ├── sellers/                 # sellers and offers (the only source of price/availability)
│   ├── search/                  # intent interpretation (rules + LLM) and search interpretation
│   ├── projects/                # project templates, need rules, need/project analysis
│   └── basket/                  # basket commands, server-side money maths, budget optimiser
└── seed/                        # deterministic demo dataset + CLI
```

| Domain | Responsibility |
|---|---|
| `catalog` | Product normalisation, Persian search, contextual relations, offer ranking |
| `sellers` | Sellers and offers; the reference for price and availability |
| `search` | Intent interpretation: `PRODUCT_SEARCH` vs `NEED_SEARCH`, plus requirement extraction |
| `projects` | Need/project engine: template + quantity rules + product selection + estimate |
| `basket` | Basket items, server-side totals, deterministic budget optimisation |

Data flow:

```
natural language → interpreter (structure only) → domain services → PostgreSQL catalogue
                → project/basket engines → REST API → Vue app
```

Every row carries `data_source`, and sellers carry `is_demo`, so demo data is always
identifiable rather than silently mixed with real data.

### Frontend — Vue 3, TypeScript, Vite, Vue Router, Pinia, Tailwind

```
frontend/src/
├── api/            # the only place that talks HTTP: client, search, products, projects, baskets
├── stores/         # shared state only: searchStore, basketStore
├── components/     # ui / product / search building blocks
├── views/          # Home, Search, Product, Project, Basket
├── types/api.ts    # TypeScript mirror of the FastAPI models
└── utils/format.ts # Persian digits and Toman formatting
```

- Persian-first RTL: `<html lang="fa" dir="rtl">`, Vazirmatn font bundled through
  fontsource (works offline, no CDN).
- No component performs a raw `fetch`; all calls go through `src/api/*`.
- Pinia holds only genuinely shared state (search flow, active basket).
- Visual identity: no gradients, no glassmorphism, no invented statistics or reviews.

### Design system: Material Design 2

The UI follows **Material Design 2** on a white surface, with the three declared
brand colours and a strictly token-driven design system:

- `frontend/src/theme/material.css` is the **single source of truth**. Colour,
  shape, elevation, type, spacing, state and motion are all CSS custom properties
  on `[data-theme="material"]`.
- `frontend/tailwind.config.js` maps Tailwind onto those tokens
  (`bg-background`, `text-foreground`, `bg-card`, `bg-primary`, `bg-secondary`,
  `bg-muted`, `bg-accent`, `text-destructive|success|warning`, `border-border`,
  `ring-ring`, plus `rounded-control|field|surface|overlay`,
  `shadow-d1…d24|appbar|control|field|overlay|surface`, `h-button|chip|field|appbar|fab`,
  `duration-motion` and `ease-motion`). It defines **no colour of its own**.
- `<html lang="fa" dir="rtl" data-theme="material">` applies the theme.
- No component hard-codes a colour, radius, shadow or duration;
  `frontend/tests/theme.spec.ts` enforces all of it.

**Brand palette — exactly three colours, no additional brand colours:**

| Role | Token |
|---|---|
| Text, icons, neutral base | `--brand-charcoal` — Charcoal Blue `#424B54` |
| Page and surface background | `--brand-white` — White `#FFFDFD` |
| Primary action, money, identity | `--brand-amaranth` — Dark Amaranth `#990D35` |

Everything else is a tint or an alpha of those three: `--muted` (6%), `--secondary`
(10%), `--accent` (5%), `--border` (12% divider), `--input` (42% unfocused field
line). State roles carry fixed semantic colours so states stay distinguishable:
`--destructive` `#B3261E`, `--success` `#1F7A5C`, `--warning` `#8F6410`. These are
**semantic, not brand** — they are never used for identity or decoration.

**Material building blocks:**

| Concern | Tokens |
|---|---|
| Shape | `--shape-control` / `--shape-field` 2dp, `--shape-surface` / `--shape-overlay` 4dp, `--shape-sheet` 16dp, `--shape-full` circular |
| Elevation | `--elevation-{1,2,3,4,6,8,16,24}` — the MD2 levels this system uses — plus component bindings: `--depth-control` 2dp, `--depth-press` 8dp, `--depth-surface` 2dp, `--depth-overlay` 8dp, `--depth-dialog` 24dp, `--depth-appbar` 4dp, `--depth-fab` 6dp |
| Metrics | `--size-button` 36dp, `--size-chip` 32dp, `--size-field` 48dp, `--size-appbar` 56dp, `--size-fab` 56dp, `--control-size` 48dp minimum target |
| Grid | `--spacing` 8dp, `--spacing-half` 4dp, `--spacing-quarter` 2dp |
| State | `--state-hover` 8%, `--state-focus` 24%, `--state-pressed` 10%, `--state-dragged` 16% |
| Motion | 225ms standard, `--motion-ease` `cubic-bezier(0.4, 0, 0.2, 1)` |
| Type | Vazirmatn; headings 600, buttons 500, body 400; `--leading-body` 1.7 (MD2's 1.5 opened up for Persian) |

Components use Material behaviour: 2dp focus outlines, state layers instead of
spring scaling, filled text fields with a 2dp bottom line, elevated borderless
cards, 32dp chips, a 56dp app bar that marks the active destination in `primary`,
and a 48dp minimum touch target on every control.

Persian RTL design rules (direction, typography, Persian digits, Toman formatting,
spacing, colour tokens, component patterns) are governed by
[`docs/UI_DESIGN_GUIDELINES.md`](docs/UI_DESIGN_GUIDELINES.md). The reviews that
shaped the UI are recorded in [`docs/UI_AUDIT.md`](docs/UI_AUDIT.md),
[`docs/MATERIAL_MIGRATION.md`](docs/MATERIAL_MIGRATION.md) and, for the earlier
steps, [`docs/THEME_MIGRATION.md`](docs/THEME_MIGRATION.md) and
[`docs/PALETTE_MIGRATION.md`](docs/PALETTE_MIGRATION.md). The **VibeFarsi** MCP
server, configured in `opencode.json`, is the reference source. Because it publishes
React + Tailwind code and this project is Vue 3, its output is used as **design
guidance and re-implemented in Vue** — React is never copied and is not a dependency
of this project.

---

## 3. Data model

```
categories ──< products >── brands
                 │
                 ├──< product_attributes
                 ├──< offers >── sellers
                 └──< product_relations (source ──▶ target)

project_templates ──< project_requirements >── categories
project_analyses ──▶ baskets ──< basket_items >── products / offers
```

| Table | Purpose |
|---|---|
| `categories` | Category tree with `domain` (bathroom/kitchen) and `kind` (fixture, surface, accessory, material, appliance, lighting, hardware) |
| `brands` | Manufacturers |
| `products` | `quality` tier (low/medium/high/ultra), `style`, `unit`, `reference_price`, normalised `search_text` |
| `product_attributes` | Structured specifications (`key` / `label` / `value` / `value_num` / `unit`) |
| `sellers` | Sellers (`is_demo = true` for all seeded demo shops) |
| `offers` | Price, availability, stock, delivery, warranty — the only price reference |
| `product_relations` | Explicit contextual links with a human-readable reason: `install_kit`, `compatible_fitting`, `required_material`, `accessory_pair`, `room_pair`, `alternative` |
| `project_templates` | A type of job, e.g. «بازسازی سرویس بهداشتی» ("bathroom renovation") |
| `project_requirements` | One quantitative/qualitative rule per line item: `per_area`/`fixed` quantity mode, multiplier, min/max, `quality_min`, reason |
| `project_analyses` | A stored interpretation: query, area, quality, budget, estimate, interpreter, intent snapshot (JSONB) |
| `baskets` / `basket_items` | The basket; `unit_price` is never stored, it is always read from `offers.price` |

All money is stored as **integer Toman**.

---

## 4. Setup (preferred path)

```bash
cp .env.example .env
docker compose up --build
```

- Frontend: http://localhost:5173
- API: http://localhost:8000 — interactive docs: http://localhost:8000/docs
- Migrations and the demo seed run automatically on startup.

The stack is a modular monolith: `frontend`, `backend`, `postgres`.

### Backend on the host (no Docker)

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
export DATABASE_URL=postgresql+psycopg://torob:torob@localhost:5432/torob_home
alembic upgrade head          # database migration
python -m app.seed.run        # load the demo dataset (idempotent)
uvicorn app.main:app --reload
```

### Frontend in development mode

```bash
cd frontend
npm install
VITE_API_BASE_URL=http://localhost:8000/api/v1 npm run dev
```

### Make targets

```bash
make up           # start the whole stack
make test         # backend + frontend tests
make migrate      # alembic upgrade head
make seed         # reload the demo dataset
make typecheck    # frontend type check
make down         # stop everything
```

---

## 5. Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://torob:torob@postgres:5432/torob_home` | Backend database connection |
| `TEST_DATABASE_URL` | `.../torob_home_test` | Test database (created automatically if missing) |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` / `POSTGRES_PORT` | `torob` / `torob` / `torob_home` / `5432` | Postgres service |
| `LLM_API_KEY` | — | **Required.** Without it the intent endpoint returns 503 and names the missing variable |
| `LLM_MODEL` | — | **Required. The only model ever contacted.** No default, no fallback, no model list |
| `LLM_BASE_URL` | `https://openrouter.ai/api/v1` | Any OpenAI-compatible endpoint |
| `LLM_TEMPERATURE` | `0` | 0 keeps intent extraction deterministic |
| `LLM_MAX_TOKENS` | `2000` | Upper bound on one reply. A reasoning model spends tokens before it answers |
| `LLM_MAX_TOKENS_ON_TRUNCATION` | `6000` | Retry budget when a reply was cut off mid-thought |
| `LLM_TRUNCATION_RETRIES` | `1` | Retries when the model used its whole budget without answering |
| `LLM_TIMEOUT_SECONDS` | `25` | Per-request timeout |
| `LLM_REFERER` / `LLM_TITLE` | site metadata | Sent as `HTTP-Referer` / `X-Title` |
| `INTENT_TAXONOMY_MAX_BRANDS` | `40` | Brands shown to the interpreter, to bound prompt cost |
| `BACKEND_PORT` / `FRONTEND_PORT` | `8000` / `5173` | Service ports |
| `VITE_API_BASE_URL` | `http://localhost:8000/api/v1` | API base URL baked into the frontend build |
| `LOG_LEVEL` | `INFO` | Backend log level |

---

## 6. Database migration and seed

```bash
cd backend
alembic upgrade head                                    # apply migrations
alembic revision --autogenerate -m "describe change"    # create a migration
python -m app.seed.run                                  # load demo data (wipes and reloads)
python -m app.seed.run --check                          # report current counts only
```

Demo dataset: **23 categories, 92 products, 276 offers from 3 demo sellers, 220
attributes, 69 product relations, 6 project templates, 40 need rules.** Every Persian
product name and price in it is invented for demonstration, and its sellers are
explicitly not real companies; they are flagged `is_demo` in the UI and the API.

This seed still drives the **backend**: intent interpretation, projects, baskets and
optimisation. It is no longer where the frontend's products come from — see
`data/catalog/` below.

---

## 7. Tests

```bash
# Backend (pytest against a real PostgreSQL)
cd backend && pytest -q

# Frontend (vitest + @vue/test-utils)
cd frontend && npm run test:run

# Type checking and lint
cd frontend && npm run typecheck
cd backend && ruff check app tests && mypy app
```

The backend suite (77 tests) covers the required cases: product query classified as
`PRODUCT_SEARCH`, project query classified as `NEED_SEARCH`, product search
returning multiple offers, correct basket totals, project requirements producing the
expected categories, budget optimisation never increasing the total, and the
impossibility of the AI layer fabricating a product. It also asserts that no
user-facing string contains a Latin digit.

The frontend suite (46 tests) covers the stores (server totals are adopted, never
recomputed), the UI primitives (skeleton, empty state, alert, budget amount input),
the seller-comparison and related-products components, the project view (including
the optimisation result), the search view, the basket view, and Persian number,
money and amount-in-words formatting.

---

## 8. Demo scenarios

Everything below works immediately after setup, with no manual database editing.

### A. Product search

1. On the home page type `شیر توکار برند X` and press the search button.
2. Normalised product cards appear with a price range, seller comparison (sorted by
   price), attributes and availability.
3. Open a product: specifications, the full seller table, and **contextual
   recommendations**, each with a reason, e.g.
   «برای نصب این شیر توکار ممکن است به این قطعه نیاز داشته باشید.»
   ("You may need this part to install this in-wall faucet.")
4. "Add to basket" or "add all" builds the recommended basket.

> Honesty note: brand "X" does not exist in the demo catalogue. The UI states this
> explicitly and shows unfiltered results instead of inventing a brand.

### B. Need / project search

1. Type `بازسازی سرویس بهداشتی ۱۲ متری، کیفیت متوسط`
   ("12 m² bathroom renovation, medium quality").
2. The project page opens with the interpreted intent, a checklist of required
   categories, the recommended product for each line with its seller and price, and
   the **estimated total project cost** (73,910,000 Toman with the current seed).
3. Press "change budget / constraints" to change area, quality or budget — the
   basket is recalculated and a new basket is produced.

### C. Budget optimisation

1. On the project or basket page type `بودجه من ۵۵ میلیون است`
   ("my budget is 55 million") or just a number, and press "optimise basket".
2. The result shows before / target / after totals and every change with its reason,
   e.g. «… 10,140,000 تومان کاهش هزینه ایجاد می‌کند», plus an explicit list of the
   quality trade-offs. With the current seed: 73,910,000 → 53,020,000 Toman via
   3 substitutions.

---

## 9. API reference

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/health` | Service and database health |
| GET | `/api/v1/meta/enums` | Domain vocabulary for the UI |
| GET | `/api/v1/meta/demo` | Demo scenarios |
| POST | `/api/v1/search/interpret` | Intent interpretation (structure only) |
| GET | `/api/v1/products/search` | Product search with filters, facets and explanations |
| GET | `/api/v1/products/{id}` | Normalised product detail with all sellers |
| GET | `/api/v1/products/{id}/related` | Contextual related products with reasons |
| GET | `/api/v1/categories`, `/api/v1/brands` | Catalogue metadata |
| GET | `/api/v1/sellers`, `/{id}`, `/{id}/offers` | Sellers and their offers |
| GET | `/api/v1/projects/templates` | Project templates |
| POST | `/api/v1/projects/analyze` | Need analysis + basket creation |
| GET | `/api/v1/projects/{id}` | Stored analysis result |
| POST | `/api/v1/projects/{id}/reanalyze` | Change constraints and recalculate |
| POST / GET | `/api/v1/baskets`, `/api/v1/baskets/{id}` | Create and read a basket (totals server-side) |
| POST / PATCH / DELETE | `/api/v1/baskets/{id}/items[/{item_id}]` | Manage basket items |
| POST | `/api/v1/baskets/{id}/optimize` | Deterministic budget optimisation |
| POST | `/api/v1/baskets/{id}/budget` | Set the target budget on a basket |

Full request/response schemas: http://localhost:8000/docs

---

## 10. Known limitations (v0.1)

- **The product catalogue is backend-owned; the project rules are not.** Products,
  sellers, prices, offers, search and related products all come from
  `data/catalog/products.json`, which the **backend** reads from disk
  (`app/catalog`) and serves under `/api/v1/products/*`. The file is built by
  `make catalog` and enriched with seller offers by `make offers`; there is no
  crawler, so it only changes when it is rebuilt. The database holds only what the
  application owns: baskets, project templates, requirement rules and analyses.
  The frontend never reads or serves the file — it only knows the API.
- **Only project templates and requirement rules are still seeded demo data.** A
  project estimate is therefore rule-based, and the catalogue records no quality,
  so quality cannot rank or constrain anything: candidate selection is by price
  and the API reports quality as `null` rather than assuming it.
- **A project may be partly uncovered.** A template asks for things the catalogue
  does not stock (tiles, lighting, cabinetry). Those roles are reported in
  `missing_categories` and excluded from the estimate, never substituted.
- **Intent interpretation is done by an LLM, always.** There is no
  keyword-matching path in the codebase. Every query goes to the model, which is
  shown the catalogue's real taxonomy (top-level categories, subcategories with
  counts, brands) and asked to map the query onto it. The reply is validated
  against a strict Pydantic schema that has no field for a product, price or
  seller, and every slug it returns is re-checked against the catalogue: one it
  invented is moved to `missing_categories` and never searched for.
  If `LLM_API_KEY` or `LLM_MODEL` is unset, the endpoint returns **503 naming the
  missing variable**. That is deliberate: a silent keyword fallback would answer
  with the same confidence whether or not it understood the sentence, which is
  exactly the failure this design removes.
- The project estimate is **rule-based**: area × rule multiplier × catalogue price.
  It is not a construction cost estimator — no labour, schedule or wastage.
- Budget optimisation substitutes **within the same category** and never drops
  below the project template's quality floor. It does not redesign the basket.
- No authentication, payments or checkout; no multi-language i18n; no ML ranking.
- The active basket is kept in `localStorage` and is not synced across devices.
- Search uses a normalised column with in-process ranking. For a much larger
  catalogue this should move to `pg_trgm` or a search engine; the seam is already
  in place (`catalog/service.py`).

---

## 11. Project layout

```
.
├── backend/            # FastAPI modular monolith (catalog, sellers, search, projects, basket)
├── frontend/           # Vue 3 + TypeScript SPA
├── data/
│   ├── raw/            # untouched Torob search captures (input, never modified)
│   ├── product-pages/  # captured Torob product pages, one per catalogue product
│   └── catalog/        # products.json + normalization-report.json
│                        # the backend-owned catalogue (read from disk, not a DB)
├── scripts/
│   ├── build_catalog.py   # raw captures -> curated products.json
│   └── add_offers.py      # product pages -> seller offers on each product
├── docs/IMPLEMENTATION_PLAN.md
├── docs/UI_DESIGN_GUIDELINES.md
├── docs/UI_AUDIT.md
├── docs/THEME_MIGRATION.md
├── docs/PALETTE_MIGRATION.md
├── docs/MATERIAL_MIGRATION.md  # current design system: Material Design 2
├── opencode.json         # VibeFarsi MCP server (Persian RTL design reference)
├── docker-compose.yml  # postgres + backend + frontend
├── Makefile            # up / test / migrate / seed / catalog / offers / typecheck
└── .env.example
```
