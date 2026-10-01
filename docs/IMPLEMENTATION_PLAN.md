# Implementation Plan --- Home Procurement Platform (MVP)

**Status: implemented architecture / living technical record**

This document records the implementation decisions that define the
current MVP architecture. It supersedes the earlier implementation plan
where that plan described a rule-driven project engine, product
quantities, basket-owned prices, LLM fallback behavior, or
database-owned catalogue data.

The implementation evolved during development. The important principle
is to document the architecture that actually exists now, including the
boundaries between deterministic backend logic, catalogue data, and
LLM-assisted reasoning.

------------------------------------------------------------------------

## 0. Repository and implementation context

The project is a prototype home procurement platform built from scratch
around a Persian-first, RTL experience.

The current implementation is a modular monolith:

``` text
Frontend
   ↓ REST / JSON
FastAPI backend
   ├── search
   ├── projects
   ├── basket / selection list
   ├── catalogue
   ├── sellers
   └── LLM infrastructure
   ↓
PostgreSQL + versioned catalogue data
```

The catalogue is intentionally kept as a versioned data artifact rather
than being treated as ordinary application-owned product state.

The project has also been designed around a strict separation:

``` text
Semantic interpretation
        ≠
Catalogue truth
        ≠
Application state
        ≠
LLM reasoning
```

That separation is the main architectural constraint behind the
implementation.

------------------------------------------------------------------------

# 1. Core architectural decisions

  -----------------------------------------------------------------------
  Topic                   Current decision        Reason
  ----------------------- ----------------------- -----------------------
  Architecture            Modular monolith        Clear domain boundaries
                                                  without
                                                  distributed-system
                                                  overhead

  Backend                 FastAPI + SQLAlchemy    Typed API and explicit
                          2 + Pydantic v2 +       persistence boundaries
                          PostgreSQL + Alembic    

  Frontend                Vue 3 + TypeScript +    Existing frontend stack
                          Vite + Router + Pinia + and Persian RTL support
                          Tailwind                

  Catalogue               Versioned enriched JSON Product truth must be
                          / pluggable product     inspectable and
                          source                  independent from
                                                  application state

  Product source          `ProductSource`         Allows source switching
                          abstraction with local  without changing
                          JSON and Torob MCP      business logic
                          implementations         

  Search routing          Deterministic           Obvious product queries
                          product-first routing   should not spend an LLM
                                                  call

  Interpretation          LLM only when the query Semantic understanding
                          is not confidently a    is needed for
                          direct product query    broad/project intent

  LLM commercial          None                    Model must not invent
  authority                                       products, sellers,
                                                  prices or catalogue
                                                  availability

  Project requirements    Semantically derived by A project query does
                          the interpretation      not explicitly
                          layer                   enumerate everything
                                                  that must be purchased

  Requirement resolution  Deterministic catalogue Catalogue vocabulary,
                          matcher                 not model output,
                                                  decides which real
                                                  subcategories exist

  Candidate generation    Deterministic           Hard constraints must
                                                  be enforceable and
                                                  reproducible

  Project reasoning       Bounded LLM reasoning   Model is useful for
                          over backend-generated  choosing/explaining
                          candidates              among valid options

  Optimisation            Deterministic candidate Avoids re-interpreting
                          generation + one        the same query and
                          bounded reasoning       avoids unrestricted
                          decision when required  model search

  Selection list          Product-ID based,       It is not a checkout
                          explicit user selection cart

  Product quantity        Removed                 Current flow is
                                                  selection/comparison,
                                                  not purchasing quantity
                                                  management

  Requirement quantity    Retained                Represents project need
                                                  quantity, not number of
                                                  products to buy

  Price authority         Catalogue / offer       No client or
                          data + backend          model-generated
                          calculations            monetary totals

  Authentication          Not part of MVP         Not required for the
                                                  prototype flow

  UI language             Persian-first, RTL      Core product experience
                                                  is Persian

  Design system           Material Design 2       Consistent UI without
                          reference + project     arbitrary
                          design tokens           component-level styling
  -----------------------------------------------------------------------

------------------------------------------------------------------------

# 2. The system boundary

