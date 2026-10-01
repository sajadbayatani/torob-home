# Torob-Home — ترب خونه

**An intent-driven home procurement platform.** You say what you want done in your
home — not what you want to buy — and the system turns that into a costed, sourced
plan.

<div dir="rtl">

**[نسخهٔ فارسی — Persian version](README.fa.md)**

</div>

```
a sentence → intent → requirements → catalogue products → selection list → budget & sellers
```

> **This is a demo.** The catalogue is 70 real product listings captured from
> [Torob](https://torob.com), the Iranian shopping site, with up to 5 seller offers
> each. Everything else the system produces — requirements, estimates, project
> reasoning — is generated, and the API says so rather than pretending otherwise.

**Two languages, one codebase.** This document is English;
[README.fa.md](README.fa.md) is the same document in Persian, and the application
itself is Persian-first and RTL throughout.

---

## Contents

1. [What it does](#1-what-it-does)
2. [The rule that shapes everything](#2-the-rule-that-shapes-everything)
3. [Architecture](#3-architecture)
4. [The pipeline, end to end](#4-the-pipeline-end-to-end)
5. [The demo dataset](#5-the-demo-dataset)
6. [Product decisions](#6-product-decisions)
7. [Technical decisions](#7-technical-decisions)
8. [Setup](#8-setup)
9. [Configuration](#9-configuration)
10. [API reference](#10-api-reference)
11. [Tests](#11-tests)
12. [Project layout](#12-project-layout)
13. [Known limitations](#13-known-limitations)

---

## 1. What it does

Three flows, all reachable from the home page with no setup:

**Product search** — `یه شیر توالت خوب میخوام`
You describe the thing. The interpreter decides you meant a product, the
catalogue answers with normalised cards, and each card carries its reasons —
which of your words matched, and why. Open one and you get the full seller table,
specifications, and the parts that go *with* it, each with a stated reason.

**Project search** — `بازسازی سرویس بهداشتی ۱۲ متری، کیفیت متوسط`
You describe a *job*. The interpreter produces `project_search`, and the harder
half begins: the model writes the **requirements** — what has to be bought to
finish this job, which the user never enumerated. Those requirements are resolved
against the catalogue into concrete products, and you get a needs checklist, a
recommendation per line, an unmet-needs list for anything the shop doesn't stock,
and an estimated project total.

**Budget optimisation** — from either page, one button
Re-evaluates the project and the current selection together against the numbers
you just typed, then shows before → target → after, with every substitution and
its quality trade-off spelled out.

### Why the project flow is the interesting one

Product search is a solved problem: you have a query, you have a catalogue. The
project flow has no query. `بازسازی سرویس بهداشتی` names no products at all — it
names a room and an action — so somebody has to decide that a bathroom renovation
means waterproofing, plumbing, sanitary ware, mirrors, lighting and paint, and
that this one needs about 39 m² of tile. That decision is the product.

---

## 2. The rule that shapes everything

> **The interpretation layer produces structure only.**
> Products, sellers, prices, availability and product relationships are always
> read from the catalogue — by the model or by the code behind it.

This is structural, not a convention:

- `InterpretedIntent` (`backend/app/domains/search/schemas.py`) has **no field**
  for a product, offer, price or seller. The interpreter is not able to represent
  an invented product, because there is nowhere to put one.
- Every request and response model inherits `StrictModel` with `extra="forbid"`.
  A model that returns an unrecognised key is a validation error, not a shrug.
- Every model response is additionally validated against a strict Pydantic schema
  and passed through `response_format=json_schema`.
- No monetary total is ever produced by a model. All money is computed on the
  server, in integers, in Toman.
- If a slug the model returns is not in the catalogue, it is moved to
  `missing_categories` and never searched for.

The failure this removes is specific: an LLM that may name products will name
products, confidently, whether or not they exist. Everything below is downstream
of making that impossible rather than unlikely.

---

## 3. Architecture

A **modular monolith**: one backend, one frontend, one database. Three containers.

```
                    ┌─────────────────────────────────────┐
  browser  ────────▶│  frontend   Vue 3 · TS · Tailwind   │
                    └───────────────┬─────────────────────┘
                                    │  REST /api/v1  (JSON)
                    ┌───────────────▼───────────────────────┐
                    │  backend    FastAPI · SQLAlchemy 2    │
                    │                                       │
                    │   search  →  projects  →  basket      │
                    │      │          │           │         │
                    │      └──────────┴───────────┘         │
                    │            catalog (file + API)       │
                    │            llm     (OpenRouter)       │
                    └───────────────┬───────────────────────┘
                                    │
                          ┌─────────▼─────────┐
                          │  PostgreSQL       │  baskets, analyses,
                          │                   │  templates, need rules
                          └───────────────────┘

                    ┌─────────────────────────────────────┐
                    │  data/catalog/*.json  (read-only)   │  70 Torob products
                    └─────────────────────────────────────┘
```

### Repository layout

```
.
├── backend/                   FastAPI modular monolith
│   ├── app/
│   │   ├── main.py            app factory, exception handlers, request ids
│   │   ├── api/v1.py          router aggregation + /meta endpoints
│   │   ├── core/              settings, domain enums, Persian text utilities
│   │   ├── db/                engine, session, declarative base
│   │   ├── catalog/           the catalogue itself (see below)
│   │   ├── llm/               OpenRouter client: chat_json, schema, errors
│   │   ├── seed/              deterministic demo dataset + CLI
│   │   └── domains/
│   │       ├── catalog/       HTTP: products, facets, categories, brands
│   │       ├── sellers/       HTTP: sellers and their offers
│   │       ├── search/        HTTP + interpretation engine
│   │       ├── projects/      HTTP + project analysis and reasoning
│   │       └── basket/        HTTP + selection list and optimiser
│   ├── alembic/               migrations
│   └── tests/                 unit / api / manual trace harnesses
├── frontend/                  Vue 3 + TypeScript SPA
│   ├── src/
│   │   ├── api/               the only place that speaks HTTP
│   │   ├── stores/            search, catalog, selection (Pinia)
│   │   ├── components/        ui · product · search · basket · project
│   │   ├── composables/       useThinkingStates
│   │   ├── views/             Home · Search · Product · Project · Selection
│   │   ├── theme/             material.css — the design tokens
│   │   ├── types/api.ts       TypeScript mirror of the API models
│   │   └── utils/format.ts    the single number and money formatter
│   └── tests/                 vitest + @vue/test-utils
├── data/
│   ├── raw/                   untouched Torob search captures
│   ├── product-pages/         captured product pages, one per product
│   └── catalog/               the enriched catalogue the app reads
├── scripts/                   build_catalog.py · add_offers.py
├── docs/                      design system notes and migration records
├── docker-compose.yml         postgres + backend + frontend
├── Makefile                   up · test · migrate · seed · catalog · offers
└── .env.example
```

`app/catalog/` is deliberately *not* under `app/domains/`. It is the data layer,
not a domain: it reads the file, builds the index, matches words to subcategories,
and knows about complementary products. The HTTP domain above it only formats
answers.

---

## 4. The pipeline, end to end

This is the part worth reading carefully, because it is where the design lives.

```
  1. interpretation        sentence  →  typed intent (strict schema)
  2. requirements         intent    →  what must be bought to finish the job
  3. requirement mapping  words     →  subcategory slugs in the catalogue
  4. candidate generation slugs     →  eligible products under hard constraints
  5. complementary        products  →  what the file says goes with them
  6. reasoning prompt     all of it →  one structured question
  7. reasoning model      prompt    →  a proposal (validated, then re-checked)
  8. final selections     proposal  →  accepted, with rejected ones explained
```

### 1. Interpretation

One model call. The prompt carries the catalogue's own taxonomy — rooms,
subcategories with counts, brands — and the schema is strict. Three intents:
`PRODUCT_SEARCH`, `NEED_SEARCH`, `UNKNOWN`.

The prompt had to be taught the shape of its own output. A model once returned
`search`, `confidence` and `explanations` *nested inside* `project`; because the
schema forbids extra keys, a semantically perfect interpretation was discarded as
a validation error. The prompt now states the output hierarchy explicitly, names
the two different `constraints` fields apart, and asks for one JSON object with no
reasoning around it.

### 2. Requirements

For a project, the model writes the shopping list the user did not say out loud.
The rules it must follow are in the prompt and are enforced by tests:

- Requirements are **outcome-derived**. What has to be acquired to reach the
  result the user described.
- **No umbrella words.** "تجهیزات" (equipment) is not a requirement; its parts are.
- No brand, model, seller, price or catalogue id in a requirement. Requirements
  name *kinds of things*, never a specific product.
- Catalogue availability is irrelevant — a need with no product is still a need,
  and is reported as unmet.
- `quantity` is a **project** quantity ("how much tile this floor takes"), never a
  purchasing quantity. This distinction is load-bearing and has its own test.

### 3. Requirement → subcategory mapping

The other half of "the model understands, the backend resolves". A requirement
carries words; the catalogue knows which words it uses for each subcategory. Both
are reduced to words and matched **word by word**.

Substring matching is what it replaced, and it produced two errors: "مبل" (sofa)
matched "مبلمان" (furniture), and "میز تحریر" failed against "میز کار". Both are
covered by tests.

A word only counts as evidence when the file offers it as a *way into* that
subcategory (its label or a search term) **and** not too many subcategories share
it. "مبلمان" is the category label on all eight furniture subcategories, so it is
evidence for all of them and therefore for none — the threshold is measured from
the file, not listed in code.

One subtlety worth recording, because it caused a real regression: **the room is
not evidence.** `آینه سرویس بهداشتی` is the only bathroom label that spells the
room out; the rest are bare (`روشویی`, `توالت`). The room words were therefore
vocabulary for that one subcategory at the highest weight, and being rare their
frequency never disqualified them — so plumbing and lighting requirements came
back as mirrors. The room is already applied by `RoomScope.admits`; reading it out
of the words a second time adds nothing and inverts the ranking. Room words are
now dropped before scoring.

### 4–5. Candidates and complements

A product is offered only if the enriched file places it in one of this project's
rooms, allows this kind of job, has the right quality, and can actually be bought.
The first candidate is the cheapest suitable one, so behaviour without a model is
unchanged.

Complements come from the file's own declared relationships, for a *different*
subcategory, room-filtered like anything else. A second product of the same
subcategory is an alternative, never a complement.

### 6–8. Reasoning, and why it is optional

A project where every need has exactly one candidate costs **no model call at
all** — the deterministic order is already the only answer there is.

When there is a choice, one call receives the plans and answers with a proposal.
`_validate` then re-checks every product id against the candidate set. A proposal
naming something we never offered is dropped, with a reason recorded. The model
proposes; it does not decide.

---

## 5. The demo dataset

Measured from `data/catalog/products_70_enriched.json`:

| | |
|---|---|
| Products | **70**, every one captured from Torob |
| Seller offers | **225**, from **178** seller storefronts |
| Offers per product | 1 (×27), 2 (×2), 3 (×5), 4 (×1), **5** (×35) |
| Subcategories | 22 |
| Top-level categories | 4 — `bathroom`, `kitchen`, `furniture`, `appliances` |
| Rooms | 8 — bathroom, bedroom, dining_room, home_office, kitchen, living_room, utility_room, whole_home |
| Brands | 36 |
| Structured attributes | 42 |
| Projects with no product in the catalogue | tiles, waterproofing, plumbing, lighting, paint |

The offers-per-product distribution is the honest picture: a third of the listings
have the full five sellers, and over a third have exactly one. There is no
artificial padding of the seller tables.

`data/raw/` holds the untouched search captures and `data/product-pages/` the page
captures they came from; `scripts/build_catalog.py` turns those into the curated
file and `scripts/add_offers.py` attaches seller offers. Neither modifies the raw
input.

---

## 6. Product decisions

Decisions about what the product *is*, as opposed to how it is built. Each one is
a decision someone could reasonably have made differently.

**The project is the primary object, not the product.** A user renovating a
bathroom does not want a shopping list; they want to know what the job costs and
what to buy. The project flow is therefore the spine of the app, and product
search is the narrower path that feeds it.

**Nothing reaches the basket by itself.** A recommendation is advice. The project
starts with an empty selection list, and a click is what fills it. There is one
button to select a whole project for the impatient case, and per-item buttons for
everyone else — but an empty list is still the starting state.

**A need we cannot supply is still a need.** It is shown, named, and excluded
from the estimate. It is never quietly dropped, and never substituted with
"something nearby", because inventing a requirement is worse than admitting a gap.

**No quantity in a selection.** It was removed. A quantity implies "buy this many",
which the shop cannot honour for a mirror or a faucet that is bought by the set,
and the user never asked for it. The number that survives is a project's
requirement quantity, which answers a different question and stays.

**One optimise button, not two.** Re-evaluating the project and optimising the
basket are the same decision, so they are one button that does both against the
values in the form. Optimisation never re-interprets the query — interpreting it
again would make the button mean two things.

**Explanations next to the result, not behind a disclosure.** The store's own
language first, the model's reasons second. A product with neither is labelled as
unexplained rather than presented as self-evident.

**The selection list, not a basket.** No checkout, no payment, no quantity, no
"cart". What exists is a list of things to buy, and it is called that.

**No invented social proof.** No ratings, no review counts, no popularity
percentages. The catalogue has none, and a demo that invents them teaches the
wrong lesson about what the system knows.

**Persian and RTL are the default, not a locale.** `dir="rtl"` everywhere, logical
CSS properties only (`ms-`/`me-`/`ps-`/`pe-`/`start-`/`end-`), Persian digits in
every visible number, `٬` for thousands, Toman always after the figure, and no
`letter-spacing` on Persian text.

---

## 7. Technical decisions

**FastAPI + Pydantic v2 + SQLAlchemy 2 + PostgreSQL, as a modular monolith.** One
deployable, clear internal boundaries. The catalogue is a file rather than a table,
which is the one place this pays off: the data is versioned, diffable, and
reviewable, and the vocabulary the matcher uses can be inspected directly.

**The catalogue is read from disk, not stored in the database.** Products, prices
and offers are a *given* — captured from Torob — not something the application
owns. The database holds only what the application owns: baskets, selection items,
project analyses, templates and need rules. This keeps the "never invent a product"
rule enforceable by construction.

**`extra="forbid"` everywhere.** A shared `StrictModel` base makes a schema change
a breaking change instead of a silent widening. It is the mechanism behind the
whole product rule.

**One number formatter, on the frontend; one money authority, on the backend.**
`utils/format.ts` is the only place digits are turned into text. The backend never
trusts a total from the client and never emits one from a model.

**Pydantic models are mirrored once, by hand, in `types/api.ts`.** Generated
client types would be another build step; a hand-written mirror is reviewable and
`vue-tsc` catches drift at compile time.

**Pinia holds only genuinely shared state.** Search flow, catalogue cache,
selection. Component-local state stays local.

**Tailwind is mapped onto design tokens and defines no colour of its own.**
`theme/material.css` is the single source of truth; `theme.spec.ts` fails the build
if a component hard-codes a colour, radius, shadow or duration.

**The LLM client is one module with a strict contract.** `chat_json(system, user,
schema_model)` validates every reply and distinguishes "the model refused" from
"the model was cut off mid-thought" from "no key". The last two retry with a larger
budget once; the first does not, because retrying a refusal is how you get a
different refusal.

**One reasoning call per decision, and only when there is a decision.** Both
project reasoning and basket optimisation generate candidates deterministically
first and ask the model only to choose or to justify. `finish_reason=length` is
read and reported rather than parsed hopefully.

**Tests pin properties, not examples.** The requirement tests assert that a sofa
requirement and a bed requirement produce *different* lists, so a hardcoded
room→requirements table fails them. A test that hardcodes the expected answer *is*
the bug it is meant to catch.

---

## 8. Setup

### With Docker (preferred)

```bash
cp .env.example .env
docker compose up --build
```

| | |
|---|---|
| App | http://localhost:5173 |
| API | http://localhost:8000 |
| Interactive docs | http://localhost:8000/docs |

Migrations run on startup. No key is required for the catalogue, product search or
the project page — only for live intent interpretation.

### Backend on the host

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

export DATABASE_URL=postgresql+psycopg://torob:torob@localhost:5432/torob_home
export CATALOG_PATH=../data/catalog/products_70_enriched.json

alembic upgrade head          # migrations
python -m app.seed.run        # demo dataset (idempotent)
uvicorn app.main:app --reload
```

> `CATALOG_PATH` is resolved **relative to the backend directory**. The default
> already points at the committed catalogue, so it rarely needs setting.

### Frontend in development

```bash
cd frontend
npm install
npm run dev            # VITE_API_BASE_URL defaults to http://localhost:8000/api/v1
```

### Make targets

```bash
make up             # whole stack
make test           # backend + frontend
make migrate        # alembic upgrade head
make seed           # reload the demo dataset
make catalog        # data/raw → data/catalog
make offers         # product pages → seller offers
make typecheck      # frontend
make down           # stop everything
```

---

## 9. Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://torob:torob@localhost:5432/torob_home` | Database |
| `TEST_DATABASE_URL` | — | Test database, created if missing |
| `CATALOG_PATH` | `../data/catalog/products_70_enriched.json` | Catalogue file, relative to `backend/` |
| `PRODUCT_SOURCE` | `local` | `local` or `mcp` |
| `TOROB_MCP_URL` | — | Required when `PRODUCT_SOURCE=mcp` |
| `LLM_API_KEY` | — | **Required for interpretation.** Without it the endpoint returns 503 naming the variable |
| `LLM_MODEL` | — | **Required.** The only model ever contacted. No default, no fallback, no list |
| `LLM_BASE_URL` | — | Any OpenAI-compatible endpoint (OpenRouter by default) |
| `LLM_TEMPERATURE` | `0` | 0 keeps interpretation deterministic |
| `LLM_REASONING_EFFORT` | `low` | `minimal`/`low`/`medium`/`high`, sent for **interpretation only** |
| `LLM_MAX_TOKENS` | `2000` | One reply's budget. A reasoning model spends tokens before it answers |
| `LLM_MAX_TOKENS_ON_TRUNCATION` | `6000` | Retry budget when a reply was cut off |
| `LLM_TRUNCATION_RETRIES` | `1` | Retries on a truncated reply |
| `LLM_TIMEOUT_SECONDS` | `650` | Per-request timeout |
| `LLM_LOG_PAYLOADS` | `false` | Log full prompts and replies (off by default) |
| `INTENT_TAXONOMY_MAX_BRANDS` | `40` | Brands shown to the interpreter, to bound prompt cost |
| `COMPLEMENTARY_CANDIDATE_LIMIT` | `24` | Candidates considered when proposing complements |
| `COMPLEMENTARY_MAX_RESULTS` | `6` | Complements shown per analysis |
| `CORS_ORIGINS` | localhost dev origins | Allowed origins |
| `VITE_API_BASE_URL` | `http://localhost:8000/api/v1` | API base for the frontend build |

> **Which model you run is a decision, not a detail.** The prompt is tuned against
> one model family and its JSON adherence is not portable. A model that narrates
> before answering will exhaust the budget on narration and return
> `finish_reason=length`, and the failure looks like a backend bug rather than a
> model choice. Change `LLM_MODEL` deliberately and watch the reasoning logs.

---

## 10. API reference

Base path `/api/v1`. Interactive documentation at `/docs`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Service and database health |
| GET | `/meta/enums` | Domain vocabulary for the UI |
| GET | `/meta/demo` | Demo scenarios |
| GET | `/search/route` | Deterministic product/project verdict, no model |
| POST | `/search/interpret` | Intent interpretation — structure only |
| GET | `/products/search` | Product search: filters, facets, explanations |
| GET | `/products/facets` | Facets for the current filters |
| GET | `/products/meta` | Catalogue size and shape |
| GET | `/products/{id}` | Product detail with every seller |
| GET | `/products/{id}/similar` | Alternatives from the same subcategory |
| GET | `/products/{id}/complementary` | What the file says goes with it, with reasons |
| GET | `/categories` | Subcategories present in the catalogue |
| GET | `/brands` | Brands present in the catalogue |
| GET | `/sellers` · `/{id}` · `/offers/search` | Sellers and their offers |
| GET | `/projects/templates` | Project templates |
| POST | `/projects/analyze` | Analyse a query: requirements, needs, candidates, estimate |
| GET | `/projects/{id}` | A stored analysis |
| POST | `/projects/{id}/reanalyze` | Change constraints and re-analyse |
| POST | `/projects/{id}/optimize` | Project + selection in one action |
| GET | `/projects/{id}/complementary` | Complementary candidates for an analysis |
| POST · GET | `/baskets` · `/baskets/{id}` | Create and read a selection list |
| POST · PATCH · DELETE | `/baskets/{id}/items[/{item_id}]` | Manage items |
| DELETE | `/baskets/{id}` | Clear a list |
| POST | `/baskets/{id}/optimize` | Deterministic budget optimisation |
| POST | `/baskets/{id}/budget` | Set the target budget |

---

## 11. Tests

```bash
make test                # everything

cd backend  && .venv/bin/python -m pytest -q
cd frontend && npm run test:run && npm run typecheck
```

**Backend — 673 tests across 28 files: 666 passing, 7 known failures.** The
failures are all in complementary-candidate selection and predate the rest of this
work; they are listed in [Known limitations](#13-known-limitations) rather than
quietly rounded off. Areas worth naming:

- interpretation structure and the strict schema, including the exact payload that
  used to be rejected;
- requirement semantics as properties (a sofa and a bed differ), never as lists;
- room words are not evidence — the regression above, pinned;
- budget optimisation never raises the total, and never calls the model twice;
- the model may never fabricate a product: invented ids are dropped with a reason;
- one model's reply cannot influence another domain's candidates.

**Frontend — 165 passing.** Stores, UI primitives, product and selection
experiences, the project view and the requirements table, thinking states, and
guards that assert removed concepts stay removed (quantity, related products).

Type checking is part of the frontend build: `npm run build` runs `vue-tsc` first,
so a type error fails the build rather than shipping.

Two guards are worth calling out because they are unusual and intentional:

- `noQuantityOrRelated.spec.ts` reads the **source** of the store and views and
  fails if the words come back. It is a lint expressed as a test.
- `theme.spec.ts` fails if any component hard-codes a colour, radius, shadow or
  duration instead of using a token.

---

## 12. Project layout

```
.
├── backend/                   FastAPI modular monolith
│   ├── app/
│   │   ├── main.py            app factory and exception handlers
│   │   ├── api/v1.py          router aggregation, /meta endpoints
│   │   ├── core/              config, enums, Persian text folding, request ids
│   │   ├── db/                SQLAlchemy engine, session, base
│   │   ├── catalog/           catalogue index, matcher, selection, sources,
│   │   │                      complementary products, projections
│   │   ├── llm/               OpenRouter client: chat_json, schema, errors
│   │   ├── seed/              demo dataset and CLI
│   │   └── domains/
│   │       ├── catalog/       products, facets, categories, brands
│   │       ├── sellers/       sellers and offers
│   │       ├── search/        interpretation: engine, schema, taxonomy, routing
│   │       ├── projects/      analysis, needs, quantity rules, reasoning
│   │       └── basket/        selection list and optimiser
│   ├── alembic/versions/      0001 schema · 0002 catalog json · 0003 reasoning · 0004 needs
│   └── tests/{unit,api,manual}/
├── frontend/
│   ├── src/
│   │   ├── api/               client · search · products · projects · baskets
│   │   ├── stores/            searchStore · catalogStore · selectionStore
│   │   ├── composables/       useThinkingStates
│   │   ├── components/
│   │   │   ├── ui/            AlertBox · EmptyState · ExplanationPanel · PriceTag · Skeleton
│   │   │   ├── product/       ProductCard · OfferComparison · CatalogueImage · AvailabilityBadge · SimilarList
│   │   │   ├── search/        SearchBar · ThinkingStates
│   │   │   ├── basket/        BudgetAmountInput
│   │   │   └── project/       Table (requirements)
│   │   ├── views/             HomeView · SearchView · ProductView · ProjectView · SelectionView
│   │   ├── theme/material.css design tokens — single source of truth
│   │   ├── types/api.ts       TypeScript mirror of the API
│   │   └── utils/format.ts    Persian numbers and Toman
│   └── tests/
├── data/
│   ├── raw/                   untouched Torob search captures
│   ├── product-pages/         captured product pages
│   └── catalog/               products_70_enriched.json · normalization-report.json
├── scripts/                   build_catalog.py · add_offers.py
├── docs/                      UI_DESIGN_GUIDELINES · UI_AUDIT · MATERIAL_MIGRATION · THEME_MIGRATION · PALETTE_MIGRATION · IMPLEMENTATION_PLAN
├── docker-compose.yml · Makefile · .env.example · .env
```

### The data pipeline

```
data/raw/*.json          Torob search captures, never modified
        │  scripts/build_catalog.py
        ▼
data/catalog/products_70_enriched.json     curated + attributed
        │  scripts/add_offers.py
        ▼
products[].offers[]     seller, price, availability, stock
        │
        ▼
app/catalog/store.py     the index every other layer reads
```

The catalogue file is committed. It is 840 KB and diffable, which is the point:
a change in vocabulary is a reviewable change, not a migration.

---

## 13. Known limitations

These are real and worth stating plainly.

- **The catalogue is small and partial.** 70 products across 4 categories. Tiles,
  waterproofing, plumbing, lighting and paint are **not in it**, so a bathroom
  renovation is only partly answerable. Those needs appear as unmet, which is the
  honest outcome, but it means the flagship demo scenario is visibly incomplete.
- **The catalogue records no quality.** Every product's quality is `null`, so
  quality cannot rank or constrain anything. The API reports it as `null` rather
  than guessing, and candidate selection falls back to price. `quality_min` on a
  requirement is therefore carried but not enforced against products.
- **Estimates are material-only.** Area × rule × catalogue price. No labour, no
  schedule, no wastage, no contractor margin. It is not a construction estimate.
- **A project may be partly uncovered,** and will be, for the categories above.
  `missing_categories` reports the gap; nothing is substituted for it.
- **Seller records are per-listing, not deduplicated.** 225 offers come from 178
  storefronts because the same seller appears under a different identity on
  different product pages. Aggregating them properly needs a seller-matching pass
  the demo does not have.
- **Ten tests are red, and they are known.** Seven in the backend, all in
  complementary-candidate selection (`TestProjectComplementary`,
  `TestReasoningStatusIsReported`, one in `test_complementary`): the complementary
  pool comes back empty where a mirror-driven or missing mapping used to fill it,
  so `not_needed` is reported where `ok` was expected. Three in the frontend: one
  brand-colour assertion in `theme.spec.ts` and two explanation-string assertions in
  `views.spec.ts`. All predate this documentation and none is caused by it. They are
  left visible rather than skipped or deleted, because a suite that hides its
  failures stops being evidence.
- **Prompt adherence is a property of the model, not of this code.** The prompt
  states the output hierarchy explicitly, but a model that narrates before
  answering can still exhaust the token budget and return `finish_reason=length`.
  That failure is reported, not worked around.
- **Complementary candidates multiply by mapped subcategory.** A need that resolves
  to three subcategories proposes complements for all three. Correct, but it makes
  the reasoning prompt larger than it needs to be.
- **No authentication, no payments, no checkout.** No multi-language UI — the
  application is Persian only; this README is bilingual. No ML ranking.
- **The selection list lives in `localStorage`** and is not synced across devices.
- **Catalog search is in-process** over a normalised column. For a catalogue orders
  of magnitude larger this belongs in `pg_trgm` or a search engine; the seam is
  already in `app/catalog/store.py`.

---

<div dir="rtl">

## پروانه

این پروژه برای نمایش ساخته شده است. داده‌های محصولات از وب‌سایت توروب گرفته شده و
مالکیت آن‌ها متعلق به صاحبانشان است.

</div>

**Licence.** Not published. All rights reserved.
