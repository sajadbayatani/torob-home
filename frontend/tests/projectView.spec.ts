import { RouterLinkStub, flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { projectsApi } = vi.hoisted(() => ({
  projectsApi: {
    detail: vi.fn(),
    reanalyze: vi.fn(),
    analyze: vi.fn(),
    templates: vi.fn(),
    complementary: vi.fn(),
    optimize: vi.fn(),
  },
}))

const { basketsApi } = vi.hoisted(() => ({
  basketsApi: {
    create: vi.fn(),
    get: vi.fn(),
    addItem: vi.fn(),
    updateItem: vi.fn(),
    removeItem: vi.fn(),
    optimize: vi.fn(),
  },
}))

const { routerMock } = vi.hoisted(() => ({
  routerMock: { push: vi.fn(), replace: vi.fn() },
}))

vi.mock('@/api/projects', () => ({ projectsApi }))
vi.mock('@/api/baskets', () => ({ basketsApi }))
vi.mock('vue-router', () => ({
  useRouter: () => routerMock,
  useRoute: () => ({ query: {} }),
}))

import ProjectView from '@/views/ProjectView.vue'
import { toPersianDigits as toFaDigits } from '@/utils/format'
import type { Basket, OptimizationResult } from '@/types/api'

/** The fixed wording the backend sends for a category it does not carry. */
const NOT_IN_CATALOG =
  'ممکن است برای این پروژه موردنیاز باشد، اما در حال حاضر در کاتالوگ ما موجود نیست.'

const ANALYSIS = {
  id: 'a1',
  template_slug: 'bathroom_renovation',
  title: 'بازسازی سرویس بهداشتی ۱۲ متر مربع',
  domain: 'bathroom' as const,
  project_type: 'renovation' as const,
  area_m2: 12,
  quality: 'medium' as const,
  quality_fa: 'متوسط',
  style: null,
  budget: null,
  requirements: {},
  estimated_total: 73910000,
  confidence: 0.75,
  interpreter: 'rules',
  interpretation: {
    intent: 'NEED_SEARCH' as const,
    domain: 'bathroom' as const,
    project_type: 'renovation' as const,
    template_slug: 'bathroom_renovation',
    product_query: null,
    requirements: {
      area_m2: 12,
      quality: 'medium' as const,
      style: null,
      budget: null,
      priorities: [],
      extra: {},
    },
    constraint_kind: 'AREA' as const,
    confidence: 0.75,
    interpreter: 'rules',
    explanations: ['حوزهٔ خانه تشخیص داده شد: سرویس بهداشتی.'],
  },
  categories: [
    {
      role: 'tiles',
      label: 'کاشی و سرامیک',
      category: {
        id: 'c1',
        slug: 'bathroom.tiles',
        name: 'کاشی و سرامیک',
        domain: 'bathroom' as const,
        kind: 'surface' as const,
        description_fa: null,
        product_count: 4,
      },
      quantity: 39,
      unit: 'متر مربع',
      is_required: true,
      quality_min: 'low' as const,
      reason: 'برای کف و دیوار، حدود ۳٫۲ متر مربع به ازای هر متر مربع زمین نیاز است.',
      // the catalogue carries no tiles, so this one is reported as not available
      in_catalog: false,
      note: NOT_IN_CATALOG,
      // the need is real; only our ability to supply it is not
      project_need: true,
      catalog_match: false,
      unavailable_reason: 'not_stocked' as const,
    },
    {
      role: 'toilet',
      label: 'توالت',
      category: {
        id: 'c2',
        slug: 'bathroom.toilet',
        name: 'توالت فرنگی',
        domain: 'bathroom' as const,
        kind: 'fixture' as const,
        description_fa: null,
        product_count: 4,
      },
      quantity: 1,
      unit: 'عدد',
      is_required: true,
      quality_min: 'low' as const,
      reason: 'در بازسازی، توالت فرنگی معمولاً تعویض می‌شود.',
      in_catalog: true,
      note: null,
      project_need: true,
      catalog_match: true,
      unavailable_reason: null,
    },
  ],
  available_categories: [
    {
      id: 'toilet',
      slug: 'toilet',
      name: 'توالت',
      domain: 'bathroom' as const,
      kind: 'fixture' as const,
      description_fa: null,
      product_count: 2,
    },
  ],
  candidates: [
    {
      role: 'tiles',
      label: 'کاشی و سرامیک',
      quantity: 39,
      unit: 'متر مربع',
      product: {
        id: 'p1',
        slug: 'tile',
        name: 'کاشی سرامیکی مدل استاندارد',
        subtitle: null,
        brand: null,
        category: {
          id: 'c1',
          slug: 'bathroom.tiles',
          name: 'کاشی و سرامیک',
          domain: 'bathroom' as const,
          kind: 'surface' as const,
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
        unit: 'متر مربع',
        rating: null,
        warranty_months: 0,
        origin_country: null,
        attributes: [],
        offers: [],
        offers_count: 3,
        min_price: 690000,
        max_price: 780000,
        available_offers_count: 2,
        is_demo: true,
        match_score: null,
      },
      offer: {
        id: 'o1',
        seller: { id: 's1', slug: 's1', name: 'ساختمان‌یار (دمو)', city: 'تهران', is_demo: true },
        price: 690000,
        original_price: null,
        availability: 'in_stock' as const,
        available: true,
        stock_count: 5,
        delivery_days: 1,
        warranty_months: 12,
        url: null,
        price_updated_at: '2026-03-01T09:00:00Z',
      },
      unit_price: 690000,
      line_total: 26910000,
      seller_name: 'ساختمان‌یار (دمو)',
      reason: 'این گزینه با توجه به متراژ ۱۲ و سطح کیفیت متوسط انتخاب شد.',
      quality: 'medium' as const,
      quality_fa: 'متوسط',
    },
  ],
  missing_categories: [
    {
      role: 'tiles',
      label: 'کاشی و سرامیک',
      category: {
        id: 'c1',
        slug: 'bathroom.tiles',
        name: 'کاشی و سرامیک',
        domain: 'bathroom' as const,
        kind: 'surface' as const,
        description_fa: null,
        product_count: 0,
      },
      quantity: 39,
      unit: 'متر مربع',
      is_required: true,
      quality_min: 'low' as const,
      reason: 'برای کف و دیوار.',
      in_catalog: false,
      note: NOT_IN_CATALOG,
    },
  ],
  basket_id: 'b1',
  explanations: [
    'حوزهٔ خانه تشخیص داده شد: سرویس بهداشتی.',
    'متراژ و سطح کیفیت اعمال‌شده: ۱۲ متر مربع / متوسط.',
  ],
  created_at: '2026-03-01T09:00:00Z',
}

const BASKET: Basket = {
  id: 'b1',
  kind: 'project',
  title: ANALYSIS.title,
  currency: 'IRT',
  items: [],
  items_count: 2,
  total: 73910000,
  project_id: 'a1',
  target_budget: null,
  budget_gap: null,
  within_budget: null,
  intent: null,
  notes: null,
  created_at: '2026-03-01T09:00:00Z',
  updated_at: '2026-03-01T09:00:00Z',
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
      item_id: 'i1',
      role: 'tiles',
      from_product: 'کاشی متوسط',
      from_product_id: 'p1',
      to_product: 'کاشی اقتصادی',
      to_product_id: 'p2',
      from_price: 690000,
      to_price: 430000,
      saving: 10140000,
      reason: '«کاشی اقتصادی» جایگزین «کاشی متوسط» شد و کاهش هزینه ایجاد می‌کند.',
      quality_from: 'متوسط',
      quality_to: 'اقتصادی',
    },
  ],
  // a proposal, not yet carried out: this is the state right after optimising
  can_optimize: true,
  over_budget: true,
  applied: false,
  basket: BASKET,
  explanation: 'با ۱ تغییر، هزینه به ۵۳٬۰۲۰٬۰۰۰ تومان رسید.',
  trade_offs: ['کیفیت «متوسط» به «اقتصادی» کاهش یافت.'],
}

