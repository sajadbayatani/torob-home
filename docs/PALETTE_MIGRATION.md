# Palette Migration — Charcoal Blue / Raspberry

A **colour-only** change. The design language, components, layout, typography,
spacing, radius, shadows, motion and UX are exactly as they were. No component file
was modified; the entire change lives in the token layer.

Applied via `<html lang="fa" dir="rtl" data-theme="charcoal-raspberry">`.

> **Historical.** Both the palette and the component language have since changed:
> the app is now **Material Design 2** with Charcoal Blue / White / Dark Amaranth —
> see [`MATERIAL_MIGRATION.md`](MATERIAL_MIGRATION.md). The values below describe
> what was true at that revision.

---

## 1. The palette

| Role | Colour | Contrast |
|---|---|---|
| Foreground / text | Charcoal Blue `#424B54` | 8.76:1 on White |
| Background / surfaces | White `#FFFDFD` | — |
| Primary / brand / actions | Raspberry `#D52941` | 4.91:1 on White, and 4.91:1 against a White label |
| Accent / hover / emphasis | Dark Amaranth `#990D35` | 8.41:1 on White |

Dark Amaranth is used sparingly: the primary-button hover state and the project
identity accents (project brief band, basket manifest band, the "need" starting
point, the need-query panel).

### Derived tokens

Everything else is a tint or alpha of the four colours, so no new palette was
introduced:

| Token | Value | Derivation |
|---|---|---|
| `--muted`, `--accent` | `#f4f2f3` | Charcoal Blue at 6% over White |
| `--secondary` | `#ecebec` | Charcoal Blue at 10% over White |
| `--muted-foreground` | `#6a747c` | Charcoal Blue, lightened to 4.71:1 (AA for meta text) |
| `--border` | `rgb(66 75 84 / 10%)` | Charcoal Blue at 10% |
| `--input` | `rgb(66 75 84 / 14%)` | Charcoal Blue at 14% |
| `--field` | `var(--card)` | White, as before |

Two tokens are **semantic state colours** rather than palette members, because they
must stay distinguishable from the primary action or the UI would lose meaning:
`--success: #1f7a5c` (5.18:1, in-stock / within budget / savings) and
`--warning: #8f6410` (5.18:1, over budget / low stock). `--destructive` uses Dark
Amaranth, the deepest red available in the palette.

## 2. What was removed

- The `sand` / `pine` / `clay` / `ink` / `line` palette, deleted in the previous
  migration, is still gone and is now enforced by a test.
- The previous theme file `src/theme/pomegranate.css` and its warm `oklch`
  values are gone. `src/theme/charcoal-raspberry.css` replaces it. The theme was
  renamed because the Pomegranate name no longer described the palette.
- Tailwind defines **no colours of its own**; it maps to the CSS variables.
- No component hard-codes a colour.

## 3. What was deliberately *not* touched

All 22 non-colour tokens are byte-identical to the previous theme:

```
--radius 1.25rem      --shape-control 999px   --shape-field 1rem
--shape-surface 1.75rem  --shape-overlay 1.5rem  --line 1px
--press scale(0.95)   --motion 420ms         --motion-ease spring
--spacing 0.275rem    --control-size 2.75rem  --type-body / --type-display
--type-display-weight 800  --leading-body 1.8  --leading-display 1.35
--leading-control 1.5  --backdrop none       --surface-filter none
```

The depth tokens keep their exact layer structure and geometry (`inset 0 -3px 0 0`,
`inset 0 2px 0 0`, `0 10px 20px -10px`, `inset 0 2px 5px 0`, `0 24px 44px -24px`,
`0 30px 60px -22px`, and the same opacities). Only the shadow *hues* follow the
palette — a near-black neutral derived from Charcoal Blue for the inner shade, and
Dark Amaranth for the outer coloured drop.

`git diff --name-only HEAD -- '*.vue'` returns nothing: no component, view or
layout was edited.

The one functional edit in the component layer is the primary button's hover state:
`hover:brightness-[1.06]` became `hover:bg-brand`, which puts Dark Amaranth to
work as the hover colour the brief asks for, instead of a brightness filter.

## 4. Verification

| Check | Result |
|---|---|
| `vue-tsc --noEmit` | clean |
| `vitest` | 55 passed (8 files) |
| Production build | ok — 165 kB JS, 32 kB CSS |
| Non-colour tokens | 22/22 identical to the previous theme |
| Component files changed | 0 |
| Shipped CSS colour literals | only `#424b54`, `#fffdfd`, `#d52941`, `#990d35`, their Charcoal Blue tints, the two state colours, and Tailwind preflight defaults (`#fff`, `#0000`, `#9ca3af`, `#e5e7eb`, the last two overridden by the base layer with tokens) |
| `oklch` values left in the bundle | 0 |
| Old palette classes in the bundle | 0 |
| Live run, all five routes | home, search, product, project, basket — behaviour identical |
| Backend `pytest` | 77 passed, unchanged |

`frontend/tests/theme.spec.ts` now asserts all four brand colours, the unchanged
shape/motion/depth/type/density values, the derived tints, the absence of both
retired palettes and of any `oklch`, that no component hard-codes a colour or uses a
physical direction utility, and that the theme is applied to the document root.
