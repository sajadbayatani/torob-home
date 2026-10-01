import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { searchApi, projectsApi, basketsApi, productsApi } = vi.hoisted(() => ({
  // `route` is the deterministic first step: it answers whether the catalogue can
  // place the query on its own. A test that wants a product query to cost no
  // inference sets it to product; the default here is "unsure", so the store asks
  // the interpreter, which is what these view tests are about.
  searchApi: { route: vi.fn(), interpret: vi.fn() },
  projectsApi: { analyze: vi.fn(), detail: vi.fn(), reanalyze: vi.fn(), templates: vi.fn() },
  basketsApi: {
    create: vi.fn(),
    get: vi.fn(),
    addItem: vi.fn(),
    updateItem: vi.fn(),
    removeItem: vi.fn(),
    optimize: vi.fn(),
  },
  productsApi: { search: vi.fn(), detail: vi.fn(), similar: vi.fn(), categories: vi.fn() },
}))

const { routerMock, routeMock } = vi.hoisted(() => ({
  routerMock: { push: vi.fn(), replace: vi.fn() },
  routeMock: { query: {} as Record<string, string> },
}))

vi.mock('@/api/search', () => ({ searchApi }))
vi.mock('@/api/projects', () => ({ projectsApi }))
vi.mock('@/api/baskets', () => ({ basketsApi }))
vi.mock('@/api/products', () => ({ productsApi }))
vi.mock('vue-router', () => ({
  useRouter: () => routerMock,
  useRoute: () => routeMock,
}))

import BasketView from '@/views/SelectionView.vue'
import { useSearchStore } from '@/stores/searchStore'
import HomeView from '@/views/HomeView.vue'
import SearchView from '@/views/SearchView.vue'
import type { Basket, InterpretedIntent, ProductSearchResponse } from '@/types/api'

const CATEGORY = {
  id: 'c1',
  slug: 'bathroom.in_wall_faucet',
  name: 'شیر توکار',
  domain: 'bathroom' as const,
  kind: 'fixture' as const,
  description_fa: null,
  product_count: 4,
}

const PRODUCT = {
  id: 'p1',
  slug: 'faucet',
  name: 'شیر توکار مدل استاندارد کاسا',
  subtitle: 'نصب توکار',
  brand: { id: 'b1', slug: 'kasa', name: 'کاسا', name_en: 'Kasa', country: 'ایران' },
  category: CATEGORY,
  domain: 'bathroom' as const,
  subcategory: 'sink-faucet',
  model: null,
  image_url: 'https://image.torob.com/test.jpg',
  source_url: 'https://torob.com/p/test',
  quality: 'medium' as const,
  quality_fa: 'متوسط',
  style: 'modern',
  unit: 'عدد',
  rating: null,
  warranty_months: 24,
  origin_country: 'ایران',
  attributes: [{ key: 'install', label: 'نوع نصب', value: 'توکار داخل دیوار', value_num: null, unit: null }],
  offers: [
    {
      id: 'o1',
      seller: { id: 's1', slug: 's1', name: 'ساختمان‌یار (دمو)', city: 'تهران', is_demo: true },
      price: 5900000,
      original_price: null,
      availability: 'in_stock' as const,
      available: true,
      stock_count: 3,
      delivery_days: 1,
      warranty_months: 24,
      url: null,
      price_updated_at: '2026-03-01T09:00:00Z',
    },
    {
      id: 'o2',
      seller: { id: 's2', slug: 's2', name: 'پارس سانوبار (دمو)', city: 'تهران', is_demo: true },
      price: 6254000,
      original_price: null,
      availability: 'preorder' as const,
      available: true,
      stock_count: 0,
      delivery_days: 2,
      warranty_months: 18,
      url: null,
      price_updated_at: '2026-03-01T09:00:00Z',
    },
  ],
  offers_count: 2,
  min_price: 5900000,
  max_price: 6254000,
  available_offers_count: 2,
  is_demo: true,
  match_score: 5,
}