The system is intentionally divided into four responsibilities.

``` text
┌─────────────────────────────┐
│ User language               │
└──────────────┬──────────────┘
               ↓
┌─────────────────────────────┐
│ Semantic interpretation     │
│ LLM when required           │
└──────────────┬──────────────┘
               ↓
┌─────────────────────────────┐
│ Deterministic domain logic  │
│ requirements → catalogue    │
│ candidates → constraints    │
└──────────────┬──────────────┘
               ↓
┌─────────────────────────────┐
│ Optional bounded reasoning  │
│ choose / compare / explain  │
└──────────────┬──────────────┘
               ↓
┌─────────────────────────────┐
│ Validated application state │
│ project / selection list    │
└─────────────────────────────┘
```

The LLM is therefore not the application.

It is one component inside a deterministic application.

------------------------------------------------------------------------

# 3. Search architecture

## 3.1 Product-first routing

Every search starts with a deterministic product matcher.

``` text
query
  ↓
product matcher
  ├── clear product match → product search
  └── not clearly a product → LLM interpretation
```

The matcher has one narrow job:

> Prove that the query is sufficiently close to a known product search.

It does not attempt to solve arbitrary natural-language understanding.

### Why this boundary exists

A query such as:

``` text
سینک ظرفشویی
```

should not require an LLM merely to discover that the user wants a sink.

A query such as:

``` text
بازسازی سرویس بهداشتی ۱۲ متری
```

does require semantic interpretation because the user described a
project rather than a product.

This reduces unnecessary model calls and makes the most common
direct-search path deterministic.

------------------------------------------------------------------------

# 4. Intent interpretation

Queries that are not confidently product-first are interpreted once.

The interpretation schema represents structure rather than commercial
data.

Conceptually:

``` json
{
  "intent": "project_search",
  "category": null,
  "project": {
    "type": "renovation",
    "room": "سرویس بهداشتی",
    "room_token": "bathroom",
    "area_m2": 12,
    "goal": "بازسازی سرویس بهداشتی",
    "constraints": [],
    "requirements": []
  },
  "search": null,
  "constraints": {
    "quality": "medium",
    "budget": null,
    "notes": []
  },
  "constraint_kind": "QUALITY",
  "confidence": 0.99,
  "explanations": []
}
```

Supported intents:

``` text
product_search
project_search
unknown
```

The interpretation layer may determine:

-   user intent;
-   project type;
-   room;
-   canonical room token;
-   area;
-   stated goal;
-   requirements;
-   explicit quality;
-   explicit budget;
-   search terms.

It must not become a product database.

There are no authoritative product IDs, sellers, prices or offers in the
interpretation contract.

------------------------------------------------------------------------

# 5. Strict LLM contract

The LLM client uses structured JSON output and Pydantic validation.

Models use strict schemas with:

``` text
extra = forbid
```

The response must therefore satisfy both:

1.  semantic expectations;
2.  exact structural expectations.

A semantically good answer with an invalid object hierarchy is still
rejected.

This became important after a model produced a response where fields
that belonged at the root were incorrectly nested inside `project`.

The prompt explicitly describes the root hierarchy to reduce this class
of failure.

------------------------------------------------------------------------

# 6. Canonical constraint values

Natural-language quality terms are normalized into canonical values.

  User wording                     Canonical value
  -------------------------------- -----------------
  اقتصادی / معمولی / پایه          `low`
  متوسط                            `medium`
  خوب / باکیفیت                    `high`
  لوکس / بسیار باکیفیت / پریمیوم   `ultra`

The schema remains canonical.

The model maps user language into the schema rather than the backend
weakening its validation rules.

Budget is represented as a structured numeric constraint and is enforced
downstream by deterministic code.

------------------------------------------------------------------------

# 7. Project requirement generation

Project search is different from product search because the user often
does not enumerate the required products.

For example:

``` text
بازسازی سرویس بهداشتی ۱۲ متری
```

does not explicitly list every procurement need.

The interpretation layer therefore derives semantic requirements.

A requirement is a procurement concept, not a catalogue product.

Example:

