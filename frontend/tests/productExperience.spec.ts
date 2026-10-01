/**
 * The product detail experience and clearing the basket.
 *
 * The catalogue is the only source, so every product on screen must be one the
 * backend sent: the card and the detail view render the catalogue's own image
 * and metadata, similar and complementary lists render only what the API
 * returned, and a cleared basket is genuinely empty rather than a stale copy.
 */

import { flushPromises, mount } from '@vue/test-utils'
import { RouterLinkStub } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { productsApi, basketsApi } = vi.hoisted(() => ({
  productsApi: {
    search: vi.fn(),
    detail: vi.fn(),
    similar: vi.fn(),
    complementary: vi.fn(),
    categories: vi.fn(),
  },
  basketsApi: {
    create: vi.fn(),
    get: vi.fn(),
    addItem: vi.fn(),
    updateItem: vi.fn(),
    removeItem: vi.fn(),
    clear: vi.fn(),
    optimize: vi.fn(),
  },
}))

const { routeMock, routerMock } = vi.hoisted(() => ({
  routeMock: { params: {} as Record<string, string>, query: {} as Record<string, string> },
  routerMock: { push: vi.fn(), replace: vi.fn() },
}))

vi.mock('@/api/products', () => ({ productsApi }))
vi.mock('@/api/baskets', () => ({ basketsApi }))
vi.mock('vue-router', () => ({
  useRouter: () => routerMock,
  useRoute: () => routeMock,
}))

import { ApiError } from '@/api/client'
import BasketView from '@/views/SelectionView.vue'
import CatalogueImage from '@/components/product/CatalogueImage.vue'
import ProductCard from '@/components/product/ProductCard.vue'
import ProductView from '@/views/ProductView.vue'
import type { Basket, Product } from '@/types/api'

const IMAGE = 'https://dkstatics-public.digikala.com/dic_image_placeholder.jpg'

const PRODUCT: Product = {
  id: 'p1',
  name: 'شیر روشویی کاسا مدل K-100',
  slug: 'kasa-k-100',
  subtitle: null,
  domain: 'bathroom',
  source_url: 'https://torob.com/p/test',
  origin_country: null,
  max_price: 5900000,
  match_score: null,
  category: {
    id: 'c1',
    slug: 'sink-faucet',
    name: 'شیر روشویی',
    domain: 'bathroom',
    kind: 'fixture',
    description_fa: null,
    product_count: 4,
  },
  subcategory: 'sink-faucet',
  brand: { id: 'b1', slug: 'kasa', name: 'کاسا', name_en: 'Kasa', country: null },
  model: 'K-100',
  image_url: IMAGE,
  attributes: [
    { key: 'color', label: 'رنگ', value: 'کروم', value_num: null, unit: null },
    { key: 'installation', label: 'نصب', value: 'روکار', value_num: null, unit: null },
  ],
  min_price: 5900000,
  offers_count: 2,
  available_offers_count: 2,
  quality: null,
  quality_fa: null,
  style: null,
  warranty_months: null,
  rating: null,
  unit: null,
  is_demo: false,
  offers: [
    {
      id: 'o1',
      seller: { id: 's1', slug: 's1', name: 'بازار ساختمان', city: 'تهران', is_demo: false },
      price: 5900000,
      original_price: null,
      availability: 'in_stock',
      available: true,
      stock_count: null,
      delivery_days: null,
      warranty_months: null,
      url: 'https://torob.com/x',
      price_updated_at: '۴ روز پیش',
    },
  ],
}

const OTHER: Product = {
  ...PRODUCT,
  id: 'p2',
  name: 'روشویی کابینتی پارس سرام',
  image_url: `${IMAGE}?v=2`,
  min_price: 12000000,
  offers: [],
  offers_count: 0,
  available_offers_count: 0,
}

const BASKET: Basket = {
  id: 'b1',
  kind: 'product',
  title: null,
  currency: 'IRT',
  items_count: 1,
  total: 5900000,
  project_id: null,
  target_budget: null,
  budget_gap: null,
  within_budget: null,
  intent: null,
  notes: null,
  created_at: '2026-03-01T09:00:00Z',
  updated_at: '2026-03-01T09:00:00Z',
  items: [
    {
      id: 'i1',
      product: PRODUCT,
      offer: PRODUCT.offers[0],
      unit_price: 5900000,
      line_total: 5900000,
      role: 'main',
      origin: 'search',
      is_locked: false,
      reason: 'مناسب برای روشویی',
      replaced_item_id: null,
      is_best_price: true,
      best_price: 5900000,
      alternative_count: 0,
      alternative_min_price: null,
    },
  ],
}