const SEARCH_RESPONSE: ProductSearchResponse = {
  query: 'شیر توکار برند X',
  total: 1,
  limit: 20,
  offset: 0,
  detected_category: 'bathroom.in_wall_faucet',
  detected_category_name: 'شیر توکار',
  detected_domain: 'bathroom',
  intent: 'PRODUCT_SEARCH',
  items: [{ product: PRODUCT, matched_terms: ['شیر', 'توکار'], reasons: [] }],
  facets: { categories: [], brands: [], subcategories: [] },
  explanations: ['دستهٔ محصول تشخیص داده شد: شیر توکار.', 'برند «X» در کاتالوگ ثبت نشده است.'],
  suggestions: [],
}

const PRODUCT_INTENT = {
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
    category_slug: 'bathroom.in_wall_faucet',
    category_name: 'شیر توکار',
    domain: 'bathroom',
    quality: null,
    style: null,
  },
  requirements: { area_m2: null, quality: null, style: null, budget: null, priorities: [], extra: {} },
  constraint_kind: 'NONE',
  confidence: 0.55,
  interpreter: 'rules',
  explanations: ['دستهٔ محصول تشخیص داده شد: شیر توکار.'],
  matched_subcategories: ['sink-faucet'],
  missing_categories: [],
  room: null,
  goal: null,
} satisfies InterpretedIntent

const BASKET: Basket = {
  id: 'b1',
  kind: 'product',
  title: 'سبد من',
  currency: 'IRT',
  items: [
    {
      id: 'i1',
      product: PRODUCT,
      offer: PRODUCT.offers[0],
      unit_price: 5900000,
      line_total: 5900000,
      role: 'item',
      origin: 'search',
      is_locked: false,
      reason: null,
      replaced_item_id: null,
      is_best_price: true,
      best_price: 5900000,
      alternative_count: 2,
      alternative_min_price: 3450000,
    },
  ],
  items_count: 1,
  total: 5900000,
  project_id: null,
  target_budget: 55000000,
  budget_gap: -49100000,
  within_budget: true,
  intent: null,
  notes: null,
  created_at: '2026-03-01T09:00:00Z',
  updated_at: '2026-03-01T09:00:00Z',
}

const RouterLinkStub = {
  props: ['to'],
  template: '<a><slot /></a>',
}
const globalMountOptions = { global: { stubs: { RouterLink: RouterLinkStub, RouterView: true } } }