``` json
{
  "description": "شیرهای سرویس بهداشتی",
  "terms": ["شیر", "توالت"],
  "quantity": 1,
  "required": true,
  "quality_min": "medium"
}
```

Requirements must not contain:

-   product IDs;
-   product model names;
-   sellers;
-   prices;
-   catalogue-specific identifiers.

Requirements remain valid even when the catalogue cannot satisfy them.

That distinction is essential:

``` text
need exists
      ≠
catalogue product exists
```

An unmet need is therefore a valid result.

------------------------------------------------------------------------

# 8. Requirement quantity vs product quantity

This distinction is deliberately preserved.

### Requirement quantity

Describes the project's need:

``` text
۱۲ متر فضا
→ a requirement may need a calculated amount
```

### Product quantity

Would mean:

``` text
buy N units of this exact catalogue product
```

The second concept is outside the current product.

Product-level quantity was removed from:

-   catalogue/product representations;
-   API models;
-   selection items;
-   frontend product/selection UI.

The selection list is therefore product-ID based and idempotent.

Requirement quantity remains because it belongs to project semantics
rather than checkout semantics.

------------------------------------------------------------------------

# 9. Canonical catalogue

The current canonical dataset contains 70 manually selected products.

Top-level domains:

``` text
bathroom
kitchen
furniture
appliances
```

The enriched catalogue contains semantic metadata such as:

``` text
rooms
product_roles
use_cases
project_types
space_fit
styles
features
search_terms
complementary_subcategories
alternative_subcategories
```

The metadata is generated/enriched once and committed as the canonical
dataset.

It is not regenerated by an LLM on every request.

------------------------------------------------------------------------

# 10. Catalogue source abstraction

Catalogue access is abstracted behind:

``` text
ProductSource
├── LocalJsonProductSource
└── TorobMcpProductSource
```

Configuration:

``` env
PRODUCT_SOURCE=local
TOROB_MCP_URL=https://torob-mcp.sajjadbayatani.workers.dev/mcp
```

or:

``` env
PRODUCT_SOURCE=torob_mcp
```

The source abstraction exists so the application can switch between the
local canonical dataset and the Torob MCP source without changing
project/search business logic.

The source does not own:

-   intent interpretation;
-   requirement generation;
-   ranking;
-   project reasoning;
-   optimization.

Those remain application responsibilities.

------------------------------------------------------------------------

# 11. Requirement → subcategory matching

Requirement-to-catalogue resolution is deterministic.

The requirement provides semantic terms.

The catalogue provides vocabulary.

The matcher resolves the terms into subcategory slugs.

Loose substring matching is intentionally avoided.

For example, substring matching caused false positives such as:

``` text
مبل → مبلمان
```

and failed to capture useful lexical relationships such as:

``` text
میز تحریر ↔ میز کار
```

The current matcher works word-by-word using catalogue-derived
vocabulary and document-frequency thresholds.

A vocabulary term is useful evidence only when it is sufficiently
specific to a subcategory.

------------------------------------------------------------------------

# 12. Room scope is not product evidence

This is an important architectural invariant.

Room information and product evidence are separate signals.

``` text
room
  ↓
RoomScope
  ↓
eligible products

requirement terms
  ↓
subcategory matcher
  ↓
product evidence
```

Room words are therefore removed from product-term scoring.

This fixes a real regression caused by:

``` text
آینه سرویس بهداشتی
```

being the only bathroom subcategory label that explicitly contained the
room wording.

Without this separation, common room words such as:

``` text
سرویس
بهداشتی
```

could become high-value evidence for `bathroom-mirror` and cause
unrelated requirements such as plumbing or lighting to resolve to
mirrors.

A requirement containing only room words therefore produces no product
evidence.

This is not a query-specific exception; it is a general property of the
matcher.

------------------------------------------------------------------------

# 13. Candidate generation

After requirements are resolved to catalogue subcategories, candidate
generation is deterministic.

The backend applies hard constraints such as:

-   room eligibility;
-   product role;
-   project type;
-   space fit;
-   budget;
-   actual catalogue membership;
-   product availability;
-   supported quality constraints.

The candidate set is deliberately bounded before any LLM reasoning call.

