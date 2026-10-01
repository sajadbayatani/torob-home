# UI Design Guidelines (Persian RTL)

How design decisions are made in this repository, and how the **VibeFarsi** MCP
server is used as a reference source.

Scope note: this document is about the frontend (`frontend/`). It is written in
English on purpose — all project documentation is English, while user-facing UI
copy stays Persian.

---

## 1. Stack (non-negotiable)

| Concern | Choice |
|---|---|
| Framework | **Vue 3** with `<script setup>` + Composition API |
| Language | **TypeScript** (strict) |
| Build | **Vite** |
| Routing / state | Vue Router, Pinia (only for genuinely shared state) |
| Styling | **Tailwind CSS** (v3, this repo) |
| Font | Vazirmatn, bundled via `@fontsource/vazirmatn` |

**React is never introduced.** No React components, no `react` / `react-dom`
dependency, no JSX, no React-flavoured component library. This holds even when a
reference source only ships React code.

---

## 2. VibeFarsi MCP server

Configured in `opencode.json` at the repository root:

```json
{
  "mcp": {
    "vibefarsi": {
      "type": "remote",
      "url": "https://vibefarsi.ir/mcp",
      "enabled": true,
      "timeout": 30000
    }
  }
}
```

Restart opencode after changing `opencode.json` — configuration is loaded once at
startup.

Available tools (5):

| Tool | Required args | Use it for |
|---|---|---|
| `get_design_rules` | — | The baseline rules below; call before generating any Persian UI |
| `scaffold_page` | `goal` | Turning a page brief into a composition plan (layout + Persian copy) |
| `get_theme` | — | Design tokens (CSS variables) for a named theme — **reference, not a copy** |
| `search_registry` | `query` | Finding relevant components, blocks, patterns |
| `get_component` | `names` | Inspecting a component's source/prompt to understand its structure |

### How to use it

VibeFarsi is a **Persian RTL React + Tailwind registry**. This project is Vue, so
the tool is used as a *design and pattern reference*:

1. Call `get_design_rules` **before** writing or reviewing UI code.
2. Use `scaffold_page` for whole-page layout decisions.
3. Use `search_registry` / `get_component` to study a pattern's structure,
   spacing, hierarchy and Persian copy.
4. Use `get_theme` to sanity-check colour roles and token naming.
5. **Re-implement in Vue 3.** Take the design intent — not the code.

When reproducing a component in Vue:

- copy the *design decisions*: spacing scale, type ramp, colour roles, states,
  Persian copy, RTL behaviour, accessibility affordances;
- write `<script setup lang="ts">` + a template that follows this repo's existing
  component conventions (`frontend/src/components/**`);
- map the design system onto the tokens already defined in
  `frontend/tailwind.config.js` (or add to them deliberately) rather than
  introducing a second token set;
- reuse the helpers in `frontend/src/utils/format.ts` (`toPersianDigits`,
  `formatToman`, …) instead of the registry's React `lib/utils.ts`;
- never add an npm UI-kit dependency to consume the design.

---

## 3. Design rules that apply to this project

Distilled from VibeFarsi's `get_design_rules` and already reflected in this repo.

### Direction

- `<html lang="fa" dir="rtl">` is set in `frontend/index.html`. RTL is the base
  case, not a patch applied to an LTR layout.
- Logical CSS only: `ms-*` / `me-*` / `ps-*` / `pe-*` / `text-start` / `text-end` /
  `border-s` / `inset-s-0`. Do not introduce `ml-`, `pl-`, `pr-`, `text-left`,
  `text-right` or `left-0` unless the value is inherently LTR.
- Normal document order; RTL flips it. Never add `row-reverse` to "fix" direction.
- Directional icons must flip: forward/next chevrons point **left**.
- Inherently LTR controls (phone, email, OTP, IBAN/Sheba, card number, URL) keep
  `dir="ltr"` **on the control itself**, not on the surrounding form. The repo's
  `.num` utility does this for numeric runs.

### Typography

- Vazirmatn is the Persian sans; never Inter, Roboto or Geist alone.
- `letter-spacing: 0` on Persian text — tracking breaks glyph joining.
- Body ≈ 16.5px with `line-height: 1.7` (`--leading-body`, MD2's 1.5 opened up for
  Persian); headings use `--leading-headline: 1.35` and never go below 1.15.
- Headings are weight 600, buttons 500, body 400 — the MD2 type roles
  (`--type-headline-weight`, `--type-button-weight`, `--type-body-weight`).
- Buttons are never `uppercase` and never tracked out: Persian is a cursive
  script, so letter-spacing destroys glyph joining.
- Use real font weights, never faux bold/italic.
- Mixed strings (Persian + a Latin run such as `SKU-2048`): isolate the Latin run
  rather than flipping the whole paragraph to LTR.
- Truncate with CSS `line-clamp`, never a naive character slice (it breaks
  letter joining).

### Numbers, money, dates

- Visible digits are Persian: `۰۱۲۳۴۵۶۷۸۹`. `toPersianDigits()` handles conversion.
- Thousands separator is `٬` (U+066C), decimal is `٫`, percent is `٪` after the
  number.
- Money renders as `formatToman(n)` → `۱۲٬۴۵۰٬۰۰۰ تومان`, unit **after** the
  number. Never `Toman`/`$` labels.
- تومان is the default unit. If a conversion is unavoidable, ریال = تومان × ۱۰, and
  the two are never silently mixed.
- Form values, URLs and JSON payloads stay Latin digits; the display layer
  converts.
- Dates are Jalali (شمسی) and the week starts on Saturday (شنبه).

### Forms

