/**
 * The catalogue store's job: fetch the filter options from the backend, and
 * report loading / ready / broken / empty without ever touching the catalogue
 * file itself.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useCatalogStore } from '@/stores/catalogStore'
import type { Facets } from '@/types/api'

const FACETS: Facets = {
  categories: [{ value: 'bathroom', label: 'سرویس بهداشتی', count: 12 }],
  brands: [
    { value: 'کاسا', label: 'کاسا', count: 3 },
    { value: 'قهرمان', label: 'قهرمان', count: 2 },
  ],
  subcategories: [
    { value: 'sink-faucet', label: 'شیر روشویی', count: 8 },
    { value: 'toilet', label: 'توالت', count: 4 },
  ],
}

function serveFacets(body: unknown, status = 200) {
  return vi.fn(
    async (_input: RequestInfo | URL) =>
      new Response(typeof body === 'string' ? body : JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      }),
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
})

describe('catalogStore', () => {
  it('starts idle and loading', () => {
    const store = useCatalogStore()
    expect(store.status).toBe('idle')
    expect(store.isLoading).toBe(true)
    expect(store.isReady).toBe(false)
    expect(store.subcategoryOptions).toEqual([])
  })

  it('loads the filter options from the API', async () => {
    vi.stubGlobal('fetch', serveFacets(FACETS))
    const store = useCatalogStore()
    await store.load()

    expect(store.isReady).toBe(true)
    expect(store.subcategoryOptions.map((f) => f.value)).toEqual(['sink-faucet', 'toilet'])
    expect(store.brandOptions).toHaveLength(2)
    expect(store.categoryOptions).toHaveLength(1)
    // and the request went to the API, not to a file
    expect(String((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0])).toContain(
      '/products/facets',
    )
  })

  it('caches the options and only refetches when forced', async () => {
    const fetchMock = serveFacets(FACETS)
    vi.stubGlobal('fetch', fetchMock)
    const store = useCatalogStore()

    await store.load()
    await store.load()
    expect(fetchMock).toHaveBeenCalledTimes(1)

    await store.load({ force: true })
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('reports a failed request instead of showing empty filters as real', async () => {
    vi.stubGlobal('fetch', serveFacets({ detail: 'در دسترس نیست' }, 503))
    const store = useCatalogStore()
    await store.load()

    expect(store.isBroken).toBe(true)
    expect(store.error).toBeTruthy()
    expect(store.subcategoryOptions).toEqual([])
    expect(store.brandOptions).toEqual([])
  })

  it('reports an empty catalogue, which is different from a broken one', async () => {
    vi.stubGlobal('fetch', serveFacets({ categories: [], brands: [], subcategories: [] }))
    const store = useCatalogStore()
    await store.load()

    expect(store.isReady).toBe(true)
    expect(store.isBroken).toBe(false)
    expect(store.isEmpty).toBe(true)
  })

  it('never reads the catalogue file', async () => {
    const fetchMock = serveFacets(FACETS)
    vi.stubGlobal('fetch', fetchMock)
    const store = useCatalogStore()
    await store.load()

    for (const call of fetchMock.mock.calls) {
      expect(String(call[0])).not.toContain('products.json')
    }
  })
})