The model never receives the entire catalogue as its search space.

------------------------------------------------------------------------

# 14. Product search constraints

Structured constraints take precedence over generic textual relevance.

For example:

``` text
دنبال یه ماشین لباسشویی تا ۳۰ تومن میگردم
```

must not return a washing machine above the 30,000,000 Toman ceiling
simply because a generic query token matched it.

The deterministic layer is responsible for:

``` text
category
subcategory
budget
availability
catalogue membership
```

The LLM is not trusted to enforce these.

------------------------------------------------------------------------

# 15. Candidate ranking

Candidate generation and reasoning are separate.

The deterministic layer establishes what is eligible.

If there is a single valid candidate, there is no need to ask a model to
make an artificial choice.

If multiple valid candidates remain, the reasoning layer can make a
bounded selection.

This produces:

``` text
hard filtering
     ↓
small candidate set
     ↓
optional reasoning
```

instead of:

``` text
full catalogue
     ↓
LLM
     ↓
hope the model picked a valid product
```

------------------------------------------------------------------------

# 16. Complementary products

Complementary relationships are derived from catalogue metadata.

They are not invented by the LLM.

The catalogue distinguishes:

``` text
alternative
≠
complement
```

Alternatives belong to the same product context/subcategory.

Complements come from explicitly declared complementary subcategories.

Complement candidates are still subject to room/project filtering.

The current complement generation can produce multiple candidate groups
when one requirement maps to multiple subcategory slugs. This is a known
optimization area and is intentionally separate from the core matching
fix.

------------------------------------------------------------------------

# 17. Project reasoning

Reasoning is performed only after candidate generation.

``` text
project
+
requirements
+
constraints
+
bounded candidates
        ↓
reasoning LLM
        ↓
structured proposal
        ↓
backend validation
        ↓
final result
```

The reasoning model can:

-   choose between valid candidates;
-   compare trade-offs;
-   explain a choice;
-   propose a replacement under changed constraints.

It cannot:

-   invent a product;
-   invent a seller;
-   invent a price;
-   create an arbitrary product ID;
-   expand the candidate set;
-   bypass hard constraints.

Every proposed product is revalidated against the backend candidate set.

------------------------------------------------------------------------

# 18. New project analysis lifecycle

For a genuinely new project query:

``` text
query
  ↓
product-first route
  ↓
LLM interpretation
  ↓
requirements
  ↓
deterministic subcategory resolution
  ↓
deterministic candidate generation
  ↓
reasoning when a decision exists
  ↓
project analysis
```

The intended model-call budget is:

``` text
0 LLM
```

for a clearly recognized direct product query, and approximately:

``` text
1 interpretation
+
1 reasoning
```

for a new project that actually requires model-based selection.

The system must not accidentally interpret the same query twice through
separate endpoints.

------------------------------------------------------------------------

# 19. Project recalculation

Changing project constraints should reuse the existing interpretation.

Examples:

-   area changes;
-   quality changes;
-   budget changes;
-   project parameters change.

The lifecycle is:

``` text
existing interpretation
      ↓
deterministic recalculation
      ↓
new candidate set
      ↓
reasoning if needed
```

There is no reason to ask the LLM to reinterpret the same
natural-language query.

This reduces latency, token usage and semantic drift.

------------------------------------------------------------------------

# 20. Selection list

The selection list is not a checkout basket.

Its purpose is:

> the explicit set of products the user currently wants to compare,
> keep, or consider for the project.

Properties:

-   product-ID based;
-   idempotent;
-   no product quantity;
-   explicit add/remove;
-   package add/remove operates on actual current product IDs;
-   partial selection is supported;
-   unmet requirements cannot become selection items;
-   recommendations do not silently enter the list.

User-facing terminology is intentionally:

``` text
لیست انتخاب‌ها
افزودن به لیست انتخاب‌ها
حذف از لیست انتخاب‌ها
در لیست انتخاب‌ها
بهینه‌سازی انتخاب‌ها
```

------------------------------------------------------------------------

# 21. Optimization architecture

Optimization is not another interpretation step.

It operates on:

``` text
existing project
+
existing selection list
+
current constraints
```

