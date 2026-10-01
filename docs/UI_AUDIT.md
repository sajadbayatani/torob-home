# Persian RTL UI Audit (VibeFarsi review)

Date: post-MVP review of `frontend/`, using the **VibeFarsi MCP server** as the
design reference. This document records what was found, what changed, and what
was deliberately left alone.

> The design language has since moved to **Material Design 2** — see
> [`MATERIAL_MIGRATION.md`](MATERIAL_MIGRATION.md). Everything below is the state of
> the UI at the time of the review; the RTL, typography, number and spacing rules it
> established still hold and are restated in
> [`UI_DESIGN_GUIDELINES.md`](UI_DESIGN_GUIDELINES.md).

Source of truth for the rules: `get_design_rules`, plus the design intent of
`skeleton`, `empty-state`, `badge`, `amount-input`, `number-to-words`, `alert`,
`input` and `button` from the registry, plus the `ui-craft-rules` and
`persian-ui-copy` skills.

> VibeFarsi ships React + Tailwind v4 source. None of it was copied. This project
> is Vue 3 + Tailwind v3, so every pattern below was re-implemented natively in
> `<script setup lang="ts">` against this repo's own tokens. React is not a
> dependency.

---

## 1. What the audit found

Ordered by impact. "Fixed" rows were addressed in this pass.

| # | Area | Finding | Severity | Status |
|---|---|---|---|---|
| 1 | Typography | `body` had no explicit size/leading; the app rendered at the browser default (~16px/1.5) instead of the Persian baseline of ~16.5px with 1.8 leading | high | Fixed |
| 2 | Typography | `.label` used `uppercase tracking-wide`. `tracking` **breaks Persian glyph joining**, and it was applied to every section eyebrow and chip caption in the product | high | Fixed |
| 3 | Typography | `text-2xs` resolved to 11px and carried prices, seller names and captions | high | Fixed (now 12px floor) |
| 4 | Forms | `.field` was 14px, so Safari/iOS zoomed the page on focus | high | Fixed (`@supports` guard) |
| 5 | Numbers | Three different mechanisms formatted numbers (`toPersianDigits`, `new Intl.NumberFormat('fa-IR')`, `toLocaleString`), so separators and edge cases could drift | high | Fixed (one helper path) |
| 6 | Numbers | **Backend explanations rendered Latin digits** — e.g. `از 73,910,000 تومان`, `تعداد 39`, `با 3 تغییر` — because `format_toman()` used `f"{amount:,}"` | high | Fixed (`fa_number()` + regression test) |
| 7 | Search UX | Submitting the search on `Enter` also fired **during IME composition**, which breaks Persian syllable entry — the single worst defect for a Persian search box | high | Fixed (`compositionstart`/`compositionend` guard) |
| 8 | Loading | All async states were a centred line of text («در حال جستجو…»). No skeletons, so every view jumped when data arrived | high | Fixed (skeletons shaped like the final layout) |
| 9 | Empty states | A bare bordered box with one sentence; the search empty state offered no next action | medium | Fixed (`EmptyState` with a real action) |
| 10 | Responsive | `OfferComparison` and `ProjectView` tables used fixed `min-w-[520px]` / `min-w-[640px]`, forcing horizontal scrolling on 360–390px phones | high | Fixed (stacked layout below `md`) |
| 11 | RTL | Physical classes in use: `mr-auto` (header nav), `text-left` (action columns, basket totals), `text-right` (tables) | medium | Fixed (logical `ms-auto`, `text-start`, `text-end`) |
| 12 | Forms | Labels were not associated with controls (`htmlFor`), the budget fields had no validation feedback, no `aria-invalid`, and no helper text | medium | Fixed |
| 13 | Price UX | The budget field was a free-text box that parsed silently — a user typing «۵۵ میلیون» got no confirmation of what the system understood | high | Fixed (amount in words under the field) |
| 14 | Hierarchy | On the project page the estimate sat in a footer strip *below* a long table, competing with the checklist | medium | Fixed (estimate is now the hero of the header) |
| 15 | Hierarchy | On the search page the "recommended basket" block sat **above** the results, pushing them below the fold | medium | Fixed (results first) |
| 16 | Hierarchy | Product names were never clamped, so cards broke their rhythm on long names | low | Fixed (`clamp-2`) |
| 17 | Comparison | The comparison table had no accessible name and the price spread had no "what you save" framing | low | Fixed (`<caption>`, saving line) |
| 18 | Copy | Error copy was developer-facing («آیا بک‌اند در حال اجراست؟») and a generic fallback («درخواست با خطا مواجه شد») | medium | Fixed (say what failed + what to do next) |
| 19 | Copy | «جستجو» used throughout instead of the correct «جست‌وجو»; search was sometimes written as «جست‌وجوی» where the glossary says «جست‌وجو» | low | Fixed |
| 20 | Motion | No `prefers-reduced-motion` handling | low | Fixed |

Deliberately **not** changed:

