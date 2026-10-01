# Material Design 2 Migration

The migration of the UI from the Charcoal Blue / Raspberry claymorphism language to
**Material Design 2**. This is the current design system. Unlike the two earlier
migrations, this one changes the **component language**, not only the palette:
shape, elevation, metrics, interaction feedback, text fields and navigation all
change. Business logic, API contracts and routing are untouched.

Applied via `<html lang="fa" dir="rtl" data-theme="material">`.

---

## 1. What changed, and why it is Material

The previous language was a "claymorphism" variant: pill-shaped everything, very
soft large-radius shadows, outlined boxes, and spring scale-downs on press. MD2 is
the opposite on each of those points:

| Concern | Before | MD2 now |
|---|---|---|
| Corner radius | pill (`9999px`) on buttons, chips, fields | 2dp controls/fields, 4dp cards and overlays, 16dp sheets |
| Depth | three hand-tuned soft shadows | the d1–d24 elevation scale, bound per component |
| Cards and bars | 1px border **and** shadow | elevation alone, no outline |
| Press feedback | `scale(0.95)` spring | state layer, `--state-pressed` 10% |
| Focus | soft 3px ring | crisp 2dp outline |
| Text fields | outlined box with a border | **filled** field, 2dp bottom line only |
| Buttons | pill, 36–44dp | 36dp visual, 48dp touch target |
| Chips | pill, 36dp | 32dp, 2dp radius |
| Top bar | 64dp, hairline border | 56dp, `--elevation-4`, active item in `primary` |
| Spacing | 4px-based Tailwind scale | 8dp grid (with 4dp and 2dp) |
| Type | weight 800 display | MD2 roles: 600 headline, 500 button, 400 body |

---

## 2. The brand palette — three colours, no more

| Token | Value | Role |
|---|---|---|
| `--brand-charcoal` | `#424B54` | Charcoal Blue — text, icons, the neutral base |
| `--brand-white` | `#FFFDFD` | White — page and surface background |
| `--brand-amaranth` | `#990D35` | Dark Amaranth — primary action, money, identity |

Raspberry `#D52941` and the whole `sand` / `pine` / `clay` / `ink` / `line` scale
are **deleted**. Every neutral role is a tint or alpha of Charcoal Blue over White:

| Token | Value | Derivation |
|---|---|---|
| `--muted` | `#F4F2F3` | Charcoal Blue at 6% over White |
| `--secondary` | `#ECEBEC` | Charcoal Blue at 10% |
| `--accent` | `rgb(66 75 84 / 5%)` | Charcoal Blue at 5% |
| `--border` | `rgb(66 75 84 / 12%)` | MD2 divider opacity |
| `--input` | `rgb(66 75 84 / 42%)` | unfocused text-field line |
| `--muted-foreground` | `#6A747C` | 4.71:1 on `--background` — the accessible floor for meta text |

Three fixed **semantic state** colours remain, because distinguishable states are a
Material requirement and cannot be expressed as a tint of the brand:

| Token | Value | Used for |
|---|---|---|
| `--destructive` | `#B3261E` | validation and load errors |
| `--success` | `#1F7A5C` | in-stock, savings |
| `--warning` | `#8F6410` | over-budget, commercial warnings |

They are not brand colours: they never appear in identity, decoration or the app
bar, and they never replace `primary` for a money or action emphasis.

---

## 3. Elevation

`--elevation-1, -2, -3, -4, -6, -8, -16, -24` are the MD2 elevation shadows,
verbatim from the specification (a key light plus an ambient shadow). These are
the levels MD2 assigns to components, which is the whole set this design system
needs; a level with no component behind it is not defined. Components normally do
not pick a shadow directly but use a binding:

| Binding | Elevation | Component |
|---|---|---|
| `--depth-field` | 0 | filled text field — recessed, not raised |
| `--depth-control` | d2 | raised button, resting |
| `--depth-surface` | d2 | card |
| `--depth-press` | d8 | raised button, pressed |
| `--depth-appbar` | d4 | top app bar |
| `--depth-fab` | d6 | FAB |
| `--depth-overlay` | d8 | menus, sheets, the two hero panels, alerts |
| `--depth-dialog` | d24 | dialogs |

Tailwind exposes the same levels directly as `shadow-d1`, `shadow-d2`, `shadow-d3`,
`shadow-d4`, `shadow-d6`, `shadow-d8`, `shadow-d16` and `shadow-d24` for the cases
a binding does not cover (`shadow-d4` is the one in use today, for a card that
needs to read as raised).