The intended flow is:

``` text
selection/project state
      ↓
deterministic candidate generation
      ↓
bounded optimization reasoning
      ↓
proposal
      ↓
user confirmation
      ↓
selection state update
```

The optimization operation must not call the interpretation endpoint
again.

This avoids a previously observed failure where optimization sent the
original query through interpretation, creating an unnecessary second
LLM call and exposing the system to a second interpretation failure.

------------------------------------------------------------------------

# 22. No silent optimization mutation

Optimization can produce a proposal such as:

``` text
current product
→ proposed replacement
→ saving
→ quality trade-off
```

The proposal is not an automatic mutation.

The user must explicitly accept the replacement.

This keeps the selection list authoritative with respect to user intent.

------------------------------------------------------------------------

# 23. Product detail semantics

Product detail exposes information that belongs to the product itself:

-   identity;
-   category/subcategory;
-   visual information;
-   structured attributes;
-   price;
-   seller offers;
-   similar products.

Similar products remain useful as alternatives.

The product detail page does not need a dedicated "complementary
products" section.

Complementary metadata remains available internally for project
reasoning and optimization.

------------------------------------------------------------------------

# 24. Pricing and money

The backend is the authority for monetary values.

Money is represented as integer Toman values.

The LLM never generates authoritative totals.

The frontend never becomes the source of truth for project totals or
optimization calculations.

A selection-list total can be displayed as an estimate of the selected
catalogue products, but it is not a checkout amount.

------------------------------------------------------------------------

# 25. LLM provider architecture

The LLM integration is centralized behind a single client contract.

Conceptually:

``` python
chat_json(system, user, schema_model)
```

The client handles:

-   OpenAI-compatible APIs;
-   structured JSON response format;
-   Pydantic validation;
-   timeouts;
-   truncation detection;
-   structured errors;
-   bounded retry behavior.

There is no hidden chain of fallback models.

The configured model is the model used for the request.

This is important because different models behave differently with:

-   structured JSON;
-   reasoning tokens;
-   response length;
-   prompt size;
-   instruction adherence.

Changing the model is therefore an explicit runtime decision.

------------------------------------------------------------------------

# 26. Truncation handling

A model response ending with:

``` text
finish_reason = length
```

is treated as a failed/truncated response.

The application must not try to guess the missing JSON structure.

A limited retry may be performed according to the LLM client
configuration.

The system should not solve repeated truncation simply by increasing the
token budget indefinitely.

Prompt size, model choice, reasoning behavior and candidate-set size are
all architectural factors.

------------------------------------------------------------------------

# 27. Frontend request lifecycle

The frontend has a dedicated API layer.

Search UI state follows actual backend request lifecycle.

The Thinking States component is presentational:

``` text
states
activeIndex
visible
```

It does not own:

-   requests;
-   timers for fake progress;
-   backend polling;
-   semantic interpretation.

The parent flow maps actual requests to visual states.

If an LLM request takes 30 seconds, the relevant state remains active
for the duration of the real request.

There is no simulated sequence that advances because a timer expired.

------------------------------------------------------------------------

# 28. Frontend state management

Pinia is used only for genuinely shared state.

Current shared state includes:

``` text
search
catalogue/cache
selection list
```

Component-local state remains local.

The API layer is the only frontend layer responsible for HTTP
communication.

------------------------------------------------------------------------

# 29. Design system and RTL

The application is Persian-first and RTL.

Core decisions:

-   Material Design 2 as the design reference;
-   centralized theme tokens;
-   Vazirmatn-first Persian typography;
-   logical CSS properties;
-   Persian digits for visible numbers;
-   Toman formatting;
-   accessibility-aware focus states;
-   reduced-motion behavior for animation.

The UI should not introduce arbitrary colors, radii, shadows or motion
durations when a token exists.

------------------------------------------------------------------------

# 30. Data pipeline

The canonical dataset is produced through a controlled pipeline:

``` text
raw catalogue data
      ↓
normalization
      ↓
manual selection
      ↓
canonical enrichment
      ↓
seller/offer attachment
      ↓
products_70_enriched.json
```