- Labels sit above the field with `htmlFor`; a placeholder is not a label.
- Phone inputs: `dir="ltr"` + `inputMode="tel"`, optional `+98` start addon.
- Persian error and helper text sit under the field; destructive actions are
  visually distinct, not just coloured.

### Spacing, shape and colour

- The layout grid is the **Material 8dp grid**: `--spacing` (8dp),
  `--spacing-half` (4dp), `--spacing-quarter` (2dp). Stay on the multiples; no
  one-off pixel values and no arbitrary values such as `p-[13px]` in components.
- **Shape comes from the theme, not from Tailwind's radius scale**:
  `--shape-control` / `--shape-field` (2dp) for buttons, chips, text fields and
  icon buttons; `--shape-surface` / `--shape-overlay` (4dp) for cards, headers,
  alerts, dialogs and menus; `--shape-sheet` (16dp) for bottom sheets;
  `--shape-full` only for genuinely circular things (avatars, FAB, status dots).
  Pill-shaped buttons are not Material — do not reintroduce them.
- **Depth comes from the theme**, using the MD2 levels `d1, d2, d3, d4, d6, d8,
  d16, d24` (exposed as `shadow-d1 … shadow-d24`): `--depth-control` (2dp) for raised buttons,
  `--depth-press` (8dp) when pressed, `--depth-surface` (2dp) for cards,
  `--depth-overlay` (8dp) for menus, sheets and the hero panels, `--depth-dialog`
  (24dp) for dialogs, `--depth-appbar` (4dp) for the top app bar and
  `--depth-fab` (6dp) for a FAB. Do not add a Tailwind `shadow-*` on top.
  **Cards and app bars are not outlined**: a 1px border *plus* elevation is not
  Material — use elevation alone, or a filled container (`bg-muted`) for
  secondary grouping.
- **Component metrics are fixed**: raised button 36dp (`--size-button`), chip 32dp
  (`--size-chip`), text field 48dp (`--size-field`), app bar 56dp
  (`--size-appbar`), FAB 56dp (`--size-fab`). Every interactive element keeps a
  48dp minimum touch target (`--control-size`), including icon-only buttons and
  quantity inputs — `.btn` grows the hit area with an `::after` so the visual
  button can stay 36dp.
- **Interaction feedback is a state layer**, not a transform: hover 8%, focus
  24%, pressed 10%, dragged 16% (`--state-hover|focus|pressed|dragged`) over the
  component's own colour, animated in 225ms on
  `cubic-bezier(0.4, 0, 0.2, 1)`. Spring scale-downs are not Material.
- **Text fields are filled**, not outlined: `bg-field` with a 2dp bottom line
  (`--input`) that turns `primary` on focus. There is no resting shadow.
- **Colour comes from the semantic tokens** defined in
  `frontend/src/theme/material.css` and mapped in `tailwind.config.js`:
  `background`, `foreground`, `card`, `primary`, `secondary`, `muted`, `accent`,
  `destructive`, `success`, `warning`, `border`, `ring`, `brand`. Never hard-code a
  colour in a component, and never introduce a new palette step. The brand palette
  is exactly three colours — Charcoal Blue `#424B54` (text and neutral base),
  White `#FFFDFD` (surfaces), Dark Amaranth `#990D35` (primary, money, identity) —
  and every neutral token is a tint or alpha of them. No additional brand colours
  may be introduced. `--destructive`, `--success` and `--warning` are semantic
  state colours, not brand colours: they are reserved for their state and never
  used for identity or decoration.
- Money and other commercial emphasis use `primary`; the project identity accent is
  `brand`. Muted text is for metadata only; body copy uses `foreground`.
- Every interactive element needs hover, focus-visible and disabled states. Focus
  rings are defined once in `style.css` and must not be removed.

### Loading and async states

- Loading is a `Skeleton` shaped like the final content, never a centred spinner.
  Async blocks reserve their height so nothing shifts.
- Empty states use `EmptyState`: say what is missing, then offer the one action
  that fixes it.
- Errors use `AlertBox` with `role="alert"`, and must name the failure and the
  next step. Never «مشکلی پیش آمد» on its own.

### Motion and a11y

- Motion is functional, not decorative, and it is token-driven: `--motion`
  (420ms), `--motion-ease` (spring) and `--press` (scale 0.95) on interactive
  components. Do not invent durations.
- Respect `prefers-reduced-motion`: the global rule in `style.css` disables the
  skeleton pulse, the spring transitions and the press scale.
- Interactive targets are comfortably tappable, form controls are labelled, and
  decorative icons are `aria-hidden`.

---

## 4. Product-specific rules

- Calm, trustworthy, information-dense but not cluttered. No gradients, no
  glassmorphism, no dashboard chrome on consumer pages.
- No fake statistics, fake reviews or fake social proof. All catalogue data is
  clearly marked as demo data.
- AI/recommendation output always carries a short explanation of *why*; never ship
  a result without its reason, and never use vague "AI magic" wording.
- Money always comes from the API. The browser never computes a total.
- Prefer contextual wording over generic labels: say "you may also need this to
  install it", not "similar products".


---

## 5. Audit and migration history

- [`UI_AUDIT.md`](UI_AUDIT.md) — the code reviewed against these rules with the
  VibeFarsi MCP server, and what it changed.
- [`THEME_MIGRATION.md`](THEME_MIGRATION.md) — the migration from the original
  palette to a token-driven theme.
- [`PALETTE_MIGRATION.md`](PALETTE_MIGRATION.md) — the colour-only migration to
  Charcoal Blue / Raspberry, with the design language held constant (historical).
- [`MATERIAL_MIGRATION.md`](MATERIAL_MIGRATION.md) — the current design system:
  Material Design 2, and the Persian adaptations made on top of it.

Re-run the review after large UI changes; the rules above are the checklist.
