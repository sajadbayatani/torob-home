# Token Architecture Migration (historical palette)

The migration of the UI from the original `sand` / `pine` / `clay` / `ink` / `line`
design system to a **token-driven theme**. At the time this was written the palette
was Pomegranate (انار).

> **Historical.** The palette has since changed to Charcoal Blue / Raspberry (see
> [`PALETTE_MIGRATION.md`](PALETTE_MIGRATION.md)) and the component language is now
> **Material Design 2** (see [`MATERIAL_MIGRATION.md`](MATERIAL_MIGRATION.md)). What this document still
> describes accurately, and what the app relies on today, is the **token
> architecture**: one canonical theme file, a Tailwind config that maps semantic
> utilities to CSS variables, and components that hard-code no colour, radius,
> shadow or duration. The colour values quoted below are no longer current.

Reference: VibeFarsi `get_theme --name pomegranate` (claymorphism). VibeFarsi ships
React + Tailwind v4 source; nothing was copied. Every pattern was re-implemented in
Vue 3 with `<script setup lang="ts">`. React is not a dependency of this project.

---

## 1. What was there before

| Group | Tokens | Usage |
|---|---|---|
| Warm paper neutrals | `sand-50/100/200/300` | page background, tinted boxes, skeletons |
| Teal | `pine-50…700` | primary buttons, focus rings, "cheapest price" highlights, in-stock states, selected filters |
| Amber | `clay-50/200/600/700` | money accent, over-budget, errors |
| Text | `ink`, `ink-soft`, `ink-muted` | foreground, secondary, meta |
| Borders | `line` | all dividers and card outlines |
| Shape | Tailwind `rounded-lg/xl/2xl` + `shadow-card` / `shadow-pop` | cards, fields, chips |

Total surface: 17 `.vue` files and `style.css` depended on those tokens.

## 2. The new token layer

`frontend/src/theme/pomegranate.css` is the single source of truth and defines every
token on `[data-theme="pomegranate"]`: colour, shape, depth, motion, line weights and
type. It is applied by the document root:

```html
<html lang="fa" dir="rtl" data-theme="pomegranate">
```

Derived tokens added for this codebase (everything else is verbatim from the
brief): `--leading-body`, `--leading-display`, `--leading-control` and
`--control-size`, which keep the Persian typographic rules from `UI_DESIGN_GUIDELINES.md`
readable instead of hard-coded.

### Tailwind mapping

`tailwind.config.js` no longer defines colours at all. It maps Tailwind utilities to
the CSS variables:

- **Colour** — `background`, `foreground`, `card`, `popover`, `primary`, `secondary`,
  `muted`, `accent`, `destructive`, `success`, `warning`, `border`, `field`, `input`,
  `ring`, `brand`, each with a `-foreground` companion where the theme defines one.
- **Shape** — `rounded-control` (999px), `rounded-field` (1rem),
  `rounded-surface` (1.75rem), `rounded-overlay` (1.5rem).
- **Depth** — `shadow-control`, `shadow-press`, `shadow-field`, `shadow-surface`,
  `shadow-overlay`.
- **Motion** — `duration-motion`, `ease-motion`, `scale-press`.
- **Type** — `font-body`, `font-display` from `--type-body` / `--type-display`.
- **Density** — `spacing` (`--spacing`), available as `p-density`, `gap-density`, …

The old `sand` / `pine` / `clay` / `ink` / `line` scale was **deleted**, not renamed.

### Component layer

`style.css` now expresses the design language rather than a palette:

| Class | Language |
|---|---|
| `.card` | `rounded-surface`, 1px `--border`, `--depth-surface` |
| `.btn` | pill (`--shape-control`), `--depth-control`, `--motion`/`--motion-ease`, press = `--depth-press` + `scale(0.95)` |
| `.btn-primary` / `-secondary` / `-ghost` / `-destructive` | `--primary` / `--secondary` / transparent / `--destructive` |
| `.field` | `--shape-field`, `--depth-field` (recessed), `--input` border |
| `.chip` | pill on `--muted` |
| `.label` | meta text; still no `uppercase` and no tracking (Persian joining) |

Preflight's default greys for borders and placeholders are overridden with
`--border` / `--muted-foreground`, so nothing outside the token set reaches the
screen.

---

## 3. Mapping applied across the UI