The raw source is not modified.

The enriched catalogue is committed and reviewable.

This matters because catalogue vocabulary affects deterministic
matching.

Changing:

``` text
label
search_terms
subcategory
room
complementary_subcategories
```

can change application behavior.

Therefore catalogue changes are semantic changes and should be reviewed
as such.

------------------------------------------------------------------------

# 31. Current catalogue scope

The current canonical dataset contains:

``` text
70 products
4 top-level domains
22 subcategories
```

Domains:

``` text
bathroom
kitchen
furniture
appliances
```

The current selected product groups include:

### Bathroom

-   toilet faucets
-   sink faucets
-   sinks
-   toilets
-   bathroom mirrors

### Kitchen

-   kitchen sinks
-   kitchen faucets
-   hoods
-   cooktops
-   built-in ovens

### Furniture

-   beds
-   desks
-   dining chairs
-   dining tables
-   sofas
-   wardrobes

### Appliances

-   refrigerators
-   washing machines
-   dishwashers
-   televisions
-   vacuum cleaners
-   microwaves

------------------------------------------------------------------------

# 32. Database responsibility

PostgreSQL stores application-owned state.

The catalogue is not required to be the primary relational product
database for this prototype.

This separation gives the catalogue these properties:

-   versioned;
-   diffable;
-   reproducible;
-   inspectable;
-   replaceable.

Database state is appropriate for:

-   projects/analyses;
-   selection lists;
-   selection items;
-   other application-owned persistent state.

The catalogue remains outside ordinary application mutation paths.

------------------------------------------------------------------------

# 33. Backend structure

The backend is organized as:

``` text
backend/app/
├── core/
├── db/
├── catalog/
├── llm/
├── seed/
└── domains/
    ├── catalog/
    ├── sellers/
    ├── search/
    ├── projects/
    └── basket/
```

### `app/catalog`

Catalogue/data layer:

-   source abstraction;
-   product indexing;
-   vocabulary matching;
-   room scope;
-   candidate selection;
-   catalogue projections;
-   complementary relationships.

### `domains/search`

Responsible for:

-   routing;
-   interpretation;
-   interpretation schema;
-   search-specific HTTP APIs.

### `domains/projects`

Responsible for:

-   project analysis;
-   requirement handling;
-   quantity semantics;
-   deterministic candidate generation;
-   bounded reasoning;
-   project recalculation.

### `domains/basket`

Responsible for:

-   selection-list state;
-   item add/remove;
-   optimization orchestration;
-   selection synchronization.

------------------------------------------------------------------------

# 34. Testing strategy

Tests protect architectural properties rather than only today's output
examples.

Important invariants include:

### Routing

A clear product query must not invoke interpretation.

### Interpretation

Structured output must satisfy the strict schema.

### Requirements

Different semantic project requirements must not collapse into the same
hardcoded list.

### Matching

Room words must not act as product evidence.

### Constraints

Budget must be enforced deterministically.

### Candidate safety

The reasoning model cannot introduce a product outside its candidate
set.

### Optimization

Optimization must not re-interpret the original query.

### Selection

Adding a product twice must remain idempotent.

### Quantity

Product-level quantity must remain absent while requirement quantity
remains valid.

### Frontend

Actual request lifecycle, rather than timers, drives Thinking States.

The test suite should therefore assert properties and boundaries rather
than encode a giant list of query-specific mappings.

------------------------------------------------------------------------

# 35. Known implementation issues / follow-up areas

These are separate from the core architecture.

## Complement candidate multiplication

If a requirement resolves to multiple subcategory slugs, complement
generation may consider complements for each slug.

This can enlarge the reasoning prompt.

This is a candidate-generation optimization area, not a reason to
reintroduce semantic guessing.

## Catalogue coverage

The current catalogue is intentionally small.

Some project requirements may remain unmet because no matching product
exists.

That is expected behavior.

## Product quality metadata

Quality metadata is not complete enough to support arbitrary quality
inference.

The system should not invent product quality.

## Large-scale search

The current in-process matcher is suitable for the prototype catalogue.

A larger catalogue can later move toward database-backed text search or
a dedicated search engine while preserving the same domain boundary.

