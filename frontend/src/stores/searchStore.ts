/**
 * Search store: owns the *shared* search state (query, interpretation, results).
 * Per-component state (open dropdowns, local tab selection) stays local.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { productsApi, type ProductSearchParams } from '@/api/products'
import { searchApi } from '@/api/search'
import type { Intent, InterpretedIntent, ProductSearchResponse } from '@/types/api'
import { ApiError } from '@/api/client'

/**
 * Where a submission goes, decided by the interpretation and nothing else.
 *
 * `product_search` → the catalogue. `project_search` → the project flow.
 * `unknown` (and a missing interpretation) → the catalogue, as before.
 *
 * The key is the intent enum, never the query text: no phrase, room, number or
 * wording is matched anywhere in this mapping.
 */
export type SearchRoute = 'product_search' | 'project_analysis'

/**
 * Which request a running search is actually waiting on.
 *
 * This is a *label on the requests that already exist*, not a second state
 * machine and not a progress bar. Every value is set immediately before one of the
 * three calls the search already makes, and cleared when they are all done, so the
 * screen can say something true at each moment: "I am asking the catalogue where
 * this belongs" and "I am asking the model what you meant" are different waits and
 * a person can tell.
 *
 * There is deliberately no progress percentage and no intermediate step that no
 * request backs. A stage that is not a request cannot be reported as one.
 */
export type SearchPhase =
  /** nothing in flight */
  | 'idle'
  /** `GET /search/route` — the free, deterministic "where does this belong" check */
  | 'routing'
  /** `POST /search/interpret` — only reached when the catalogue was not sure */
  | 'understanding'
  /** `GET /products/search` — the catalogue query itself */
  | 'products'
  /** `POST /projects/analyze` — a project, reported by the view that calls it */
  | 'analysing'

function routeFor(intent: Intent | null | undefined): SearchRoute {
  return intent === 'NEED_SEARCH' ? 'project_analysis' : 'product_search'
}