function mountView() {
  // RouterLinkStub renders its slot, so product names are assertable
  return mount(ProjectView, {
    props: { id: 'a1' },
    global: { stubs: { RouterLink: RouterLinkStub } },
  })
}

describe('ProjectView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    projectsApi.detail.mockResolvedValue(ANALYSIS)
    projectsApi.complementary.mockResolvedValue({
      items: [],
      llm_available: false,
      candidate_count: 4,
      note: 'کلید OpenRouter تنظیم نشده است، بنابراین پیشنهاد مکمل فقط بر پایهٔ جفت‌های خودِ کاتالوگ ساخته شده است.',
      discarded_ids: [],
    })
    projectsApi.optimize.mockResolvedValue({
      analysis: ANALYSIS,
      basket: BASKET,
      budget_status: { estimated_total: BASKET.total, target_budget: null, gap: null, within_budget: null },
      optimization: OPTIMIZATION,
    })
    basketsApi.get.mockResolvedValue(BASKET)
  })

  it('shows the interpreted project, the checklist and the estimate', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(projectsApi.detail).toHaveBeenCalledWith('a1')
    const text = wrapper.text()
    expect(text).toContain('پروژهٔ شما')
    expect(text).toContain('بازسازی سرویس بهداشتی')
    expect(text).toContain('نیازهای این پروژه')
    expect(text).toContain('کاشی و سرامیک')
    expect(text).toContain('توالت')
    // the quantity comes from the project rules, not from hardcoded UI text
    expect(text).toContain('۳۹')
    expect(text).toContain('برآورد هزینهٔ کل پروژه')
    expect(text).toContain('۷۳٫۹ میلیون تومان')
  })

  it('explains how the recommendation was made', async () => {
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.find('[data-test="explanation"]').text()).toContain('سرویس بهداشتی')
  })

  it('selects the whole project in one action', async () => {
    // the shared fixture is a single-candidate project; this one needs several
    const base = ANALYSIS.candidates[0]
    const candidates = ['sanitary', 'furniture', 'lighting'].map((role, index) => ({
      ...base,
      role,
      label: role,
      product: { ...base.product, id: `p${index + 2}`, name: role },
      offer: { ...base.offer, id: `o${index + 2}` },
    }))
    projectsApi.detail.mockResolvedValue({ ...ANALYSIS, candidates })

    const wrapper = mountView()
    await flushPromises()

    basketsApi.create.mockResolvedValue({ ...BASKET, kind: 'project', items: [] })
    basketsApi.addItem.mockResolvedValue(undefined)
    const getsBefore = basketsApi.get.mock.calls.length

    await wrapper.find('[data-test="add-all-candidates"]').trigger('click')
    await flushPromises()

    // every recommendation, each with the role and the reason that justified it
    expect(basketsApi.addItem).toHaveBeenCalledTimes(candidates.length)
    for (const candidate of candidates) {
      expect(basketsApi.addItem).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          product_id: candidate.product.id,
          offer_id: candidate.offer.id,
          role: candidate.role,
          reason: candidate.reason,
          origin: 'project',
        }),
      )
    }
    // the list is re-read once at the end, not once per recommendation
    expect(basketsApi.get).toHaveBeenCalledTimes(getsBefore + 1)
    expect(wrapper.text()).toContain(`${toFaDigits(candidates.length)} قلم`)
  })

  it('keeps the per-item buttons, and never selects anything on its own', async () => {
    const wrapper = mountView()
    await flushPromises()

    for (const candidate of ANALYSIS.candidates) {
      expect(wrapper.find(`[data-test="candidate-add-${candidate.role}"]`).exists()).toBe(true)
    }
    expect(basketsApi.addItem).not.toHaveBeenCalled()
  })

  it('optimises the project and the basket in one action', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-test="amount-input"]').setValue('۵۵ میلیون')
    await wrapper.find('[data-test="optimize"]').trigger('click')
    await flushPromises()

    // the values come from the form, and the project endpoint is used — the
    // basket optimiser is no longer a separate call
    expect(projectsApi.optimize).toHaveBeenCalledWith(
      'a1',
      expect.objectContaining({ budget: 55000000, area_m2: 12, quality: 'medium' }),
      false,
    )
    expect(basketsApi.optimize).not.toHaveBeenCalled()

    const result = wrapper.find('[data-test="optimization-result"]')
    expect(result.exists()).toBe(true)
    expect(result.text()).toContain('کاشی اقتصادی')
    expect(wrapper.findAll('[data-test="optimization-change"]')).toHaveLength(1)
  })

  it('sends a cleared field as null and never as the previous value', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-test="amount-input"]').setValue('۵۵ میلیون')
    await wrapper.find('[data-test="optimize"]').trigger('click')
    await flushPromises()
    expect(projectsApi.optimize).toHaveBeenLastCalledWith(
      'a1',
      expect.objectContaining({ budget: 55000000 }),
      false,
    )

    // now empty the field and run again
    await wrapper.find('[data-test="amount-input"]').setValue('')
    await wrapper.find('[data-test="optimize"]').trigger('click')
    await flushPromises()
    expect(projectsApi.optimize).toHaveBeenLastCalledWith(
      'a1',
      expect.objectContaining({ budget: null }),
      false,
    )
  })

  it('does not mutate the basket until the proposals are accepted', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('[data-test="optimize"]').trigger('click')
    await flushPromises()
    expect(projectsApi.optimize).toHaveBeenLastCalledWith('a1', expect.anything(), false)

    await wrapper.find('[data-test="optimization-apply"]').trigger('click')
    await flushPromises()
    expect(projectsApi.optimize).toHaveBeenLastCalledWith('a1', expect.anything(), true)
  })

  it('keeps a need it cannot supply, marked as unavailable', async () => {
    const wrapper = mountView()
    await flushPromises()
    const needs = wrapper.findAll('[data-test="project-need"]')
    expect(needs.length).toBeGreaterThan(0)
    const unavailable = wrapper.findAll('[data-test="need-unavailable"]')
    expect(unavailable.length).toBeGreaterThan(0)
    // the state does not rest on colour: it carries a word as well
    expect(unavailable[0].text()).toContain('موجود نیست')
  })
})