| Old | New | Rationale |
|---|---|---|
| `bg-sand-50` | `bg-background` | page surface |
| `bg-sand-100/200` | `bg-muted` | tinted boxes, skeletons |
| `text-ink` | `text-foreground` | body |
| `text-ink-soft`, `text-ink-muted` | `text-muted-foreground` | meta (muted is for metadata only) |
| `border-line` | `border-border` | dividers |
| `bg-pine-50/100/200` | `bg-accent` | highlighted surfaces |
| `text-pine-500…800` | `text-primary` | commercial emphasis, cheapest price, selected state |
| `ring-pine-500` | `ring-ring` | focus |
| `text-clay-600/700` | `text-warning` | over budget, commercial warnings |
| `bg-clay-50`, `border-clay-200` | `bg-accent` / `border-border` | tinted containers |
| `shadow-card` / `shadow-pop` | `shadow-surface` / `shadow-overlay` | elevation |
| `rounded-2xl` | `rounded-surface` | cards |
| `rounded-xl` / `rounded-lg` (boxes) | `rounded-field` | fields, message boxes, tiles |
| `rounded-xl` / `rounded-lg` (chips, icon buttons, skeletons) | `rounded-control` | pills |
| `rounded-full` (circles) | unchanged | a circle is intentional |
| `bg-white` | `bg-card` | surfaces |

Semantic components were rewritten rather than remapped, so tones are meaningful:

- `AlertBox` — `error → destructive`, `warn → warning`, `success → success`,
  `info → accent`, each with a tinted background and a 25% border.
- `ExplanationPanel` — `neutral / info / warn / brand`.
- `AvailabilityBadge` — `in_stock → success`, `low_stock`/`preorder → warning`,
  `out_of_stock → muted`.
- `PriceTag` — money is `--primary`; `tone="primary"` replaced the old accent tone.

---

## 4. Product-level changes

These are visual hierarchy changes required by the migration brief; no logic moved.

### Home (`views/HomeView.vue`)

The two starting points are now explicit and non-technical, so the Product Search /
Need Search distinction is legible before the user types: two cards —
«دنبال یک محصول مشخصم» and «می‌خواهم یک کار را انجام دهد» — each with a plain
explanation and a working example that routes through the same `onSubmit` intent
routing as before. The hero uses `--type-display` weight 800.

### Product search (`views/SearchView.vue`)

- Result grid unchanged; price remains the card's visual anchor.
- The intent chip and the "this is a need" panel are now brand/primary tinted and
  use `--shape-overlay` with `--depth-overlay`, so a need query looks different from a
  product result list at a glance.
- Quality filters are pills with `aria-pressed`; the selected one is primary.

### Smart Basket (`views/BasketView.vue`)

Rebuilt as a **manifest**, not a cart. The header is a `--shape-overlay` /
`--depth-overlay` surface with a `--brand` band that states what the basket is for,
then the line count, target budget, savings chip and the server-computed total.
Each line now shows **unit price alongside line total** (previously only the line
total was visible), the seller, availability, quantity, reason, lock state and a
"cheapest price elsewhere" warning. The budget control is the amount input, which
spells the understood amount in Persian words.

### Project search (`views/ProjectView.vue`)

Rendered as a **project brief** that cannot be mistaken for a product list: a
brand-tinted band with the project title, domain/type/area/quality chips and the
estimate as the hero; then «الزامات پروژه و لیست پیشنهادی خرید» with the rule
origin stated; then the constraint controls, the line items, the optimisation result
and the explanations.

---

## 5. RTL and responsive audit

| Check | Result |
|---|---|
| Physical direction classes (`ml-`, `pl-`, `left-0`, `text-left`, …) | none remain |
| `row-reverse` / `flex-direction` hacks | none |
| Directional icons | the only inline SVG is the search magnifier, which is not directional |
| Numeric values, prices, tables | Persian digits via `utils/format`; tables use `text-start` |
| Fixed widths that could overflow at 360px | none; both tables have stacked variants below `md` |
| Hard-coded colours outside the theme | none (preflight greys overridden with tokens) |
| Root element | `lang="fa" dir="rtl" data-theme="pomegranate"` |

`prefers-reduced-motion` still disables the skeleton pulse, the spring transitions and
the press scale.

---

## 6. Verification

| Check | Result |
|---|---|
| `vue-tsc --noEmit` | clean |
| `vitest` | 53 passed (8 files), including a new `tests/theme.spec.ts` |
| Production build | ok — 165 kB JS, 33 kB CSS |
| Served HTML | `<html lang="fa" dir="rtl" data-theme="pomegranate">` |
| Shipped CSS | contains every required token; colour literals are only the Pomegranate `oklch` set |
| Live run, all five routes | home, search, product, project, basket verified against the running API |
| Backend `pytest` | 77 passed, unchanged |

`tests/theme.spec.ts` locks the migration in: it fails if the old palette reappears, if
a component hard-codes a colour, if a physical direction utility returns, or if the
theme stops being applied to the document.

### Not verifiable here

jsdom has no layout engine, so mobile layout was verified **structurally** (stacked
variants present, no fixed pixel widths, breakpoints in place) rather than visually.
A real browser pass at 360–390 px is still worth doing.
