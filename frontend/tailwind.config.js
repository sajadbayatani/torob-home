/**
 * Tailwind is mapped to the Material Design 2 tokens — never to a second,
 * hand-picked palette or scale. Every colour, corner radius, shadow, duration and
 * spacing step below resolves to a CSS variable defined in
 * `src/theme/material.css`, which stays the single source of truth.
 *
 * The numeric font-size keys are re-pointed at the MD2 type scale, so existing
 * utilities (`text-sm`, `text-xl`, …) become Material without touching a
 * component: sm = body 2 / button (14), base = body 1 (16), lg = headline 5 (20),
 * xl = headline 4 (24), 2xl = headline 3 (28), 3xl = headline 2 (34).
 *
 * @type {import('tailwindcss').Config}
 */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        background: 'var(--background)',
        foreground: 'var(--foreground)',
        card: { DEFAULT: 'var(--card)', foreground: 'var(--card-foreground)' },
        popover: { DEFAULT: 'var(--popover)', foreground: 'var(--popover-foreground)' },
        primary: { DEFAULT: 'var(--primary)', foreground: 'var(--primary-foreground)' },
        secondary: { DEFAULT: 'var(--secondary)', foreground: 'var(--secondary-foreground)' },
        muted: { DEFAULT: 'var(--muted)', foreground: 'var(--muted-foreground)' },
        accent: { DEFAULT: 'var(--accent)', foreground: 'var(--accent-foreground)' },
        destructive: 'var(--destructive)',
        success: 'var(--success)',
        warning: 'var(--warning)',
        border: 'var(--border)',
        // filled text fields use --field; --input is the 2dp unfocused line colour
        field: 'var(--field)',
        input: 'var(--input)',
        ring: 'var(--ring)',
        brand: { DEFAULT: 'var(--brand)', foreground: 'var(--brand-foreground)' },
      },
      fontFamily: {
        body: 'var(--type-body)',
        display: 'var(--type-display)',
      },
      fontSize: {
        // MD2 type scale
        overline: ['0.625rem', { lineHeight: '1rem' }], // 10
        '2xs': ['0.75rem', { lineHeight: '1.25rem' }], // caption 12
        xs: ['0.75rem', { lineHeight: '1.25rem' }], // caption 12
        sm: ['0.875rem', { lineHeight: '1.5rem' }], // body 2 / button 14
        base: ['1rem', { lineHeight: '1.7rem' }], // body 1 16
        lg: ['1.25rem', { lineHeight: '1.75rem' }], // headline 5 20
        xl: ['1.5rem', { lineHeight: '2rem' }], // headline 4 24
        '2xl': ['1.75rem', { lineHeight: '2.25rem' }], // headline 3 28
        '3xl': ['2.125rem', { lineHeight: '2.75rem' }], // headline 2 34
        '4xl': ['3rem', { lineHeight: '3.5rem' }], // headline 1 48 (desktop)
      },
      borderRadius: {
        control: 'var(--shape-control)', // 2dp
        field: 'var(--shape-field)', // 2dp
        surface: 'var(--shape-surface)', // 4dp
        overlay: 'var(--shape-overlay)', // 4dp
        sheet: 'var(--shape-sheet)', // 16dp
      },
      boxShadow: {
        control: 'var(--depth-control)', // 2dp
        press: 'var(--depth-press)', // 8dp
        field: 'var(--depth-field)', // 0
        surface: 'var(--depth-surface)', // 2dp
        overlay: 'var(--depth-overlay)', // 8dp
        dialog: 'var(--depth-dialog)', // 24dp
        appbar: 'var(--depth-appbar)', // 4dp
        fab: 'var(--depth-fab)', // 6dp
        // the MD2 levels this system uses, available directly where a component
        // binding below does not cover the case
        d1: 'var(--elevation-1)',
        d2: 'var(--elevation-2)',
        d3: 'var(--elevation-3)',
        d4: 'var(--elevation-4)',
        d6: 'var(--elevation-6)',
        d8: 'var(--elevation-8)',
        d16: 'var(--elevation-16)',
        d24: 'var(--elevation-24)',
      },
      transitionTimingFunction: {
        motion: 'var(--motion-ease)',
        decelerate: 'var(--motion-ease-decelerate)',
        accelerate: 'var(--motion-ease-accelerate)',
      },
      transitionDuration: {
        short: 'var(--motion-short)',
        motion: 'var(--motion)',
        long: 'var(--motion-long)',
      },
      // The thinking shimmer sweeps a 250%-wide gradient across a run of text. It
      // is defined here rather than in a component's own <style> block because no
      // component in this project carries one, and because the global
      // `prefers-reduced-motion` rule in `src/style.css` already neutralises
      // `animation-*` for everyone — the shimmer needs no second, per-component
      // opt-out and cannot drift out of step with it.
      keyframes: {
        // The shimmer is a highlight travelling across the sentence, so it is
        // eased rather than linear: a constant-speed slide reads as a mechanical
        // wipe, while one that eases in and out reads as light moving. The
        // mid-keyframe is what removes the hard start and hard stop.
        'thinking-shimmer': {
          '0%': { backgroundPosition: '110% 0' },
          '55%': { backgroundPosition: '-60% 0' },
          '100%': { backgroundPosition: '-160% 0' },
        },
        // The sparkle breathes rather than spins: a scale of a few percent and a
        // small dip in opacity, over a long period, so it is felt rather than seen.
        'thinking-pulse': {
          '0%, 100%': { transform: 'scale(1)', opacity: '1' },
          '50%': { transform: 'scale(1.08)', opacity: '0.72' },
        },
        // The ambient effect: barely there. One property, a small range, a long
        // period — anything more would compete with the sentence.
        'thinking-breathe': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.78' },
        },
      },
      animation: {
        'thinking-shimmer':
          'thinking-shimmer 2.8s cubic-bezier(0.45, 0, 0.55, 1) infinite',
        'thinking-pulse': 'thinking-pulse 3.2s cubic-bezier(0.4, 0, 0.4, 1) infinite',
        'thinking-breathe': 'thinking-breathe 4.4s cubic-bezier(0.4, 0, 0.4, 1) infinite',
      },
      // 250% is the shimmer's width, not a spacing decision, so it is named here
      // rather than written as `bg-[length:250%_100%]` at the point of use.
      backgroundSize: {
        shimmer: '250% 100%',
      },
      spacing: {
        // the MD2 8dp grid, plus its documented half-steps
        density: 'var(--spacing)',
        'density-half': 'var(--spacing-half)',
      },
      maxWidth: {
        content: '1180px',
      },
      minHeight: {
        button: 'var(--size-button)',
        chip: 'var(--size-chip)',
        field: 'var(--size-field)',
        appbar: 'var(--size-appbar)',
        fab: 'var(--size-fab)',
      },
    },
  },
  plugins: [],
}
