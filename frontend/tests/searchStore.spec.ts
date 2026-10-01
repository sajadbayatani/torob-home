import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useSearchStore } from '@/stores/searchStore'
import type { InterpretedIntent, Product, ProductSearchResponse } from '@/types/api'

const PRODUCT_INTENT: InterpretedIntent = {
  intent: 'PRODUCT_SEARCH',
  domain: 'bathroom',
  project_type: null,
  template_slug: null,
  product_query: {
    text: 'شیر توکار برند X',
    tokens: ['شیر', 'توکار', 'برند', 'x'],
    raw_brand: 'X',
    brand_id: null,
    brand_name: null,
    category_slug: 'sink-faucet',
    category_name: 'شیر روشویی',
    domain: 'bathroom',
    quality: null,
    style: null,
  },
  requirements: { area_m2: null, quality: null, style: null, budget: null, priorities: [], extra: {} },
  constraint_kind: 'NONE',
  confidence: 0.55,
  interpreter: 'rules',
  explanations: ['دستهٔ محصول تشخیص داده شد: شیر روشویی.'],
  matched_subcategories: ['sink-faucet'],
  missing_categories: [],
  room: null,
  goal: null,
}

const PROJECT_INTENT: InterpretedIntent = {
  ...PRODUCT_INTENT,
  intent: 'NEED_SEARCH',
  product_query: null,
  project_type: 'renovation',
  template_slug: 'bathroom_renovation',
  requirements: { area_m2: 12, quality: 'medium', style: null, budget: null, priorities: [], extra: {} },
  confidence: 0.75,
  room: 'سرویس بهداشتی',
  goal: 'بازسازی سرویس بهداشتی',
  matched_subcategories: ['toilet', 'sink', 'sink-faucet'],
}

function product(id: string, name: string, subcategory = 'sink-faucet'): Product {
  return {
    id,
    slug: id,
    name,
    subtitle: null,
    brand: null,
    category: {
      id: subcategory,
      slug: subcategory,
      name: 'شیر روشویی',
      domain: 'bathroom',
      kind: 'fixture',
      description_fa: null,
      product_count: 1,
    },
    domain: 'bathroom',
    subcategory,
    model: null,
    image_url: 'https://image.torob.com/x.jpg',
    source_url: `https://torob.com/p/${id}`,
    quality: null,
    quality_fa: null,
    style: null,
    unit: null,
    rating: null,
    warranty_months: null,
    origin_country: null,
    attributes: [],
    offers: [],
    offers_count: 0,
    min_price: 1_000_000,
    max_price: null,
    available_offers_count: 0,
    is_demo: false,
    match_score: 8,
  }
}

function searchResponse(items: Product[], total = items.length): ProductSearchResponse {
  return {
    query: 'شیر',
    total,
    limit: 20,
    offset: 0,
    detected_category: 'sink-faucet',
    detected_category_name: 'شیر روشویی',
    detected_domain: 'bathroom',
    intent: 'PRODUCT_SEARCH',
    items: items.map((p) => ({ product: p, matched_terms: ['شیر'], reasons: ['مطابقت'] })),
    facets: { categories: [], brands: [], subcategories: [] },
    explanations: ['۱ نتیجه از ۷۰ محصول کاتالوگ.'],
    suggestions: ['شیر روشویی'],
  }
}

const TWO_PRODUCTS = [
  product('11111111-1111-4111-8111-111111111111', 'شیر روشویی کاسا'),
  product('22222222-2222-4222-8222-222222222222', 'شیر روشویی قهرمان'),
]

function mockFetchSequence(handlers: Record<string, unknown>) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    const key = Object.keys(handlers).find((k) => url.includes(k))
    const body = key ? handlers[key] : {}
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  })
}