## Model variability

Different LLMs can differ substantially in:

-   JSON adherence;
-   reasoning verbosity;
-   token consumption;
-   response latency.

Model changes should therefore be tested against representative
structured-output and project-reasoning cases.

------------------------------------------------------------------------

# 36. Configuration

Important runtime configuration includes:

``` env
DATABASE_URL=postgresql+psycopg://torob:torob@localhost:5432/torob_home

PRODUCT_SOURCE=local
TOROB_MCP_URL=https://torob-mcp.sajjadbayatani.workers.dev/mcp

LLM_API_KEY=
LLM_MODEL=
LLM_BASE_URL=
LLM_TEMPERATURE=0
LLM_REASONING_EFFORT=low
LLM_MAX_TOKENS=2000

CATALOG_PATH=../data/catalog/products_70_enriched.json

VITE_API_BASE_URL=http://localhost:8000/api/v1
```

The repository's `.env.example` is the authoritative configuration
reference.

------------------------------------------------------------------------

# 37. Development commands

## Docker

``` bash
cp .env.example .env
docker compose up --build
```

## Backend

``` bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

alembic upgrade head
python -m app.seed.run
uvicorn app.main:app --reload
```

## Frontend

``` bash
cd frontend
npm install
npm run dev
```

## Tests

``` bash
make test
```

or:

``` bash
cd backend && .venv/bin/python -m pytest -q
cd frontend && npm run test:run
cd frontend && npm run typecheck
```

------------------------------------------------------------------------

# 38. Implementation invariants

The following statements should remain true as the project evolves:

1.  A clear product query can complete without an LLM.
2.  Interpretation produces structure, not catalogue truth.
3.  The catalogue is the authority for products, sellers, offers and
    prices.
4.  Requirements are semantic needs, not product records.
5.  Room scope and product evidence are separate signals.
6.  Room words must not influence product-term scoring.
7.  Hard constraints are deterministic.
8.  Candidate generation happens before reasoning.
9.  The reasoning model receives a bounded candidate set.
10. The reasoning model cannot introduce arbitrary products.
11. A missing product remains an unmet requirement.
12. A project is not re-interpreted merely because its constraints
    changed.
13. Optimization does not invoke interpretation.
14. Optimization does not silently mutate the selection list.
15. Product quantity is not part of the current selection model.
16. Requirement quantity remains part of project semantics.
17. Recommendations do not automatically enter the selection list.
18. No query-specific hardcoded phrase map is introduced to compensate
    for matcher failures.
19. No second semantic model is introduced merely to compensate for the
    first model.
20. Token-budget problems are investigated at the
    model/prompt/candidate-set level rather than solved by unlimited
    token increases.
21. Tests protect these architectural boundaries.
22. Changes to catalogue vocabulary are treated as behavioral changes.

------------------------------------------------------------------------

# 39. Final architecture

The implementation should be understood as this pipeline:

``` text
                    USER QUERY
                        │
                        ▼
             ┌─────────────────────┐
             │ Product-first route │
             └──────────┬──────────┘
                        │
             ┌──────────┴──────────┐
             │                     │
       clear product          not clearly product
             │                     │
             ▼                     ▼
      Product Search         LLM Interpretation
       0 LLM calls                  │
                                   ▼
                            Project / Product
                                   │
                                   ▼
                         Project Requirements
                                   │
                                   ▼
                    Deterministic Catalogue Match
                                   │
                                   ▼
                       Hard Candidate Filtering
                                   │
                                   ▼
                         Bounded Candidate Set
                                   │
                         ┌─────────┴─────────┐
                         │                   │
                  no real choice       real choice
                         │                   │
                         ▼                   ▼
                   deterministic      Reasoning LLM
                      result                │
                                           ▼
                                   backend validation
                                           │
                                           ▼
                                  Project / Selection
                                           │
                                           ▼
                                  User confirmation
```

The central architectural rule is:

> **The model understands intent and helps make bounded choices. The
> backend and catalogue remain responsible for what is actually
> possible.**

That boundary is the foundation for the current MVP and should be
preserved as the system grows.
