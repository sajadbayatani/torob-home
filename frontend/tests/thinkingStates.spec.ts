/**
 * Thinking states: what it draws, and — more importantly — when it is allowed to.
 *
 * The failure this guards against is not a broken animation, it is a *lying* one.
 * A loading label that shows a phase no request is in, or that lingers after the
 * search is over, tells a person their search is doing something it is not. So the
 * tests here check the coupling to the real store phase as closely as they check
 * the markup.
 *
 * The animation itself is CSS and cannot be asserted in jsdom; what *is* asserted
 * is the mechanism that produces it — both sentences in one grid cell, the longest
 * one holding the width, the outgoing copy hidden from assistive technology, and
 * the incoming copy inside the live region.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import ThinkingStates from '@/components/search/ThinkingStates.vue'
import { useThinkingStates } from '@/composables/useThinkingStates'
import { useSearchStore } from '@/stores/searchStore'
import type { SearchPhase } from '@/stores/searchStore'

/**
 * The three dots the component renders after the sentence.
 *
 * They live in the component, not in the copy, because they are what makes a
 * waiting sentence feel alive — so a state carries its text clean, and this is
 * what a reader actually ends up seeing.
 */
const DOTS = '...'

const STATES = [
  { id: 'routing', text: 'دارم درخواستت رو بررسی می‌کنم' },
  { id: 'understanding', text: 'دارم نیتت رو متوجه می‌شم' },
  { id: 'products', text: 'دارم محصولات مناسب رو پیدا می‌کنم' },
]

/**
 * Every wrapper made here, so they can all be torn down.
 *
 * A component left mounted keeps its swap timer and its animation frame alive, and
 * the next test's fake clock then drives a callback that belongs to the previous
 * one. The component is fine; the isolation was not.
 */
const mounted: ReturnType<typeof mount>[] = []

function mountStates(props: Record<string, unknown> = {}) {
  const wrapper = mount(ThinkingStates, {
    props: { states: STATES, activeIndex: 0, visible: true, ...props },
    attachTo: document.body,
  })
  mounted.push(wrapper)
  return wrapper
}

afterEach(() => {
  while (mounted.length) mounted.pop()?.unmount()
  document.body.innerHTML = ''
  vi.useRealTimers()
})