describe('views (integration with mocked API layer)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    routeMock.query = {}
    searchApi.route.mockResolvedValue({
      route: 'llm',
      is_product: false,
      explained: [],
      unexplained: ['—'],
      reason: 'unexplained_words',
    })
    searchApi.interpret.mockImplementation(async (query: string) =>
      /بودجه/.test(query)
        ? { ...PRODUCT_INTENT, intent: 'UNKNOWN', constraint_kind: 'BUDGET', requirements: {
            area_m2: null, quality: null, style: null, budget: 55000000, priorities: [], extra: {},
          } }
        : PRODUCT_INTENT,
    )
    productsApi.search.mockResolvedValue(SEARCH_RESPONSE)
    basketsApi.get.mockResolvedValue(BASKET)
    basketsApi.create.mockResolvedValue(BASKET)
    basketsApi.addItem.mockResolvedValue({} as never)
  })

  it('home: a failed second search does not keep the first project on screen', async () => {
    const wrapper = mount(HomeView, globalMountOptions)
    searchApi.interpret.mockResolvedValue({
      ...PRODUCT_INTENT,
      intent: 'NEED_SEARCH',
      product_query: null,
    })
    projectsApi.analyze.mockResolvedValue({
      analysis: { id: 'a1', estimated_total: 73910000, domain: 'bathroom', project_type: 'renovation' },
      basket: BASKET,
    })

    // The first search succeeds and its project is previewed.
    await wrapper.find('[data-test="search-input"]').setValue('میخوام سرویس بهداشتی رو بازسازی کنم')
    await wrapper.find('[data-test="search-bar"]').trigger('submit')
    await flushPromises()
    expect(wrapper.find('[data-test="home-preview"]').exists()).toBe(true)

    // The second search's interpretation fails.
    searchApi.interpret.mockRejectedValue(new Error('پاسخ مدل معتبر نبود'))
    await wrapper.find('[data-test="search-input"]').setValue('بازسازی سرویس بهداشتی ۱۲ متری')
    await wrapper.find('[data-test="search-bar"]').trigger('submit')
    await flushPromises()

    // The first project's preview is gone, and no analysis is requested for the
    // new query from the old query's interpretation.
    expect(wrapper.find('[data-test="home-preview"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('73910000')
    expect(projectsApi.analyze).toHaveBeenCalledTimes(1)
    expect(useSearchStore().submittedQuery).toBe('بازسازی سرویس بهداشتی ۱۲ متری')
  })

  it('home: a product query routes to search, a need query opens the project', async () => {
    const wrapper = mount(HomeView, globalMountOptions)
    expect(wrapper.text()).toContain('برای خانه‌ات چی لازم داری؟')

    await wrapper.find('[data-test="search-input"]').setValue('شیر توکار برند X')
    await wrapper.find('[data-test="search-bar"]').trigger('submit')
    await flushPromises()
    expect(routerMock.push).toHaveBeenCalledWith({ name: 'search', query: { q: 'شیر توکار برند X' } })

    searchApi.interpret.mockResolvedValue({
      ...PRODUCT_INTENT,
      intent: 'NEED_SEARCH',
      product_query: null,
    })
    projectsApi.analyze.mockResolvedValue({
      analysis: { id: 'a1', estimated_total: 73910000, domain: 'bathroom', project_type: 'renovation' },
      basket: BASKET,
    })
    // A *different* sentence. The store reads each sentence once, so asking
    // about the same words again would legitimately keep the first answer.
    await wrapper.find('[data-test="search-input"]').setValue('میخوام سرویس بهداشتی رو بازسازی کنم')
    await wrapper.find('[data-test="search-bar"]').trigger('submit')
    await flushPromises()
    expect(routerMock.push).toHaveBeenCalledWith({ name: 'project', params: { id: 'a1' } })
  })

  it('search: renders normalised results, seller rows and the intent explanations', async () => {
    routeMock.query = { q: 'شیر توکار برند X' }
    const wrapper = mount(SearchView, globalMountOptions)
    await flushPromises()

    expect(productsApi.search).toHaveBeenCalled()
    const text = wrapper.text()
    expect(text).toContain(PRODUCT.name)
    expect(text).toContain('۱ نتیجه')
    expect(text).toContain('۵٬۹۰۰٬۰۰۰')
    expect(text).toContain('ساختمان‌یار (دمو)')
    expect(text).toContain('۶٬۲۵۴٬۰۰۰')
    // results come before the prompt to build a selection list
    expect(wrapper.text().indexOf('کمترین قیمت')).toBeLessThan(
      wrapper.text().indexOf('ساخت فهرست پیشنهادی'),
    )
    // the explanations panel is always shown, including the honest brand note
    expect(text).toContain('برند «X» در کاتالوگ ثبت نشده است')
    expect(text).toContain('شیر توکار')
  })

  it('search: says plainly what is missing and what to do next', async () => {
    routeMock.query = { q: 'کیهان‌نماز' }
    productsApi.search.mockResolvedValue({ ...SEARCH_RESPONSE, total: 0, items: [] })
    const wrapper = mount(SearchView, globalMountOptions)
    await flushPromises()

    const empty = wrapper.find('[data-test="empty-state"]')
    expect(empty.exists()).toBe(true)
    expect(empty.text()).toContain('نتیجه‌ای پیدا نشد')
    expect(empty.text()).toContain('در کاتالوگ محصولی با این مشخصات ثبت نشده است')
    expect(wrapper.findAll('[data-test="product-card"]')).toHaveLength(0)
  })

  it('search: routes a need query away from product results', async () => {
    routeMock.query = { q: 'بازسازی سرویس بهداشتی ۱۲ متری' }
    searchApi.interpret.mockResolvedValue({
      ...PRODUCT_INTENT,
      intent: 'NEED_SEARCH',
      product_query: null,
    })
    // The view carries a need query straight into the project flow, so the
    // analysis is called. Unmocked it resolved to `undefined` and the view threw
    // on `result.basket` as an unhandled rejection that no assertion saw.
    projectsApi.analyze.mockResolvedValue({
      analysis: { id: 'a1', estimated_total: 73910000, domain: 'bathroom', project_type: 'renovation' },
      basket: BASKET,
    })
    const wrapper = mount(SearchView, globalMountOptions)
    await flushPromises()

    expect(wrapper.find('[data-test="need-intent-hint"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('این یک نیاز است، نه جست‌وجوی یک محصول')
  })

  it('basket: renders the server total and accepts a budget sentence', async () => {
    const wrapper = mount(BasketView, { props: { id: 'b1' }, ...globalMountOptions })
    await flushPromises()

    expect(basketsApi.get).toHaveBeenCalledWith('b1')
    // the basket reads as a manifest, and the total is server-computed
    expect(wrapper.find('[data-test="basket-manifest"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('برآورد کل (محاسبهٔ سرور)')
    expect(wrapper.text()).toContain('۵٫۹ میلیون تومان')
    expect(wrapper.findAll('[data-test="amount-input"]').length).toBeGreaterThan(0)
    expect(wrapper.find('[data-test="basket-items"]').exists()).toBe(true)

    basketsApi.optimize.mockResolvedValue({
      original_total: 73910000,
      target_budget: 55000000,
      optimized_total: 53020000,
      saved: 20890000,
      within_budget: true,
      unfilled_gap: 0,
      changes: [],
      applied: true,
      basket: BASKET,
      explanation: 'هزینه کاهش یافت.',
      trade_offs: [],
    })

    await wrapper.find('[data-test="amount-input"]').setValue('بودجه من ۵۵ میلیون است')
    await wrapper.find('[data-test="optimize"]').trigger('click')
    await flushPromises()

    // the sentence is parsed in the UI (the user has already seen the amount in
    // words), so the request carries an explicit Toman target
    expect(basketsApi.optimize).toHaveBeenCalledWith('b1', {
      target_budget: 55000000,
      apply: true,
    })
    expect(wrapper.find('[data-test="optimization-result"]').text()).toContain('هزینه کاهش یافت')
  })

  it('basket: shows the understood amount in words and falls back to the sentence API', async () => {
    const wrapper = mount(BasketView, { props: { id: 'b1' }, ...globalMountOptions })
    await flushPromises()

    const field = wrapper.find('[data-test="amount-input"]')
    await field.setValue('۵۵ میلیون')
    await flushPromises()
    // grouping + the amount spelled out before the user commits
    expect(wrapper.find('[data-test="amount-words"]').text()).toContain('پنجاه و پنج میلیون تومان')

    // text the parser cannot read is handed to the API as a sentence
    await field.setValue('هرچی که می‌توانم')
    await flushPromises()
    expect(wrapper.find('[data-test="amount-error"]').exists()).toBe(true)

    await field.setValue('بودجه‌ام خیلی کمه')
    await wrapper.find('[data-test="optimize"]').trigger('click')
    await flushPromises()
    expect(basketsApi.optimize).toHaveBeenCalledWith('b1', {
      query: 'بودجه‌ام خیلی کمه',
      apply: true,
    })
  })

  // ---------------------------------------------------------------------- //
  // the thinking states are tied to the request, not to a timer
  // ---------------------------------------------------------------------- //
  describe('thinking states in the search box', () => {
  it('are absent while nothing is being searched', () => {
    const wrapper = mount(HomeView, globalMountOptions)
    expect(wrapper.find('[data-test="thinking-states"]').exists()).toBe(false)
  })

  it('appear while a search is genuinely in flight and go when it ends', async () => {
    const wrapper = mount(HomeView, globalMountOptions)

    // hold the interpretation open, so the search is provably still running
    let release!: () => void
    const held = new Promise<void>((resolve) => (release = resolve))
    searchApi.interpret.mockImplementation(async () => {
      await held
      return { ...PRODUCT_INTENT, intent: 'NEED_SEARCH', product_query: null }
    })

    await wrapper.find('[data-test="search-input"]').setValue('بازسازی سرویس بهداشتی')
    await wrapper.find('[data-test="search-bar"]').trigger('submit')
    await flushPromises()

    const shown = wrapper.find('[data-test="thinking-states"]')
    expect(shown.exists()).toBe(true)
    expect(shown.text()).toContain('دارم')
    // a real phase, named in Persian, inside the live region
    expect(shown.attributes('role')).toBe('status')
    expect(shown.attributes('dir')).toBe('rtl')

    release()
    await flushPromises()
    expect(wrapper.find('[data-test="thinking-states"]').exists()).toBe(false)
  })

  it('name the phase the search is actually in', async () => {
    const wrapper = mount(HomeView, globalMountOptions)

    let release!: () => void
    const held = new Promise<void>((resolve) => (release = resolve))
    searchApi.interpret.mockImplementation(async () => {
      await held
      return { ...PRODUCT_INTENT, intent: 'NEED_SEARCH', product_query: null }
    })

    await wrapper.find('[data-test="search-input"]').setValue('بازسازی سرویس بهداشتی')
    await wrapper.find('[data-test="search-bar"]').trigger('submit')
    await flushPromises()

    // the deterministic route call has already returned and the model call is the
    // one still open, so this is the understanding sentence and nothing else
    expect(wrapper.get('[data-test="thinking-active"]').text()).toBe(
      'دارم نیتت رو متوجه می‌شم...',
    )

    release()
    await flushPromises()
  })

  it('shows the analysis sentence while the project request is in flight', async () => {
    /**
     * The regression this fixes.
     *
     * `/projects/analyze` is issued by the view, not by the store, so the store's
     * `loading` is already false while it runs. The status line used to read that
     * flag, so it went blank for the whole request — and the analysis message,
     * the one that names the longest part of a project, was the one thing a user
     * never saw.
     */
    const wrapper = mount(HomeView, globalMountOptions)

    let release!: () => void
    const held = new Promise<void>((resolve) => (release = resolve))
    searchApi.interpret.mockResolvedValue({
      ...PRODUCT_INTENT, intent: 'NEED_SEARCH', product_query: null,
    })
    projectsApi.analyze.mockImplementation(async () => {
      await held
      return {
        analysis: { id: 'a1', estimated_total: 73910000, domain: 'bathroom', project_type: 'renovation' },
        basket: BASKET,
      }
    })

    await wrapper.find('[data-test="search-input"]').setValue('میخوام سرویس بهداشتی رو بازسازی کنم')
    await wrapper.find('[data-test="search-bar"]').trigger('submit')
    await flushPromises()

    expect(projectsApi.analyze).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-test="thinking-states"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="thinking-active"]').text()).toBe(
      'دارم نیازت رو تحلیل می‌کنم...',
    )

    release()
    await flushPromises()
    expect(wrapper.find('[data-test="thinking-states"]').exists()).toBe(false)
  })

  it('never shows the project message during a plain product search', async () => {
    const wrapper = mount(HomeView, globalMountOptions)

    let release!: () => void
    const held = new Promise<void>((resolve) => (release = resolve))
    productsApi.search.mockImplementation(async () => {
      await held
      return SEARCH_RESPONSE
    })
    searchApi.route.mockResolvedValue({
      route: 'catalog', is_product: true, explained: ['یخچال'], unexplained: [], reason: 'all_words_explained',
    })

    await wrapper.find('[data-test="search-input"]').setValue('یخچال دوو')
    await wrapper.find('[data-test="search-bar"]').trigger('submit')
    await flushPromises()

    const text = wrapper.get('[data-test="thinking-active"]').text()
    expect(text).toBe('دارم محصولات مناسب رو پیدا می‌کنم...')
    expect(text).not.toContain('نیازت')
    expect(projectsApi.analyze).not.toHaveBeenCalled()

    release()
    await flushPromises()
  })

  it('do not linger after a failed search', async () => {
    const wrapper = mount(HomeView, globalMountOptions)
    searchApi.interpret.mockRejectedValue(new Error('پاسخ مدل معتبر نبود'))

    await wrapper.find('[data-test="search-input"]').setValue('بازسازی سرویس بهداشتی')
    await wrapper.find('[data-test="search-bar"]').trigger('submit')
    await flushPromises()

    // the existing error UI owns the failure; the status line must not still be
    // claiming work is happening
    expect(wrapper.find('[data-test="thinking-states"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('درخواست انجام نشد')
  })

  it('send no request of their own', async () => {
    const wrapper = mount(HomeView, globalMountOptions)
    const before = searchApi.interpret.mock.calls.length

    let release!: () => void
    const held = new Promise<void>((resolve) => (release = resolve))
    searchApi.interpret.mockImplementation(async () => {
      await held
      return { ...PRODUCT_INTENT, intent: 'NEED_SEARCH', product_query: null }
    })
    await wrapper.find('[data-test="search-input"]').setValue('بازسازی سرویس بهداشتی')
    await wrapper.find('[data-test="search-bar"]').trigger('submit')
    await flushPromises()

    expect(searchApi.interpret.mock.calls.length).toBe(before + 1)
    release()
    await flushPromises()
  })
})

})
