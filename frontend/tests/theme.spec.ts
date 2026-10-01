import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

/**
 * Guards the Material Design 2 contract:
 *  - the theme is applied to the document root,
 *  - colour, shape, elevation, type and spacing are token-driven,
 *  - no component hard-codes a colour or a physical direction utility,
 *  - the brand palette is exactly the three declared colours.
 */

const SRC = join(process.cwd(), 'src')

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry)
    return statSync(full).isDirectory() ? walk(full) : full.endsWith('.vue') ? [full] : []
  })
}

const VUE_FILES = walk(SRC)
const THEME_FILE = join(SRC, 'theme', 'material.css')
const INDEX_HTML = join(process.cwd(), 'index.html')
const STYLE_FILE = join(SRC, 'style.css')

const RETIRED_PALETTE =
  /\b(?:bg|text|border|ring|divide|from|via|to|fill|stroke|outline|shadow|accent|caret)-(?:sand|pine|clay|ink|line)(?:-[0-9]+)?\b/

const COLOUR_LITERAL = /#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(|oklch\(|oklab\(|color-mix\(/
const PHYSICAL_DIRECTION =
  /\b(?:ml-|pl-|pr-|mr-|left-0|right-0|text-left|text-right|border-l|border-r|rounded-l|rounded-r)\b/

const theme = () => readFileSync(THEME_FILE, 'utf8')

describe('Material Design 2 theme integration', () => {
  it('applies the theme to the document root', () => {
    const html = readFileSync(INDEX_HTML, 'utf8')
    expect(html).toContain('data-theme="material"')
    expect(html).toContain('lang="fa"')
    expect(html).toContain('dir="rtl"')
  })

  it('declares exactly the three brand colours', () => {
    const css = theme()
    expect(css).toContain('[data-theme=\'material\']')
    expect(css).toContain('--brand-charcoal: #424b54') // Charcoal Blue
    expect(css).toContain('--brand-white: #fffdfd') // White
    expect(css).toContain('--brand-amaranth: #990d35') // Dark Amaranth
    // the brand roles point at those tokens, not at literals
    expect(css).toContain('--primary: var(--brand-amaranth)')
    expect(css).toContain('--foreground: var(--brand-charcoal)')
    expect(css).toContain('--background: var(--brand-white)')
  })

  it('derives every neutral role from Charcoal Blue over White', () => {
    const css = theme()
    expect(css).toContain('--muted: #f4f2f3') // 6%
    expect(css).toContain('--secondary: #ecebec') // 10%
    expect(css).toContain('--muted-foreground: #6a747c') // 4.71:1
    expect(css).toContain('--border: rgb(66 75 84 / 12%)') // MD2 divider
    expect(css).toContain('--input: rgb(66 75 84 / 42%)') // unfocused field line
    expect(css).toContain('--field: var(--muted)') // filled text field
  })

  it('uses the Material corner-radius scale (2dp / 4dp)', () => {
    const css = theme()
    expect(css).toContain('--shape-control: 0.125rem') // 2dp
    expect(css).toContain('--shape-field: 0.125rem')
    expect(css).toContain('--shape-surface: 0.25rem') // 4dp
    expect(css).toContain('--shape-overlay: 0.25rem')
    expect(css).toContain('--radius: 0.25rem')
  })

  it('binds each component to its Material elevation', () => {
    const css = theme()
    for (const level of [1, 2, 3, 4, 6, 8, 16, 24]) {
      expect(css, `missing --elevation-${level}`).toContain(`--elevation-${level}:`)
    }
    // the MD2 component reference
    expect(css).toContain('--depth-control: var(--elevation-2)') // raised button 2dp
    expect(css).toContain('--depth-press: var(--elevation-8)') // pressed 8dp
    expect(css).toContain('--depth-surface: var(--elevation-2)') // card 2dp
    expect(css).toContain('--depth-overlay: var(--elevation-8)') // menus 8dp
    expect(css).toContain('--depth-dialog: var(--elevation-24)') // dialogs 24dp
    expect(css).toContain('--depth-appbar: var(--elevation-4)') // app bar 4dp
    expect(css).toContain('--depth-fab: var(--elevation-6)') // FAB 6dp
  })

  it('carries the Material type scale with Persian line-heights', () => {
    const css = theme()
    expect(css).toContain('--type-headline-weight: 600')
    expect(css).toContain('--leading-body: 1.7')
    expect(css).toContain('--leading-headline: 1.35')
    expect(css).toContain('--type-body:')
    expect(css).toContain('Vazirmatn')
  })

  it('uses the Material 8dp grid and MD2 component metrics', () => {
    const css = theme()
    expect(css).toContain('--spacing: 0.5rem') // 8dp
    expect(css).toContain('--spacing-half: 0.25rem') // 4dp
    expect(css).toContain('--control-size: 3rem') // 48dp
    expect(css).toContain('--size-button: 2.25rem') // 36dp
    expect(css).toContain('--size-chip: 2rem') // 32dp
    expect(css).toContain('--size-appbar: 3.5rem') // 56dp
  })

  it('uses Material state-layer opacities and motion', () => {
    const css = theme()
    expect(css).toContain('--state-hover: 0.08')
    expect(css).toContain('--state-focus: 0.24')
    expect(css).toContain('--state-pressed: 0.1')
    expect(css).toContain('--state-dragged: 0.16')
    expect(css).toContain('--motion-ease: cubic-bezier(0.4, 0, 0.2, 1)')
  })

  it('maps Tailwind to the Material tokens instead of a second scale', () => {
    const config = readFileSync(join(process.cwd(), 'tailwind.config.js'), 'utf8')
    for (const semantic of [
      'background', 'foreground', 'card', 'primary', 'secondary', 'muted',
      'accent', 'destructive', 'success', 'warning', 'border', 'ring', 'brand',
    ]) {
      expect(config).toContain(semantic)
    }
    expect(config).toContain('--shape-control')
    expect(config).toContain('--elevation-2')
    expect(config).toContain('--motion-ease')
    expect(config).toContain('--size-button')
    // the retired palettes stay gone, and no colour is defined outside the theme
    for (const retired of ['sand', 'pine', 'clay']) {
      expect(config).not.toMatch(new RegExp(`\\b${retired}[\\s:]`, 'm'))
    }
    expect(config).not.toMatch(/#[0-9a-fA-F]{6}/)
    expect(config).not.toContain('oklch(')
  })

  it('defines Material state layers on buttons in the component layer', () => {
    const css = readFileSync(STYLE_FILE, 'utf8')
    expect(css).toContain('.btn::before') // state layer
    expect(css).toContain('.btn::after') // 48dp hit area
    expect(css).toContain('var(--state-hover)')
    expect(css).toContain('var(--state-focus)')
    expect(css).toContain('var(--state-pressed)')
    // a filled Material text field: no shadow, 2dp line, primary on focus
    expect(css).toMatch(/\.field\s*\{[\s\S]*border-b-2[\s\S]*focus:border-ring/)
  })

  it('has no leftover references to any retired palette in components', () => {
    expect(VUE_FILES.filter((f) => RETIRED_PALETTE.test(readFileSync(f, 'utf8')))).toEqual([])
  })

  it('keeps colour out of components (tokens only)', () => {
    expect(VUE_FILES.filter((f) => COLOUR_LITERAL.test(readFileSync(f, 'utf8')))).toEqual([])
  })

  it('uses only logical, RTL-native direction utilities', () => {
    expect(VUE_FILES.filter((f) => PHYSICAL_DIRECTION.test(readFileSync(f, 'utf8')))).toEqual([])
  })
})