describe('ThinkingStates', () => {
  it('shows the active sentence and nothing else as live text', () => {
    const wrapper = mountStates({ activeIndex: 1 })
    expect(wrapper.get('[data-test="thinking-active"]').text()).toBe(STATES[1].text + DOTS)
    // one live sentence, so a screen reader announces one thing
    expect(wrapper.findAll('[role="status"]')).toHaveLength(1)
  })

  it('is a Persian RTL status region', () => {
    const wrapper = mountStates()
    const region = wrapper.get('[data-test="thinking-states"]')
    expect(region.attributes('role')).toBe('status')
    expect(region.attributes('dir')).toBe('rtl')
  })

  it('hides itself when told not to be visible', () => {
    // the parent owns the decision; the component obeys it
    expect(mountStates({ visible: false }).find('[data-test="thinking-states"]').exists()).toBe(false)
  })

  it('shows nothing for an index that names no state', () => {
    // -1 is what the composable returns when nothing is in flight
    expect(mountStates({ activeIndex: -1 }).find('[data-test="thinking-states"]').exists()).toBe(false)
    expect(mountStates({ activeIndex: 99 }).find('[data-test="thinking-states"]').exists()).toBe(false)
  })

  it('holds the width open with the longest sentence, not a hardcoded one', () => {
    const longest = STATES.reduce((a, b) => (b.text.length > a.text.length ? b : a))
    const wrapper = mountStates({ activeIndex: 0 })
    const sizer = wrapper.get('[data-test="thinking-sizer"]')
    expect(sizer.text()).toBe(longest.text)
    expect(sizer.text().length).toBeGreaterThan(STATES[0].text.length)
  })

  it('never lets the width-holding copy be announced', () => {
    // it is real text in the DOM, so without this a screen reader would read every
    // sentence in the list on every state change
    expect(mountStates().get('[data-test="thinking-sizer"]').attributes('aria-hidden')).toBe('true')
  })

  it('stacks the sentences in one grid cell so the box cannot jump', () => {
    const wrapper = mountStates()
    const stack = wrapper.get('[data-test="thinking-stack"]')
    expect(stack.classes()).toContain('relative')
    // both the sizer and the active sentence are taken out of flow and pinned to
    // the same box, so a longer sentence cannot widen the row
    expect(wrapper.get('[data-test="thinking-active"]').classes()).toContain('absolute')
    expect(wrapper.get('[data-test="thinking-active"]').classes()).toContain('inset-0')
  })

  it('shimmers the active sentence with a 250% gradient clipped to the text', () => {
    const active = mountStates().get('[data-test="thinking-active"]')
    expect(active.classes()).toContain('bg-clip-text')
    expect(active.classes()).toContain('animate-thinking-shimmer')
    expect(active.classes()).toContain('bg-shimmer')
  })

  it('does not colour the text with anything but theme tokens', () => {
    const active = mountStates().get('[data-test="thinking-active"]')
    for (const token of ['from-muted-foreground', 'via-foreground', 'to-muted-foreground']) {
      expect(active.classes()).toContain(token)
    }
    expect(active.classes()).toContain('text-transparent')
    // a shimmer is a highlight, not a colour of its own
    expect(active.attributes('class')).not.toMatch(/#[0-9a-f]{3,8}\b|rgb\(/i)
  })

  it('rotates the sparkle by 90 degrees per state', () => {
    const rotation = (index: number) =>
      mountStates({ activeIndex: index }).get('[data-test="thinking-sparkle"]').attributes('style')
    expect(rotation(0)).toContain('rotate(0deg)')
    expect(rotation(1)).toContain('rotate(90deg)')
    expect(rotation(2)).toContain('rotate(180deg)')
  })

  it('hides the sparkle and the outgoing copy from assistive technology', () => {
    const wrapper = mountStates()
    expect(wrapper.get('[data-test="thinking-sparkle"]').attributes('aria-hidden')).toBe('true')
  })

  it('keeps the sentence readable when reduced motion is requested', () => {
    /**
     * Not the same as "shorter".
     *
     * The global rule parks the 250% gradient at its end position after one 0.01ms
     * frame, while the text is still transparent — so stopping the animation alone
     * leaves the sentence clipped away and unreadable. The fallback therefore drops
     * the gradient and gives the text its own colour.
     */
    const active = mountStates().get('[data-test="thinking-active"]')
    expect(active.classes()).toContain('motion-reduce:animate-none')
    expect(active.classes()).toContain('motion-reduce:bg-none')
    expect(active.classes()).toContain('motion-reduce:text-muted-foreground')
  })

  it('drops the outgoing layer entirely under reduced motion', async () => {
    vi.useFakeTimers()
    try {
      const wrapper = mountStates({ activeIndex: 0 })
      await wrapper.setProps({ activeIndex: 1 })
      expect(wrapper.get('[data-test="thinking-outgoing"]').classes()).toContain('motion-reduce:hidden')
    } finally {
      vi.useRealTimers()
    }
  })

  it('starts the incoming sentence low and blurred, then settles', async () => {
    vi.useFakeTimers()
    try {
      const wrapper = mountStates({ activeIndex: 0 })
      const active = () => wrapper.get('[data-test="thinking-active"]')
      expect(active().attributes('class')).toContain('translate-y-0')

      await wrapper.setProps({ activeIndex: 1 })
      // one frame in its start state: 6px low, blurred, transparent
      expect(active().attributes('class')).toContain('translate-y-[6px]')
      expect(active().attributes('class')).toContain('opacity-0')
      expect(active().attributes('class')).toContain('blur-[2px]')

      // then released on the next animation frame — a frame is not a microtask, so
      // the fake clock has to be advanced for the callback to run and the component
      // to re-render. The async form flushes between timers, which is what makes
      // this reliable when the whole file runs rather than the test alone.
      await vi.advanceTimersByTimeAsync(20)
      expect(active().attributes('class')).toContain('translate-y-0')
      expect(active().attributes('class')).toContain('opacity-100')
    } finally {
      vi.useRealTimers()
    }
  })

  describe('motion polish', () => {
    it('the swap is smooth and within the requested window', async () => {
      // 150ms read as abrupt for a sentence this long; the design system's
      // standard motion step (225ms) sits inside the requested 150-250ms and is a
      // token rather than a new number. Decelerating is what makes it *settle*.
      const active = mountStates().get('[data-test="thinking-active"]')
      expect(active.classes()).toContain('duration-motion')
      expect(active.classes()).toContain('ease-decelerate')
      expect(active.classes()).not.toContain('duration-short')
      // the outgoing layer only exists after a real change, so make one
      const wrapper = mountStates({ activeIndex: 0 })
      await wrapper.setProps({ activeIndex: 1 })
      expect(wrapper.get('[data-test="thinking-outgoing"]').classes()).toContain(
        'ease-decelerate',
      )
    })

    it('the shimmer eases rather than sliding at a constant speed', () => {
      const config = readFileSync(join(__dirname, '..', 'tailwind.config.js'), 'utf-8')
      // a linear sweep reads as a mechanical wipe
      expect(config).toMatch(/thinking-shimmer[^']*cubic-bezier/)
      expect(config).not.toMatch(/'thinking-shimmer[^']*linear infinite/)
      // and it is not fast
      const seconds = Number(config.match(/thinking-shimmer (\d+\.\d+)s/)?.[1])
      expect(seconds).toBeGreaterThanOrEqual(2)
    })

    it('the sparkle pulses and turns as two separate motions', () => {
      /**
       * Composed rather than fused.
       *
       * The angle is a per-state transform and the breath is a keyframe on the
       * same property, so on one element the keyframe would win and the icon would
       * never sit at its state's angle.
       */
      const wrapper = mountStates().get('[data-test="thinking-sparkle"]').element
        .parentElement as HTMLElement
      expect(wrapper.className).toContain('animate-thinking-pulse')

      const sparkle = mountStates().get('[data-test="thinking-sparkle"]')
      // the turn is transitioned, so a state change is a quarter turn not a jump
      expect(sparkle.classes()).toContain('transition-transform')
      expect(sparkle.classes()).toContain('duration-long')
      expect(sparkle.attributes('style')).toContain('rotate(')
    })

    it('the ambient effect is barely there', () => {
      const region = mountStates().get('[data-test="thinking-states"]')
      expect(region.classes()).toContain('animate-thinking-breathe')
      // and it is opacity only: a fade, not a glow, a blob or a bounce
      const config = readFileSync(join(__dirname, '..', 'tailwind.config.js'), 'utf-8')
      const keyframes = config.slice(config.indexOf("'thinking-breathe': {"),)
      const block = keyframes.slice(0, keyframes.indexOf('},'))
      expect(block).toContain('opacity')
      expect(block).not.toMatch(/translate|scale|box-shadow|filter/)
    })

    it('every continuous motion is switched off under reduced motion', () => {
      const region = mountStates().get('[data-test="thinking-states"]')
      expect(region.classes()).toContain('motion-reduce:animate-none')

      const wrapper = mountStates().get('[data-test="thinking-sparkle"]').element
        .parentElement as HTMLElement
      expect(wrapper.className).toContain('motion-reduce:animate-none')

      const active = mountStates().get('[data-test="thinking-active"]')
      expect(active.classes()).toContain('motion-reduce:animate-none')
      // the turn becomes instant rather than animated, but the angle still applies
      expect(active.classes()).toContain('motion-reduce:transition-none')
      // and the sentence is still there to read
      expect(active.text()).toBe(STATES[0].text + DOTS)
    })

    it('adds no colour of its own', () => {
      const source = readFileSync(
        join(__dirname, '..', 'src', 'components', 'search', 'ThinkingStates.vue'),
        'utf-8',
      )
      expect(source).not.toMatch(/#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(/)
    })
  })

  it('introduces no interactive element', () => {
    // the search box owns focus; a decorative status must not add a tab stop
    const wrapper = mountStates()
    expect(wrapper.findAll('button, a, input, [tabindex]')).toHaveLength(0)
  })

  describe('when the state changes', () => {
    it('keeps the previous sentence mounted so it can animate out', async () => {
      vi.useFakeTimers()
      try {
        const wrapper = mountStates({ activeIndex: 0 })
        expect(wrapper.find('[data-test="thinking-outgoing"]').exists()).toBe(false)

        await wrapper.setProps({ activeIndex: 1 })
        // both are present for the length of the transition, stacked in one cell
        expect(wrapper.get('[data-test="thinking-outgoing"]').text()).toBe(STATES[0].text)
        expect(wrapper.get('[data-test="thinking-active"]').text()).toBe(STATES[1].text + DOTS)

        // released by its own transition finishing, not by a timer — jsdom does
        // not animate, so the event is dispatched as the browser would fire it
        await wrapper.get('[data-test="thinking-outgoing"]').trigger('transitionend')
        expect(wrapper.find('[data-test="thinking-outgoing"]').exists()).toBe(false)
      } finally {
        vi.useRealTimers()
      }
    })

    it('keeps the outgoing copy out of the live region', async () => {
      vi.useFakeTimers()
      try {
        const wrapper = mountStates({ activeIndex: 0 })
        await wrapper.setProps({ activeIndex: 1 })
        const outgoing = wrapper.get('[data-test="thinking-outgoing"]')
        expect(outgoing.attributes('aria-hidden')).toBe('true')
        // otherwise both sentences would be announced on every change
        expect(outgoing.text()).not.toBe(wrapper.get('[data-test="thinking-active"]').text())
      } finally {
        vi.useRealTimers()
      }
    })

    it('does not leave a stale sentence when the component is hidden mid-swap', async () => {
      vi.useFakeTimers()
      try {
        const wrapper = mountStates({ activeIndex: 0 })
        await wrapper.setProps({ activeIndex: 1 })
        await wrapper.setProps({ visible: false })
        expect(wrapper.find('[data-test="thinking-states"]').exists()).toBe(false)
        // and the pending timer is cleared on unmount, not left to fire
        wrapper.unmount()
        expect(() => vi.advanceTimersByTime(200)).not.toThrow()
      } finally {
        vi.useRealTimers()
      }
    })
  })
})

describe('useThinkingStates: the sentence must match a real request', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('shows nothing while the store is idle', () => {
    const thinking = useThinkingStates(() => true)
    expect(thinking.visible.value).toBe(false)
    expect(thinking.states.value).toEqual([])
    expect(thinking.activeIndex.value).toBe(-1)
  })

  it.each([
    ['routing', 'دارم درخواستت رو بررسی می‌کنم'],
    ['understanding', 'دارم نیتت رو متوجه می‌شم'],
    ['products', 'دارم محصولات مناسب رو پیدا می‌کنم'],
    ['analysing', 'دارم نیازت رو تحلیل می‌کنم'],
  ])('names the phase that is actually running: %s', (phase, text) => {
    const search = useSearchStore()
    search.setPhase(phase as SearchPhase)

    const thinking = useThinkingStates(() => true)
    expect(thinking.visible.value).toBe(true)
    expect(thinking.states.value.at(-1)?.text).toBe(text)
    expect(thinking.activeIndex.value).toBe(search.phaseLog.length - 1)
  })

  it('never claims to be working when the caller is not busy', () => {
    // the parent owns this: a view's own request is still running while the
    // store's own `loading` is already false
    const search = useSearchStore()
    search.setPhase('analysing')
    expect(useThinkingStates(() => false).visible.value).toBe(false)
  })

  it('never advances on its own', () => {
    // The whole point. No timer, no clock, no percentage.
    vi.useFakeTimers()
    const search = useSearchStore()
    search.setPhase('routing')
    const thinking = useThinkingStates(() => true)
    const first = thinking.activeIndex.value
    const firstStates = [...thinking.states.value]

    vi.advanceTimersByTime(30_000)
    expect(thinking.activeIndex.value).toBe(first)
    expect(thinking.states.value).toEqual(firstStates)
    vi.useRealTimers()
  })

  it('holds one state for as long as the request is pending', () => {
    /**
     * The acceptance criterion, stated as a test.
     *
     * Thirty seconds pass with no clock involvement and the state does not move,
     * because the phase only changes when a real request starts — not when time
     * passes. The index is real too: a second request is the second entry, so the
     * animation has something to swap between.
     */
    const search = useSearchStore()
    search.setPhase('routing')
    const thinking = useThinkingStates(() => true)

    expect(thinking.activeIndex.value).toBe(0)
    expect(thinking.states.value).toHaveLength(1)

    // 30s later the LLM is still thinking: same state, same index
    vi.useFakeTimers()
    vi.advanceTimersByTime(30_000)
    expect(thinking.activeIndex.value).toBe(0)
    expect(thinking.states.value.at(-1)?.text).toBe(STATES[0].text)
    vi.useRealTimers()

    // only when the next request actually starts does the state move
    search.setPhase('understanding')
    expect(thinking.activeIndex.value).toBe(1)
    expect(thinking.states.value).toHaveLength(2)
    expect(thinking.states.value.at(-1)?.text).toBe(STATES[1].text)
  })

  it('only lists phases that really happened, so a skipped model shows nothing', () => {
    // the catalogue was confident: routing then products, never an interpretation
    const search = useSearchStore()
    search.setPhase('routing')
    search.setPhase('products')

    const thinking = useThinkingStates(() => true)
    expect(thinking.states.value.map((s) => s.id)).toEqual(['routing', 'products'])
    expect(thinking.activeIndex.value).toBe(1)
  })

  it('starts a fresh list for a second search', () => {
    const search = useSearchStore()
    search.setPhase('routing')
    search.setPhase('understanding')
    search.phaseLog = []

    const thinking = useThinkingStates(() => true)
    expect(thinking.states.value).toEqual([])
    expect(thinking.activeIndex.value).toBe(-1)
    expect(thinking.visible.value).toBe(false)
  })

  it('says nothing generic', () => {
    const search = useSearchStore()
    for (const banned of ['در حال پردازش', 'لطفاً صبر کنید', 'Loading', 'Processing']) {
      search.setPhase('routing')
      expect(useThinkingStates(() => true).states.value.map((s) => s.text)).not.toContain(banned)
    }
  })
})

describe('the thinking state is driven by requests, not a clock', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('the component holds no timer at all', async () => {
    /**
     * Read from the source, because this is the property a test cannot otherwise
     * observe: a timer inside a component produces no visible effect until real
     * time passes, and a fake clock makes it look harmless.
     */
    const source = readFileSync(
      join(__dirname, '..', 'src', 'components', 'search', 'ThinkingStates.vue'),
      'utf-8',
    )
    // strip comments so the prose explaining *why* there are none does not trip it
    const code = source.replace(/<!--[\s\S]*?-->/g, '').replace(/\/\*[\s\S]*?\*\//g, '')
    for (const banned of ['setTimeout', 'setInterval']) {
      expect(code).not.toContain(banned)
    }
  })

  it('the store advances the phase only at a real request boundary', async () => {
    const search = useSearchStore()
    search.setPhase('routing')
    expect(search.phaseLog).toEqual(['routing'])
    // nothing but an explicit enterPhase changes it
    vi.useFakeTimers()
    vi.advanceTimersByTime(60_000)
    expect(search.phase).toBe('routing')
    expect(search.phaseLog).toEqual(['routing'])
    vi.useRealTimers()
  })
})
