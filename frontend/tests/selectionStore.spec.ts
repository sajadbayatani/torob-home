import { describe, expect, it, vi } from 'vitest'

import { useSelectionStore } from '@/stores/selectionStore'
import type { Basket, OptimizationResult } from '@/types/api'

const PRODUCT = {
  id: 'p1',
  slug: 'faucet',
  name: 'شیر توکار کاسا',
  subtitle: null,
  brand: null,
  category: {
    id: 'c1',
    slug: 'bathroom.in_wall_faucet',
    name: 'شیر توکار',
    domain: 'bathroom' as const,
    kind: 'fixture',
    description_fa: null,
    product_count: 4,
  },
  domain: 'bathroom' as const,
  subcategory: 'sink-faucet',
  model: null,
  image_url: 'https://image.torob.com/test.jpg',
  source_url: 'https://torob.com/p/test',
  quality: 'medium' as const,
  quality_fa: 'متوسط',
  style: null,
  unit: 'عدد',
  rating: null,
  warranty_months: 24,
  origin_country: null,
  attributes: [],
  offers: [],
  offers_count: 3,
  min_price: 5900000,
  max_price: 6667000,
  available_offers_count: 2,
  is_demo: true,
  match_score: null,
}

const OFFER = {
  id: 'o1',
  seller: { id: 's1', slug: 'seller', name: 'ساختمان‌یار (دمو)', city: 'تهران', is_demo: true },
  price: 5900000,
  original_price: null,
  availability: 'in_stock' as const,
  available: true,
  stock_count: 5,
  delivery_days: 1,
  warranty_months: 24,
  url: null,
  price_updated_at: '2026-03-01T09:00:00Z',
}

function makeBasket(total: number, isLocked = false): Basket {
  return {
    id: 'b1',
    kind: 'product',
    title: 'سبد من',
    currency: 'IRT',
    items: [
      {
        id: 'i1',
        product: PRODUCT,
        offer: { ...OFFER, price: 5900000 },
        unit_price: 5900000,
        line_total: 5900000,
        role: 'item',
        origin: 'search',
        is_locked: isLocked,
        reason: null,
        replaced_item_id: null,
        is_best_price: true,
        best_price: 5900000,
        alternative_count: 2,
        alternative_min_price: 3450000,
      },
    ],
    items_count: 1,
    total,
    project_id: null,
    target_budget: null,
    budget_gap: null,
    within_budget: null,
    intent: null,
    notes: null,
    created_at: '2026-03-01T09:00:00Z',
    updated_at: '2026-03-01T09:00:00Z',
  }
}

const OPTIMIZATION: OptimizationResult = {
  original_total: 73910000,
  target_budget: 55000000,
  optimized_total: 53020000,
  saved: 20890000,
  within_budget: true,
  unfilled_gap: 0,
  changes: [
    {
      item: 'tiles',
      item_id: 'i2',
      role: 'tiles',
      from_product: 'کاشی متوسط',
      from_product_id: 'p2',
      to_product: 'کاشی اقتصادی',
      to_product_id: 'p3',
      from_price: 690000,
      to_price: 430000,
      saving: 10140000,
      reason: '«کاشی اقتصادی» جایگزین «کاشی متوسط» شد و ۱۰٬۱۴۰٬۰۰۰ تومان کاهش هزینه ایجاد می‌کند.',
      quality_from: 'متوسط',
      quality_to: 'اقتصادی',
    },
  ],
  applied: true,
  basket: makeBasket(53020000),
  explanation: 'با ۱ تغییر، هزینه کاهش یافت.',
  trade_offs: ['کیفیت «متوسط» به «اقتصادی» کاهش یافت.'],
}

function stubFetch(handlers: Record<string, { status?: number; body: unknown }>) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    const key = Object.keys(handlers).find((k) => url.includes(k))
    const handler = key ? handlers[key] : { body: {} }
    if (handler.status === 204) return new Response(null, { status: 204 })
    return new Response(JSON.stringify(handler.body), {
      status: handler.status ?? 200,
      headers: { 'Content-Type': 'application/json' },
    })
  })
}

