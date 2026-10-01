import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import OfferComparison from '@/components/product/OfferComparison.vue'
import type { Offer } from '@/types/api'

const SELLER = (id: string, name: string) => ({
  id,
  slug: id,
  name,
  city: 'تهران',
  is_demo: true,
})

const OFFERS: Offer[] = [
  {
    id: 'o1',
    seller: SELLER('s1', 'ساختمان‌یار (دمو)'),
    price: 5900000,
    original_price: 6372000,
    availability: 'in_stock',
    available: true,
    stock_count: 4,
    delivery_days: 1,
    warranty_months: 24,
    url: null,
    price_updated_at: '2026-03-01T09:00:00Z',
  },
  {
    id: 'o2',
    seller: SELLER('s2', 'پارس سانوبار (دمو)'),
    price: 6254000,
    original_price: null,
    availability: 'preorder',
    available: true,
    stock_count: 0,
    delivery_days: 2,
    warranty_months: 18,
    url: null,
    price_updated_at: '2026-03-01T09:00:00Z',
  },
  {
    id: 'o3',
    seller: SELLER('s3', 'بازار ساختمان (دمو)'),
    price: 6667000,
    original_price: null,
    availability: 'out_of_stock',
    available: false,
    stock_count: 0,
    delivery_days: 4,
    warranty_months: 12,
    url: null,
    price_updated_at: '2026-03-01T09:00:00Z',
  },
]

describe('OfferComparison', () => {
  it('makes same-product / different-seller / different-price obvious', () => {
    const wrapper = mount(OfferComparison, { props: { offers: OFFERS } })
    const text = wrapper.text()

    expect(text).toContain('مقایسهٔ فروشندگان')
    expect(text).toContain('اختلاف قیمت')
    expect(text).toContain('کمترین قیمت')
    // the difference between the cheapest and the most expensive offer
    expect(text).toContain('۷۶۷٬۰۰۰')
    // how much the cheapest seller saves
  })

  it('renders one row per seller for both the stacked and table layouts', () => {
    const wrapper = mount(OfferComparison, { props: { offers: OFFERS } })
    // two responsive variants (stacked list for phones, table for md and up)
    expect(wrapper.findAll('[data-test="offer-row"]')).toHaveLength(OFFERS.length * 2)
  })

  it('shows availability per seller and disables the button when unavailable', () => {
    const wrapper = mount(OfferComparison, { props: { offers: OFFERS } })
    const labels = wrapper.findAll('[data-test="availability"]').map((n) => n.text())
    expect(labels.filter((label) => label === 'موجود').length).toBeGreaterThan(0)
    expect(labels).toContain('ناموجود')

    const disabledButtons = wrapper
      .findAll('button')
      .filter((b) => b.attributes('disabled') !== undefined)
    expect(disabledButtons.length).toBeGreaterThan(0)
  })

  it('emits the chosen offer', async () => {
    const wrapper = mount(OfferComparison, { props: { offers: OFFERS } })
    const enabled = wrapper.findAll('button').filter((b) => b.attributes('disabled') === undefined)
    await enabled[0].trigger('click')
    expect(wrapper.emitted('choose')?.[0][0]).toMatchObject({ id: 'o1' })
  })

  it('tells the user what the cheapest seller saves', () => {
    const text = mount(OfferComparison, { props: { offers: OFFERS } }).text()
    expect(text).toContain('با خرید از ارزان‌ترین فروشنده')
    expect(text).toContain('کمتر پرداخت می‌کنید')
  })
})