---

## 4. Component layer (`src/style.css`)

- **`.btn`** — 36dp minimum height, 2dp radius, `--depth-control`. Interaction
  comes from two pseudo-elements: `::before` is the **state layer**
  (`background: currentColor` at 8% hover / 24% focus / 10% pressed, clipped by
  `overflow-hidden`), and `::after` expands the **hit area** to the 48dp
  `--control-size` minimum touch target. The two are kept separate on purpose —
  clipping the state layer must not clip the target.
- **`.field`** — filled Material text field: `bg-field`, no border box, no
  resting shadow, a 2dp bottom line in `--input` that becomes `primary` on focus.
- **`.card`** — 4dp radius, `--depth-surface`, **no border**.
- **`.chip`** — 32dp minimum height, 2dp radius, pill-free.
- **`.input` / `.select` / `.textarea`** — the Material form control base.
- **App bar** — 56dp (`--size-appbar`), `--depth-appbar`, and the active
  `RouterLink` carries `active-class="text-primary"`.
- **Empty state** — an elevated `card`, no dashed outline.

`--motion-ease` is `cubic-bezier(0.4, 0, 0.2, 1)` at 225ms. Spring and scale
press feedback was removed entirely.

---

## 5. Persian / RTL adaptations

Material is a Latin-script specification, so several values are adapted rather than
copied. Each one is a deliberate deviation:

| MD2 value | Here | Why |
|---|---|---|
| `letter-spacing: 0.02em` on overlines and buttons | `letter-spacing: 0` | Persian is cursive; tracking destroys glyph joining |
| uppercase button and overline labels | Persian labels, never uppercased | there is no uppercase in Persian |
| body `line-height: 1.5` | `--leading-body: 1.7` | Persian glyphs need more vertical room |
| headline `line-height: 1.1` | `--leading-headline: 1.35` | same reason, within the 1.15 floor |
| Roboto | Vazirmatn, bundled via fontsource | the project's Persian typeface, works offline |
| Roboto Medium (500) buttons | 500 kept | matches the MD2 button role |
| 4dp grid | 8dp grid with 4dp and 2dp steps | keeps the MD2 rhythm at a Persian-appropriate density |

Physical direction utilities stay banned: only logical properties (`ms-`, `ps-`,
`border-b`, `rounded-control`) appear, so the RTL flip is the browser's job.
`theme.spec.ts` fails the build if `ml-`, `pl-`, `pr-`, `left-0`, `text-left`,
`border-l` or `rounded-l` reappear in a component.

---

## 6. Verification

| Check | Result |
|---|---|
| `frontend` `vue-tsc --noEmit` | clean |
| `frontend` `vitest run` | 60 passed (8 files) |
| `frontend` `npm run build` | clean — 34.80 kB CSS / 6.68 kB gzip, 164.89 kB JS / 58.43 kB gzip |
| `backend` `pytest` | 77 passed |
| Live run, all routes (home, search, product, project + optimisation, basket, empty basket) | 6/6 passed against the running API |
| Shipped CSS audit | 0 `oklch()`, 0 retired-palette utilities, 0 leftover `shadow-card` / `shadow-pop` |

`frontend/tests/theme.spec.ts` now guards the whole contract: the three brand
colours and no others, the d1–d24 scale, the 2/4dp shape scale, the 36/32/48/56dp
component metrics, the 8dp grid, the state-layer opacities, the Material easing,
the presence of `.btn::before` / `.btn::after` / `.field`, and the absence of
colour literals, retired palettes and physical direction classes in any component.

The live run also caught a real bug: the budget field re-grouped `۵۵ میلیون` down
to `۵۵`, which read as 55 Toman while the budget in use was 55,000,000. The field
now re-groups only plain numbers and leaves any input containing a scale word or a
sentence exactly as typed, with a regression test in `tests/ui.spec.ts`.

---

## 7. Earlier migrations

- [`THEME_MIGRATION.md`](THEME_MIGRATION.md) — the original `sand` / `pine` /
  `clay` palette to a token-driven theme (Pomegranate). Still accurate about the
  **token architecture**.
- [`PALETTE_MIGRATION.md`](PALETTE_MIGRATION.md) — Pomegranate to Charcoal Blue /
  Raspberry. Historical palette values only.

Design rules that survive all three are in
[`UI_DESIGN_GUIDELINES.md`](UI_DESIGN_GUIDELINES.md).