const EMPTY_BASKET: Basket = {
  ...BASKET,
  items_count: 0,
  total: 0,
  items: [],
}

const globalMountOptions = { global: { stubs: { RouterLink: RouterLinkStub, RouterView: true } } }

beforeEach(() => {
  vi.clearAllMocks()
  routeMock.query = {}
  routeMock.params = { id: 'p1' }
  productsApi.detail.mockResolvedValue(PRODUCT)
  productsApi.similar.mockResolvedValue([])
  productsApi.complementary.mockResolvedValue({
    items: [],
    llm_available: false,
    candidate_count: 0,
    note: null,
    discarded_ids: [],
  })
  basketsApi.get.mockResolvedValue(BASKET)
  basketsApi.clear.mockResolvedValue(undefined)
})

describe('ProductCard', () => {
  it('shows the catalogue image, brand and model', () => {
    const wrapper = mount(ProductCard, {
      props: { product: PRODUCT },
      ...globalMountOptions,
    })

    const image = wrapper.get('[data-test="product-image"]')
    expect(image.attributes('src')).toBe(IMAGE)
    expect(image.attributes('loading')).toBe('lazy')
    expect(wrapper.text()).toContain('کاسا')
    expect(wrapper.text()).toContain('K-100')
  })

  it('links to the product it came from', () => {
    const wrapper = mount(ProductCard, {
      props: { product: PRODUCT },
      ...globalMountOptions,
    })
    const link = wrapper.getComponent(RouterLinkStub)
    expect(link.props('to')).toEqual({ name: 'product', params: { id: 'p1' } })
  })

  it('falls back gracefully when the catalogue has no image', () => {
    const wrapper = mount(ProductCard, {
      props: { product: { ...PRODUCT, image_url: '' } },
      ...globalMountOptions,
    })
    expect(wrapper.find('[data-test="product-image"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('شیر روشویی کاسا مدل K-100')
  })

  it('shows a quality only when the catalogue carries one', () => {
    const withQuality = mount(ProductCard, {
      props: { product: { ...PRODUCT, quality: 'medium', quality_fa: 'متوسط' } },
      ...globalMountOptions,
    })
    expect(withQuality.text()).toContain('متوسط')

    // the catalogue records no quality, so none may be shown
    const withoutQuality = mount(ProductCard, {
      props: { product: { ...PRODUCT, quality: null, quality_fa: null } },
      ...globalMountOptions,
    })
    expect(withoutQuality.text()).not.toContain('متوسط')
  })
})

describe('ProductView', () => {
  it('renders the catalogue product and its offers', async () => {
    const wrapper = mount(ProductView, { props: { id: 'p1' }, ...globalMountOptions })
    await flushPromises()

    expect(productsApi.detail).toHaveBeenCalledWith('p1')
    expect(wrapper.text()).toContain('شیر روشویی کاسا مدل K-100')
    expect(wrapper.text()).toContain('بازار ساختمان')
    expect(wrapper.get('[data-test="detail-image"]').attributes('src')).toBe(IMAGE)
  })

  it('shows the attributes the catalogue records', async () => {
    const wrapper = mount(ProductView, { props: { id: 'p1' }, ...globalMountOptions })
    await flushPromises()

    expect(wrapper.text()).toContain('رنگ')
    expect(wrapper.text()).toContain('کروم')
    expect(wrapper.text()).toContain('روکار')
  })

  it('loads similar products, and never asks for complementary ones', async () => {
    mount(ProductView, { props: { id: 'p1' }, ...globalMountOptions })
    await flushPromises()

    expect(productsApi.similar).toHaveBeenCalledWith('p1', 6)
    // Complementary products were removed from the product page: the page is
    // about this product, its sellers, and genuine alternatives.
    expect(productsApi.complementary).not.toHaveBeenCalled()
  })

  it('has no complementary section on the product page', async () => {
    productsApi.similar.mockResolvedValue([
      {
        product_id: 'p2',
        product: OTHER,
        reason: 'گزینهٔ مشابه',
        match_score: 0.5,
        relation_type: 'same_kind',
        similar_to: 'p1',
      },
    ])
    const wrapper = mount(ProductView, { props: { id: 'p1' }, ...globalMountOptions })
    await flushPromises()

    expect(wrapper.find('[data-test="complementary-products"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('مکمل')
    // the alternatives section stays
    expect(wrapper.find('[data-test="similar-products"]').exists()).toBe(true)
  })

  it('renders only the similar products the backend returned', async () => {
    productsApi.similar.mockResolvedValue([
      { product: OTHER, match_type: 'same_subcategory', reason: 'از همان دستهٔ کاتالوگ.' },
    ])

    const wrapper = mount(ProductView, { props: { id: 'p1' }, ...globalMountOptions })
    await flushPromises()

    const section = wrapper.get('[data-test="similar-products"]')
    expect(section.text()).toContain('روشویی کابینتی پارس سرام')
    expect(section.text()).toContain('از همان دستهٔ کاتالوگ.')
  })

  it('shows an error instead of a blank page when the product 404s', async () => {
    productsApi.detail.mockRejectedValue(new ApiError('محصول پیدا نشد.', 404))

    const wrapper = mount(ProductView, { props: { id: 'p1' }, ...globalMountOptions })
    await flushPromises()

    expect(wrapper.find('[data-test="product-error"]').exists()).toBe(true)
  })
})

describe('BasketView', () => {
  it('clears the whole basket through the API', async () => {
    const wrapper = mount(BasketView, { props: { id: 'b1' }, ...globalMountOptions })
    await flushPromises()

    await wrapper.get('[data-test="clear-basket"]').trigger('click')
    await flushPromises()

    expect(basketsApi.clear).toHaveBeenCalledWith('b1')
  })

  it('explains an empty selection list in terms of selecting', async () => {
    basketsApi.get.mockResolvedValue(EMPTY_BASKET)
    const wrapper = mount(BasketView, { props: { id: 'b1' }, ...globalMountOptions })
    await flushPromises()

    expect(wrapper.find('[data-test="basket-manifest"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="selection-empty"]').exists()).toBe(true)
    const text = wrapper.text()
    expect(text).toContain('هنوز محصولی انتخاب نکرده‌اید')
    // no cart, checkout or payment language anywhere in the empty state
    expect(text).not.toContain('سبد')
    expect(text).not.toContain('پرداخت')
    expect(text).not.toContain('تسویه')
  })

  it('offers the clear action only when there is something to clear', async () => {
    basketsApi.get.mockResolvedValue(EMPTY_BASKET)
    const wrapper = mount(BasketView, { props: { id: 'b1' }, ...globalMountOptions })
    await flushPromises()

    expect(wrapper.find('[data-test="clear-basket"]').exists()).toBe(false)
  })
})

describe('CatalogueImage', () => {
  it('loads the catalogue URL and nothing else', () => {
    const wrapper = mount(CatalogueImage, {
      props: { src: IMAGE, alt: 'شیر روشویی کاسا', class: 'h-20 w-20' },
    })

    const img = wrapper.get('img')
    expect(img.attributes('src')).toBe(IMAGE)
    expect(img.attributes('alt')).toBe('شیر روشویی کاسا')
    expect(img.attributes('loading')).toBe('lazy')
    expect(img.classes()).toContain('h-20')
  })

  it('falls back to a placeholder when the image host refuses', async () => {
    // the catalogue host is unreachable on some networks; a broken-image icon
    // in the middle of a product grid would read as a bug in the shop
    const wrapper = mount(CatalogueImage, { props: { src: IMAGE, alt: 'شیر روشویی' } })
    await wrapper.get('img').trigger('error')

    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.find('[data-test="product-image-fallback"]').exists()).toBe(true)
  })

  it('keeps the same box so nothing jumps', async () => {
    const wrapper = mount(CatalogueImage, {
      props: { src: IMAGE, alt: 'شیر روشویی', class: 'aspect-square w-full' },
    })
    await wrapper.get('img').trigger('error')

    expect(wrapper.get('[data-test="product-image-fallback"]').classes()).toContain('aspect-square')
  })

  it('names the product when there is no image to show at all', () => {
    const wrapper = mount(CatalogueImage, { props: { src: '', alt: 'شیر روشویی کاسا' } })

    const fallback = wrapper.get('[data-test="product-image-fallback"]')
    expect(wrapper.find('img').exists()).toBe(false)
    expect(fallback.attributes('role')).toBe('img')
    expect(fallback.attributes('aria-label')).toBe('شیر روشویی کاسا')
  })

  it('retries when the product changes', async () => {
    const wrapper = mount(CatalogueImage, { props: { src: IMAGE, alt: 'first' } })
    await wrapper.get('img').trigger('error')
    expect(wrapper.find('img').exists()).toBe(false)

    // a new product means a new URL, so the failure must not stick
    await wrapper.setProps({ src: 'https://image.torob.com/other.jpg', alt: 'second' })
    expect(wrapper.get('img').attributes('src')).toBe('https://image.torob.com/other.jpg')
  })
})