describe('searchStore', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      mockFetchSequence({
        // the deterministic router answers first, and for a product query the
        // interpreter is never reached at all
        '/search/route': { route: 'product', is_product: true, explained: ['شیر'], unexplained: [], reason: 'all_words_explained' },
        '/search/interpret': PRODUCT_INTENT,
        '/products/search': searchResponse(TWO_PRODUCTS),
      }),
    )
  })

  it('classifies the query on the server and stores the results', async () => {
    const store = useSearchStore()
    await store.search('شیر')

    expect(store.isProductIntent).toBe(true)
    expect(store.isProjectIntent).toBe(false)
    expect(store.detectedCategory).toBe('شیر روشویی')
    expect(store.hasResults).toBe(true)
    expect(store.results?.total).toBe(2)
    expect(store.results?.items[0].product.name).toBe('شیر روشویی کاسا')
  })

  it('asks the deterministic router first, and skips the model when it is sure', async () => {
    const store = useSearchStore()
    await store.search('شیر')

    const urls = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.map((call) =>
      String(call[0]),
    )
    // the routing decision comes first, and costs nothing
    expect(urls[0]).toContain('/api/v1/search/route')
    // the catalogue answered on its own, so the model was never asked
    expect(urls.some((url) => url.includes('/api/v1/search/interpret'))).toBe(false)
    expect(store.interpretationCalls).toBe(0)
    expect(store.isProductIntent).toBe(true)
    expect(store.hasResults).toBe(true)
  })

  it('asks the model when the catalogue is not sure', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetchSequence({
        '/search/route': { route: 'llm', is_product: false, explained: [], unexplained: ['اتاق'], reason: 'unexplained_words' },
        '/search/interpret': PROJECT_INTENT,
        '/products/search': searchResponse([]),
      }),
    )
    const store = useSearchStore()
    await store.search('اتاق خوابم')

    const urls = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.map((call) =>
      String(call[0]),
    )
    expect(urls[0]).toContain('/api/v1/search/route')
    // not confident means do not guess: the model decides
    expect(urls.some((url) => url.includes('/api/v1/search/interpret'))).toBe(true)
    expect(store.interpretationCalls).toBe(1)
  })

  it('reads products from the backend, never from a file', async () => {
    const store = useSearchStore()
    await store.search('شیر')

    const urls = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.map((call) =>
      String(call[0]),
    )
    expect(urls.some((url) => url.includes('/api/v1/products/search'))).toBe(true)
    // the catalogue file is not a frontend asset
    expect(urls.some((url) => url.includes('products.json'))).toBe(false)
  })

  it('flags a need query so the UI can route to the project flow', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetchSequence({
        '/search/route': { route: 'llm', is_product: false, explained: [], unexplained: ['اتاق'], reason: 'unexplained_words' },
        '/search/interpret': PROJECT_INTENT,
        '/products/search': searchResponse([]),
      }),
    )
    const store = useSearchStore()
    await store.search('بازسازی سرویس بهداشتی ۱۲ متری، کیفیت متوسط')

    expect(store.isProjectIntent).toBe(true)
    expect(store.intent?.requirements.area_m2).toBe(12)
    expect(store.intent?.requirements.quality).toBe('medium')
  })

  it('never searches for queries that are too short', async () => {
    const store = useSearchStore()
    await store.search('a')
    expect(store.results).toBeNull()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('surfaces API errors instead of pretending there are results', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ detail: 'سرور در دسترس نیست' }), { status: 500 })),
    )
    const store = useSearchStore()
    await store.search('شیر توکار')

    expect(store.error).toBe('سرور در دسترس نیست')
    expect(store.results).toBeNull()
  })

  it('sends a catalogue filter to the backend and re-runs the search', async () => {
    const store = useSearchStore()
    await store.search('شیر')
    await store.applyFilters({ category: 'sink-faucet' })

    expect(store.filters.category).toBe('sink-faucet')
    const urls = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.map((call) =>
      String(call[0]),
    )
    expect(urls.some((url) => url.includes('category=sink-faucet'))).toBe(true)
  })

  it('resets every filter', async () => {
    const store = useSearchStore()
    await store.search('شیر')
    await store.applyFilters({ brand: 'کاسا', category: 'sink-faucet' })
    store.reset()

    expect(store.filters).toEqual({ category: undefined, brand: undefined, onlyAvailable: undefined })
    expect(store.results).toBeNull()
    expect(store.submittedQuery).toBe('')
  })
})