export const useSearchStore = defineStore('search', () => {
  const query = ref('')
  const submittedQuery = ref('')
  const intent = ref<InterpretedIntent | null>(null)
  const results = ref<ProductSearchResponse | null>(null)
  const loading = ref(false)
  /**
   * The request a running search is waiting on. See :data:`SearchPhase`.
   *
   * Kept beside `loading` rather than derived from it: `loading` is a boolean that
   * says a search is happening, and this says *which* one, which is the only thing
   * the thinking states are allowed to describe.
   */
  const phase = ref<SearchPhase>('idle')
  /**
   * The phases this submission has actually entered, in order.
   *
   * Not a plan and not a queue: a phase is appended only at the moment its own
   * request starts, so this list is a record of real requests rather than a set of
   * stages we expect to reach. It gives the thinking states something to index
   * into — so the message that swaps in is the one for the request that is running,
   * and the sparkle turns a quarter for each request actually begun.
   *
   * Reset per submission, so a second search does not inherit the first one's
   * stages.
   */
  const phaseLog = ref<SearchPhase[]>([])
  const error = ref<string | null>(null)
  // Filters come from the catalogue's own fields: a subcategory, a brand, and
  // whether the product has a seller that can actually be bought from. The
  // catalogue carries no quality or style, so there is nothing to filter on
  // for those and no control is shown for them.
  /** The route the last submission took, for the view and for the logs. */
  const route = ref<SearchRoute>('product_search')
  /**
   * Whether the catalogue placed the current query on its own, with no inference.
   *
   * Held as state rather than a local, because a filter change re-runs the same
   * query with `interpret: false` and must not be mistaken for a submission that
   * had nothing at all to go on.
   */
  const routedByCatalogue = ref(false)
  /** How many times the model was asked to interpret, for this submission. */
  const interpretationCalls = ref(0)
  const filters = ref<Pick<ProductSearchParams, 'category' | 'brand' | 'onlyAvailable'>>({
    category: undefined,
    brand: undefined,
    onlyAvailable: undefined,
  })

  /**
   * Monotonic id of the newest submission.
   *
   * Searches are asynchronous and nothing cancels an in-flight one, so two
   * submissions can be in progress at once. Without a number, the slower of them
   * wins on arrival and the screen shows a result for a query the user has
   * already replaced. Every write to shared state is gated on this, so a
   * superseded search simply stops rather than overwriting.
   */
  let newestSubmission = 0

  const isProjectIntent = computed(() => route.value === 'project_analysis')
  /**
   * Whether this submission is a product search.
   *
   * Read from the **route**, not from `intent`: a query the catalogue placed on
   * its own never gets an interpretation, because making one is the cost this
   * design exists to avoid. Deriving it from the intent object would report
   * "not a product search" for the very queries that were answered without a
   * single inference.
   */
  const isProductIntent = computed(() => route.value === 'product_search')
  /**
   * Human-readable category.
   *
   * The search response now carries its own label, because a query the catalogue
   * placed deterministically has no interpretation to supply one — and showing a
   * raw slug to a shopper is a poor answer to a question that costs nothing.
   */
  const detectedCategory = computed(
    () =>
      intent.value?.product_query?.category_name ??
      results.value?.detected_category_name ??
      results.value?.detected_category ??
      null,
  )
  const hasResults = computed(() => (results.value?.items.length ?? 0) > 0)

  /**
   * Interpret once, then act on what came back.
   *
   * The interpretation is the only thing that decides what happens next, and it
   * is asked for exactly once. Previously this called `/search/interpret` and
   * then called `/products/search` with the same text, which made the backend
   * interpret it a *second* time — two inferences for one submission, and a
   * wasted product search whenever the answer was "this is a project".
   *
   * Routing reads the structured intent and nothing else: no query text is
   * inspected, so a phrasing nobody anticipated routes the same as one that was.
   */
  /**
   * Run one search. Resolves to whether *this* submission is the one now on
   * screen — `false` when it failed, or when a newer submission replaced it.
   *
   * Callers must check the result. It used to resolve to nothing and swallow its
   * own failure, so a view went on to branch on whatever the *previous* search
   * had left in `route` and `intent` — which is how a failed second search kept
   * the first search's project on screen.
   */
  async function search(
    text: string,
    options: { interpret?: boolean; reinterpret?: boolean } = {},
  ): Promise<boolean> {
    const value = text.trim()
    const submission = ++newestSubmission
    /** True while this submission is still the one the user is waiting on. */
    const current = () => submission === newestSubmission
    // Read before it is overwritten below. Comparing against `submittedQuery`
    // after assigning it compares the value with itself, which is always true,
    // and the reuse check then degrades into "an interpretation exists" — so a
    // brand-new query was never interpreted and kept the previous project's
    // interpretation, room, area and title.
    const previousQuery = submittedQuery.value
    query.value = text
    if (value.length < 2) {
      // Nothing is searched, so the store must not still be showing a search.
      // `loading` is cleared unconditionally rather than under `current()`: this
      // submission *is* the newest, and the search it just replaced is gated out
      // of its own `finally`, so nothing else would ever clear the spinner.
      loading.value = false
      error.value = null
      results.value = null
      intent.value = null
      route.value = 'product_search'
      submittedQuery.value = value
      routedByCatalogue.value = false
      interpretationCalls.value = 0
      return false
    }
    loading.value = true
    error.value = null
    submittedQuery.value = value
    interpretationCalls.value = 0
    // Only a genuinely new sentence invalidates the verdict. A filter change
    // re-runs the same query and must keep the decision it already made.
    if (previousQuery !== value) {
      routedByCatalogue.value = false
      phaseLog.value = []
      // Invalidate the previous submission's outcome *before* any await. Left in
      // place, a failure below would leave the old query's interpretation and
      // route behind, and the caller would act on them as if they described the
      // new query.
      intent.value = null
      results.value = null
      route.value = 'product_search'
    }
    try {
      // The *same sentence* is interpreted once, whatever reaches this function:
      // the home page hands the query to the results view, the view can be
      // re-entered by a route change, and a retry re-runs the same text. A
      // different sentence is always interpreted afresh, so a new query can
      // never inherit the previous project's understanding.
      const alreadyInterpreted =
        options.reinterpret !== true && intent.value !== null && previousQuery === value
      if (options.interpret !== false && !alreadyInterpreted) {
        // The first decision is deterministic and free: ask the backend whether
        // the catalogue accounts for this query on its own. Asking the model to
        // classify product-versus-project was paying an inference to answer a
        // question the catalogue can answer, and the only thing the model is
        // actually needed for is what the person is *trying to do*.
        enterPhase('routing')
        const decision = await searchApi.route(value)
        if (!current()) return false
        console.info(
          `[search] deterministic route: ${value} -> ${decision.route} ` +
            `reason=${decision.reason} ` +
            `unexplained=[${(decision.unexplained ?? []).join(', ')}]`,
        )

        if (decision.is_product) {
          // Confidently a product query, so no interpretation is made at all.
          intent.value = null
          interpretationCalls.value = 0
          routedByCatalogue.value = true
        } else {
          // Not confident. Do not guess — ask the model what is wanted.
          interpretationCalls.value += 1
          enterPhase('understanding')
          const interpretation = await searchApi.interpret(value)
          if (!current()) return false
          intent.value = interpretation
          console.info(
            `[search] interpretation request: ${value} -> intent=${intent.value.intent} ` +
              `llm_interpretation_calls=${interpretationCalls.value}`,
          )
        }
      }
      // Reached with `interpret: false` and nothing in hand, there is no way to
      // tell a project from a product query, and guessing sent project requests
      // to the catalogue. Stop instead: the caller that owns the query decides
      // what a bare re-run means.
      if (intent.value === null && !routedByCatalogue.value) {
        route.value = 'product_search'
        results.value = null
        return false
      }

      route.value =
        intent.value === null ? 'product_search' : routeFor(intent.value.intent)

      if (route.value === 'project_analysis') {
        // a project is not a product query: no catalogue search is run, and the
        // interpretation we just made is handed to the analysis flow so it is
        // not asked for again there
        results.value = null
        console.info(
          `[search] route=${route.value} interpretation_reused=false ` +
            `llm_interpretation_calls=${interpretationCalls.value}`,
        )
        return true
      }

      // The backend is told not to interpret: either the catalogue already placed
      // this query, or an interpretation was made above and is reused. Either way
      // the search itself costs no inference.
      enterPhase('products')
      const found = await productsApi.search({
        q: value,
        ...filters.value,
        interpret: false,
      })
      if (!current()) return false
      results.value = {
        ...found,
        intent: intent.value?.intent ?? found.intent,
        explanations: intent.value?.explanations ?? found.explanations,
      }
      console.info(
        `[search] route=${route.value} interpretation_reused=${options.interpret === false} ` +
          `llm_interpretation_calls=${interpretationCalls.value}`,
      )
      return true
    } catch (e) {
      // A superseded search reports nothing: the one it would overwrite is still
      // running, and its own outcome is the one that belongs on screen.
      if (!current()) return false
      error.value = e instanceof ApiError ? e.message : 'خطای ناشناخته در جستجو'
      // The failed query stays the current one, and nothing from the previous
      // submission is put back in its place.
      intent.value = null
      results.value = null
      route.value = 'product_search'
      return false
    } finally {
      if (current()) {
        loading.value = false
        phase.value = 'idle'
      }
    }
  }

  /**
   * Report a request this store does not make itself.
   *
   * The project analysis is called by the view that owns the project flow, not
   * here, so that view sets the phase for the duration of its own call and clears
   * it afterwards. Anything else would have to guess when it finished.
   */
  function setPhase(value: SearchPhase) {
    enterPhase(value)
  }

  /**
   * Mark one real request as started, and as the current one.
   *
   * Consecutive repeats are collapsed rather than stacked, so a phase the caller
   * re-reports (a filter re-run re-entering `products`) is one stage, not two.
   */
  function enterPhase(value: SearchPhase) {
    if (value === 'idle') {
      phase.value = 'idle'
      return
    }
    phase.value = value
    const log = phaseLog.value
    if (log[log.length - 1] !== value) log.push(value)
  }

  async function applyFilters(next: Partial<typeof filters.value>) {
    filters.value = { ...filters.value, ...next }
    if (submittedQuery.value) await search(submittedQuery.value, { interpret: false })
  }

  function reset() {
    query.value = ''
    submittedQuery.value = ''
    intent.value = null
    results.value = null
    error.value = null
    filters.value = { category: undefined, brand: undefined, onlyAvailable: undefined }
  }

  return {
    query,
    submittedQuery,
    intent,
    results,
    loading,
    phase,
    phaseLog,
    error,
    filters,
    route,
    interpretationCalls,
    isProjectIntent,
    isProductIntent,
    detectedCategory,
    hasResults,
    search,
    setPhase,
    applyFilters,
    reset,
  }
})
