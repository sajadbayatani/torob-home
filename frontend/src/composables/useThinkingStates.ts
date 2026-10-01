/**
 * Persian copy for the phases a search is really in.
 *
 * The thinking states are a *label* on the requests the search already makes, so
 * this is a lookup from :data:`SearchPhase` to a sentence — not a second state
 * machine, and not a timer. Nothing here advances on a clock: a state is shown for
 * exactly as long as its request is pending, whether that is 200ms or 30 seconds.
 *
 * The list is the phases the store has **actually entered** (`phaseLog`), not a
 * fixed plan. That distinction is what makes the animation honest: every entry
 * corresponds to a request that really started, so the message on screen names the
 * operation currently running, and a search that skips the model (the catalogue was
 * confident enough on its own) never shows an interpretation message at all.
 *
 * `active` is supplied by the parent because "is a search running" is the parent's
 * to answer, not the store's. The store's `loading` only covers the requests it
 * makes itself; a view that issues its own request — project analysis — is still
 * busy while the store is idle, and reading `loading` would blank the status line
 * for the whole of that request.
 */
import { computed, toValue, type MaybeRefOrGetter } from 'vue'

import { useSearchStore } from '@/stores/searchStore'
import type { SearchPhase } from '@/stores/searchStore'

export interface ThinkingState {
  id: string
  text: string
}

/**
 * One message per phase, in the order the phases can occur.
 *
 * A project is more work than a product lookup: the model has to work out what the
 * job needs before any product is chosen, so it gets its own sentence rather than
 * reusing the product one.
 */
const COPY: Record<SearchPhase, ThinkingState> = {
  routing: { id: 'routing', text: 'دارم درخواستت رو بررسی می‌کنم' },
  understanding: { id: 'understanding', text: 'دارم نیتت رو متوجه می‌شم' },
  products: { id: 'products', text: 'دارم محصولات مناسب رو پیدا می‌کنم' },
  analysing: { id: 'analysing', text: 'دارم نیازت رو تحلیل می‌کنم' },
  // never rendered: `idle` means nothing is in flight. It is here so the lookup is
  // total and needs no fallback branch.
  idle: { id: 'idle', text: '' },
}

/**
 * The states the running search has entered, and which one is active now.
 *
 * @param active the caller's own "a search is running" flag. Required, because the
 * store cannot see requests a view makes itself.
 */
export function useThinkingStates(active: MaybeRefOrGetter<boolean>) {
  const search = useSearchStore()

  /** Every phase entered so far, in the order they were entered. */
  const states = computed<ThinkingState[]>(() =>
    search.phaseLog.map((phase) => COPY[phase]),
  )
  /** Where the request currently in flight sits in that list. */
  const activeIndex = computed(() => search.phaseLog.lastIndexOf(search.phase))
  /**
   * Shown only while the parent is busy *and* a real phase is the running one.
   *
   * Both halves matter: without `activeIndex >= 0` the component would render
   * whatever stage was last entered after the search finished, leaving a stale
   * sentence on screen.
   */
  const visible = computed(
    () => toValue(active) && search.phase !== 'idle' && activeIndex.value >= 0,
  )

  return { states, activeIndex, visible, phase: computed(() => search.phase) }
}