describe('selectionStore', () => {
  it('mirrors the server total instead of computing it in the browser', async () => {
    vi.stubGlobal('fetch', stubFetch({ '/baskets/b1': { body: makeBasket(59000000) } }))
    const store = useSelectionStore()
    await store.load('b1')

    expect(store.total).toBe(59000000)
    expect(store.itemsCount).toBe(1)
    expect(store.list?.currency).toBe('IRT')
  })

  it('creates a basket on first add and refetches it', async () => {
    const calls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        calls.push(`${init?.method ?? 'GET'} ${url}`)
        if (init?.method === 'POST' && url.endsWith('/baskets')) {
          return new Response(JSON.stringify(makeBasket(5900000)), { status: 201 })
        }
        return new Response(JSON.stringify(makeBasket(5900000)), { status: 200 })
      }),
    )

    const store = useSelectionStore()
    await store.addItem({ product_id: 'p1' })

    expect(calls[0]).toContain('POST')
    expect(calls[0]).toMatch(/\/baskets$/)
    expect(calls[1]).toContain('/items')
    expect(calls[2]).toMatch(/GET .*\/baskets\/b1$/)
    expect(store.total).toBe(5900000)
  })

  it('exposes the optimisation result returned by the server', async () => {
    vi.stubGlobal(
      'fetch',
      stubFetch({ '/optimize': { body: OPTIMIZATION }, '/baskets/b1': { body: makeBasket(73910000) } }),
    )
    const store = useSelectionStore()
    await store.load('b1')
    const result = await store.optimize({ target_budget: 55000000, apply: true })

    expect(result?.optimized_total).toBe(53020000)
    expect(result?.optimized_total).toBeLessThan(result!.original_total)
    expect(store.lastOptimization?.changes[0].reason).toContain('کاهش هزینه')
    expect(store.total).toBe(53020000)
  })

  it('empties the whole basket through the API', async () => {
    const calls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        calls.push(`${init?.method ?? 'GET'} ${String(input)}`)
        if (init?.method === 'DELETE') return new Response(null, { status: 204 })
        return new Response(JSON.stringify(makeBasket(5900000)), { status: 200 })
      }),
    )

    const store = useSelectionStore()
    await store.load('b1')
    expect(store.itemsCount).toBe(1)

    expect(await store.clearList()).toBe(true)
    expect(calls.some((c) => c.startsWith('DELETE') && c.includes('/baskets/b1'))).toBe(true)
  })

  it('leaves no stale basket behind after clearing', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) =>
        init?.method === 'DELETE'
          ? new Response(null, { status: 204 })
          : new Response(JSON.stringify(makeBasket(5900000)), { status: 200 }),
      ),
    )

    const store = useSelectionStore()
    await store.load('b1')
    await store.clearList()

    // a reload must not resurrect the basket that was just emptied
    expect(store.list).toBeNull()
    expect(store.listId).toBeNull()
    expect(store.itemsCount).toBe(0)
    expect(store.total).toBe(0)
  })

  it('keeps the basket when clearing fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) =>
        init?.method === 'DELETE'
          ? new Response(JSON.stringify({ detail: 'سبد خرید پیدا نشد.' }), { status: 404 })
          : new Response(JSON.stringify(makeBasket(5900000)), { status: 200 }),
      ),
    )

    const store = useSelectionStore()
    await store.load('b1')
    expect(await store.clearList()).toBe(false)

    // the error is surfaced, not swallowed
    expect(store.error).toBeTruthy()
  })

  it('clears a stale basket id when the basket is gone', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ detail: 'سبد خرید پیدا نشد.' }), { status: 404 })),
    )
    const store = useSelectionStore()
    store.listId = 'missing'
    await store.load()

    expect(store.list).toBeNull()
    expect(store.listId).toBeNull()
    expect(localStorage.getItem('home-procurement.basket-id')).toBeNull()
  })

  it('updates an item by asking the server, and adopts the server numbers', async () => {
    /**
     * An update now means "which offer, and is it locked" — there is no count to
     * change, so there is no quantity to send and none to read back.

     * The store still does not compute a total of its own: it takes the number the
     * server reports, which is what the test this replaced was really checking.
     */
    const sent: string[] = []
    let bodies = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        sent.push(`${init?.method ?? 'GET'} ${String(input)}`)
        bodies += 1
        return new Response(JSON.stringify(makeBasket(5900000 * bodies)), { status: 200 })
      }),
    )
    const store = useSelectionStore()
    await store.load('b1')
    await store.setLocked('i1', true)

    expect(sent.some((call) => call.startsWith('PATCH') && call.includes('/items/i1'))).toBe(true)
    // the total is the server's, never a client-side sum
    expect(store.total).toBe(5900000 * bodies)
  })

  it('surfaces an error when the update fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/items/')) {
          return new Response(JSON.stringify({ detail: 'این قلم در فهرست انتخاب‌ها پیدا نشد.' }), { status: 404 })
        }
        return new Response(JSON.stringify(makeBasket(5900000)), { status: 200 })
      }),
    )
    const store = useSelectionStore()
    await store.load('b1')
    await expect(store.setLocked('missing', true)).rejects.toThrow()
  })
})