- **No icon library.** VibeFarsi mandates a single icon set (lucide). Adding one is a dependency decision outside the scope of a UI pass, and the two inline SVGs already in the app are consistent. The rule is recorded in the guidelines for later.
- **The colour palette.** The app has its own token set (`sand` / `pine` / `clay` / `ink` / `line`) with a documented rationale. VibeFarsi themes are a reference; swapping the product's visual identity was not part of this task.
- **The A11y/skeleton of `toLocaleDateString('fa-IR')`.** No dates are displayed yet, so Jalali support is noted, not built.
- **Product structure.** No screen was restructured into a generic ecommerce layout. The two core journeys are unchanged.

---

## 2. What changed, by layer

### Design tokens (`tailwind.config.js`, `style.css`)

- Persian type baseline: `body` at 16.5px / 1.8, headings at 1.2, controls at 1.5, exposed as `--leading-*` custom properties.
- `letter-spacing: 0` on body and headings; `.label` no longer uses `uppercase` or tracking.
- `text-2xs` raised from 11px to a 12px floor.
- iOS/Safari input-zoom guard, so controls reach ≥16px on those engines while desktop stays `text-sm`.
- `prefers-reduced-motion` honoured globally.
- `--control-size: 2.75rem` (44px) applied to `.btn`, `.field` and interactive chips, so touch targets meet the minimum.
- `.clamp-2` / `.clamp-3` helpers (Persian text must never be truncated by slicing).

### Number and money formatting (`utils/format.ts`)

One path for every visible number:

| Helper | Purpose |
|---|---|
| `faNumber(v)` | Persian digits, «٬» grouping |
| `formatToman(v)` | «۱۲٬۴۵۰٬۰۰۰ تومان» — unit after the number |
| `formatTomanShort(v)` | «۷۳٫۹ میلیون تومان» for headline figures |
| `parseToman(s)` | accepts `55000000`, «۵۵ میلیون» or a full sentence |
| `numberToWords(v)` | «یک میلیون و دویست و پنجاه هزار تومان» |
| `toLatinDigits(s)` | shared by parsing and grouping |

The same rule was applied to the **backend** (`app/core/text.py::fa_number` /
`format_toman`), because backend explanation strings are rendered verbatim by the
UI. A backend test now asserts that no user-facing string contains a Latin digit.

### New components (Vue 3)

| Component | Re-implemented pattern |
|---|---|
| `ui/Skeleton.vue` | `skeleton` — pulsing, `aria-hidden`, honours reduced motion, sized by the caller's class |
| `ui/EmptyState.vue` | `empty-state` — dashed border, icon, title, description, one action |
| `ui/AlertBox.vue` | `alert` — `role="alert"` for errors, `role="status"` otherwise, `aria-live`, optional retry |
| `basket/BudgetAmountInput.vue` | `amount-input` + `number-to-words` — grouped Persian digits, unit after the number, amount spelled out, `aria-invalid` and an error that says what to write |

### Reworked components

- **`search/SearchBar.vue`** — IME composition guard, clear action with a Persian `aria-label`, 44px targets, example chips at full touch size.
- **`product/OfferComparison.vue`** — stacked list on phones, real `<table>` with `<caption>` and `scope` from `md` up, logical alignment, and a "what the cheapest seller saves" line.
- **`product/ProductCard.vue`** — clamped name, one money path, "N more sellers" instead of a silent truncation.
- **`ui/PriceTag.vue`** — single money component, `bare` mode where the unit already appears in the sentence.

### Views

- **Search** — skeletons for the results grid, `EmptyState` with a next action, `AlertBox` with retry, quality filters as a `<fieldset>` with `aria-pressed`, results **before** the recommended-basket prompt.
- **Product** — skeletons, `AlertBox` retry, label/`for` on quantity, hero price, saving framing.
- **Project** — estimate promoted to the hero of the header, line items stacked on phones, constraint fields with labels and ids, budget via `BudgetAmountInput`, note that the estimate comes from rules rather than the model.
- **Basket** — skeletons, `EmptyState`, `BudgetAmountInput` with amount-in-words, saving spelled out in words.

### Copy (Persian, per the `persian-ui-copy` glossary)

- «جست‌وجو» instead of «جستجو».
- «در حال …» with an ellipsis for loading.
- Empty states say what is missing and what to do next; no «Oops»-style text.
- Errors name the failure and the next step, both in the API client and the views.
- «خرید» / «سبد خرید» / «افزودن به سبد» kept consistent per concept.
- ZWNJ applied where it belongs.

---

## 3. Verification

| Check | Result |
|---|---|
| Backend `pytest` | 77 passed |
| Backend `ruff` / `mypy` | clean |
| Frontend `vitest` | 46 passed (7 files) |
| Frontend `vue-tsc` | clean |
| Frontend production build | ok (~162 kB JS, ~30 kB CSS) |
| Live run against the running stack | product search, product page + add to basket, project analysis, budget optimisation, empty basket — all verified with the real API |
| Latin-digit sweep over API responses | 0 leaks |

A live end-to-end pass (real components against the running API) additionally
caught the backend Latin-digit bug in finding #6, which no unit test had covered.

---

## 4. Remaining opportunities (not done here)

- Adopt a single icon set instead of the two inline SVGs.
- Extract the repeated "explanation + cost" pattern into a shared component.
- Add Jalali date rendering when a real date surfaces (offer timestamps are ISO
  strings today and are deliberately not shown).
- Convert the `data-test` hooks to `data-testid` if a different runner is adopted.
- Add a visual regression pass at 360–390px once a browser runner is available.