/**
 * A failed search must never leave the previous search on screen.
 *
 * The reported symptom was a second project query whose interpretation call
 * failed, after which the first query's project was still displayed. The cause was
 * not the failure itself: `search()` swallowed it, resolved to nothing, and left
 * the earlier `intent` and `route` in place, so the caller branched on another
 * query's understanding as if it were this one's.
 */
describe('searchStore: a failed search leaves nothing behind', () => {
  /** Answers each path; `fail` makes a path reject, as a 503 or a dead network would. */
  function mockFetch(opts: { route?: unknown; interpret?: unknown; fail?: string[] } = {}) {
    const fail = new Set(opts.fail ?? [])
    return vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (fail.has('route') && url.includes('/search/route')) throw new Error('route down')
      if (fail.has('interpret') && url.includes('/search/interpret')) throw new Error('interpret down')
      if (url.includes('/search/route')) {
        return jsonResponse(opts.route ?? { route: 'llm', is_product: false, explained: [], unexplained: ['اتاق'], reason: 'unexplained_words' })
      }
      if (url.includes('/search/interpret')) {
        return jsonResponse(opts.interpret ?? PROJECT_INTENT)
      }
      if (url.includes('/products/search')) return jsonResponse(searchResponse(TWO_PRODUCTS))
      return jsonResponse({})
    })
  }

  function jsonResponse(body: unknown) {
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }

  const projectRoutes = (intent = PROJECT_INTENT) => ({
    route: { route: 'llm', is_product: false, explained: [], unexplained: [], reason: 'unexplained_words' },
    interpret: intent,
  })

  it('1. a failed second project search drops the first project', async () => {
    vi.stubGlobal('fetch', mockFetch(projectRoutes()))
    const store = useSearchStore()
    expect(await store.search('بازسازی سرویس بهداشتی')).toBe(true)
    expect(store.isProjectIntent).toBe(true)
    expect(store.intent).not.toBeNull()

    vi.stubGlobal('fetch', mockFetch({ ...projectRoutes(), fail: ['interpret'] }))
    expect(await store.search('اتاق خوابم رو تغییر دکوراسیون بدم')).toBe(false)

    // the new query is the current one, and nothing of the old one survives
    expect(store.submittedQuery).toBe('اتاق خوابم رو تغییر دکوراسیون بدم')
    expect(store.intent).toBeNull()
    expect(store.results).toBeNull()
    expect(store.isProjectIntent).toBe(false)
    expect(store.error).toBeTruthy()
    expect(store.loading).toBe(false)
  })

  it('2. a failed product search also drops the first project', async () => {
    vi.stubGlobal('fetch', mockFetch(projectRoutes()))
    const store = useSearchStore()
    await store.search('بازسازی سرویس بهداشتی')
    expect(store.isProjectIntent).toBe(true)

    vi.stubGlobal('fetch', mockFetch({ fail: ['route'] }))
    expect(await store.search('ماشین لباسشویی')).toBe(false)
    expect(store.intent).toBeNull()
    expect(store.results).toBeNull()
    expect(store.isProjectIntent).toBe(false)
  })

  it('3. a successful second project replaces the first', async () => {
    const store = useSearchStore()
    vi.stubGlobal('fetch', mockFetch(projectRoutes()))
    await store.search('بازسازی سرویس بهداشتی')
    const first = store.intent

    const second = { ...PROJECT_INTENT, room: 'اتاق خواب', goal: 'تغییر دکوراسیون' }
    vi.stubGlobal('fetch', mockFetch(projectRoutes(second)))
    expect(await store.search('اتاق خوابم رو تغییر دکوراسیون بدم')).toBe(true)

    expect(store.intent?.room).toBe('اتاق خواب')
    expect(store.intent).not.toBe(first)
    expect(store.submittedQuery).toBe('اتاق خوابم رو تغییر دکوراسیون بدم')
  })

  it('4. a slow earlier search cannot overwrite a newer one', async () => {
    // The first interpretation resolves only after the second has finished, so a
    // naive implementation writes the stale answer last and wins.
    const first = new Promise<string>((resolve) => setTimeout(() => resolve(JSON.stringify(PROJECT_INTENT)), 40))
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/search/route')) {
        return jsonResponse({ route: 'llm', is_product: false, explained: [], unexplained: [], reason: 'x' })
      }
      if (url.includes('/search/interpret')) {
        const body = url.includes('کند') ? await first : JSON.stringify(PROJECT_INTENT)
        return jsonResponse(JSON.parse(body))
      }
      if (url.includes('/products/search')) return jsonResponse(searchResponse(TWO_PRODUCTS))
      return jsonResponse({})
    })
    vi.stubGlobal('fetch', fetchMock)

    const store = useSearchStore()
    const slow = store.search('یک پروژهٔ کند')
    const fast = store.search('بازسازی سرویس بهداشتی')
    await Promise.all([slow, fast])
    await first

    expect(store.submittedQuery).toBe('بازسازی سرویس بهداشتی')
    expect(store.intent?.room).toBe('سرویس بهداشتی')
  })

  it('5. a first search that fails leaves no result at all', async () => {
    vi.stubGlobal('fetch', mockFetch({ fail: ['route'] }))
    const store = useSearchStore()
    expect(await store.search('بازسازی سرویس بهداشتی')).toBe(false)
    expect(store.results).toBeNull()
    expect(store.intent).toBeNull()
    expect(store.error).toBeTruthy()
  })

  it('6. a filter re-run still applies, because it is the same query', async () => {
    vi.stubGlobal('fetch', mockFetch(projectRoutes()))
    const store = useSearchStore()
    await store.search('بازسازی سرویس بهداشتی')
    // `applyFilters` re-runs with `interpret: false`; the same query must keep
    // its interpretation rather than being invalidated as a new submission.
    vi.stubGlobal('fetch', mockFetch({ fail: ['route'] }))
    await store.applyFilters({ category: 'toilet' })
    expect(store.intent).not.toBeNull()
    expect(store.submittedQuery).toBe('بازسازی سرویس بهداشتی')
  })

  it('7. a too-short query ends a search that is still running', async () => {
    /**
     * The same bug on the branch that never fetches.
     *
     * The short-query path returns before the request, so it left `loading` true.
     * The search it replaced is gated out of its own `finally` by the sequence
     * guard, so nothing would clear the spinner and the page would wait forever
     * for a request that was abandoned.
     */
    let release!: () => void
    const blocked = new Promise<void>((resolve) => (release = resolve))
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).includes('/search/route')) await blocked
        return jsonResponse({
          route: { route: 'llm', is_product: false, explained: [], unexplained: [], reason: 'unexplained_words' },
        })
      }),
    )
    const store = useSearchStore()
    const first = store.search('بازسازی سرویس بهداشتی')
    expect(store.loading).toBe(true)
    // the user gives up and clears the box
    expect(await store.search('ا')).toBe(false)
    expect(store.loading).toBe(false)
    expect(store.results).toBeNull()
    expect(store.intent).toBeNull()
    expect(store.isProjectIntent).toBe(false)
    release()
    expect(await first).toBe(false)
    expect(store.loading).toBe(false)
  })

  it('8. a failed search does not touch the selection list', async () => {
    /**
     * Clearing a search must not empty the basket.
     *
     * Results are what the page is showing right now; a selection is what the
     * user already decided to buy. They are separate stores, and the search store
     * does not import the selection store at all — this pins that separation, so
     * a future "just clear it here" reaches for the wrong one and fails.
     */
    const { useSelectionStore } = await import('@/stores/selectionStore')
    const selection = useSelectionStore()
    selection.list = {
      id: 'b1',
      kind: 'product',
      items: [{ product_id: 'p1', quantity: 2 }],
      total: 1000,
      items_count: 1,
    } as never
    const before = JSON.stringify(selection.$state)

    vi.stubGlobal('fetch', mockFetch({ fail: ['route'] }))
    const store = useSearchStore()
    expect(await store.search('بازسازی سرویس بهداشتی')).toBe(false)

    expect(store.results).toBeNull()
    expect(JSON.stringify(selection.$state)).toBe(before)
  })
})
