import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import Table, { type RequirementColumn } from '@/components/project/Table.vue'
import type { Category, RecommendedCategory } from '@/types/api'

/**
 * The rows are shaped by the API type, so they are built from a category and a
 * handful of fields rather than invented wholesale.
 */
function category(overrides: Partial<Category> = {}): Category {
  return {
    id: 'c1',
    slug: 'bathroom.tiles',
    name: 'کاشی و سرامیک',
    domain: 'bathroom',
    kind: 'surface',
    description_fa: null,
    product_count: 4,
    ...overrides,
  } as Category
}

function requirement(overrides: Partial<RecommendedCategory> = {}): RecommendedCategory {
  return {
    role: 'tiles',
    label: 'کاشی و سرامیک',
    category: category(),
    quantity: 39,
    unit: 'متر مربع',
    is_required: true,
    quality_min: 'low',
    reason: 'برای کف و دیوار، حدود ۳٫۲ متر مربع به ازای هر متر مربع زمین نیاز است.',
    project_need: true,
    catalog_match: true,
    in_catalog: true,
    note: null,
    unavailable_reason: null,
    ...overrides,
  }
}

/** The columns the project page uses: the model's own fields, nothing added. */
const COLUMNS: RequirementColumn[] = [
  { field: 'label', header: 'ملزومات', format: 'text' },
  { field: 'quantity', header: 'تعداد', format: 'quantity' },
  { field: 'is_required', header: 'وضعیت', format: 'status' },
  { field: 'reason', header: 'توضیحات', format: 'text' },
]

describe('project requirements Table', () => {
  it('is a real table, with a column header per column', () => {
    const wrapper = mount(Table, {
      props: { rows: [requirement()], columns: COLUMNS },
    })

    expect(wrapper.find('table').exists()).toBe(true)
    expect(wrapper.find('thead').exists()).toBe(true)
    expect(wrapper.find('tbody').exists()).toBe(true)
    expect(wrapper.findAll('tbody tr')).toHaveLength(1)

    const headers = wrapper.findAll('th')
    expect(headers).toHaveLength(COLUMNS.length)
    for (const header of headers) {
      expect(header.attributes('scope')).toBe('col')
      // reading starts at the start in Persian
      expect(header.classes().join(' ')).toMatch(/text-start|text-end/)
    }
    expect(headers.map((h) => h.text())).toEqual(['ملزومات', 'تعداد', 'وضعیت', 'توضیحات'])
  })

  it('is Persian and right-to-left', () => {
    const wrapper = mount(Table, { props: { rows: [requirement()], columns: COLUMNS } })
    expect(wrapper.get('table').attributes('dir')).toBe('rtl')
  })

  it('maps the model directly: quantity, unit, reason and required', () => {
    const wrapper = mount(Table, { props: { rows: [requirement()], columns: COLUMNS } })
    const cells = wrapper.findAll('tbody td').map((c) => c.text())

    expect(cells[0]).toContain('کاشی و سرامیک')
    expect(cells[1]).toContain('۳۹')
    expect(cells[1]).toContain('متر مربع')
    expect(cells[2]).toContain('ضروری')
    expect(cells[3]).toContain('برای کف و دیوار')
  })

  it('keeps a requirement it cannot supply, in words rather than colour', () => {
    const wrapper = mount(Table, {
      props: {
        rows: [
          requirement({
            catalog_match: false,
            in_catalog: false,
            unavailable_reason: 'not_stocked',
            note: 'کاشی ساده در این بازهٔ قیمت موجود نیست.',
          }),
        ],
        columns: COLUMNS,
      },
    })
    const status = wrapper.findAll('tbody td')[2].text()

    expect(status).toContain('قابل تأمین نیست')
    expect(status).toContain('کاشی ساده در این بازهٔ قیمت موجود نیست.')
  })

  it('says which is which without needing colour', () => {
    const wrapper = mount(Table, {
      props: {
        rows: [requirement({ is_required: false })],
        columns: COLUMNS,
      },
    })
    expect(wrapper.findAll('tbody td')[2].text()).toContain('اختیاری')
  })

  it('writes figures so they do not reflow', () => {
    const wrapper = mount(Table, { props: { rows: [requirement()], columns: COLUMNS } })
    const quantity = wrapper.findAll('tbody td')[1]

    expect(quantity.classes().join(' ')).toContain('num')
    expect(quantity.classes().join(' ')).toContain('text-end')
  })

  it('renders money through the one money formatter, unit after the number', () => {
    const wrapper = mount(Table, {
      props: {
        rows: [requirement()],
        columns: [{ field: 'quality_min', header: 'برآورد', format: 'money' }],
      },
    })
    // a requirement carries no amount, so the cell says so rather than inventing one
    expect(wrapper.find('tbody td').text()).toBe('—')

    const withMoney = mount(Table, {
      props: {
        rows: [requirement()],
        columns: [{ field: 'quantity', header: 'برآورد', format: 'money' }],
      },
    })
    expect(withMoney.find('tbody td').text()).toBe('۳۹ تومان')
  })

  it('holds its width on a narrow screen and scrolls inside itself', () => {
    const wrapper = mount(Table, { props: { rows: [requirement()], columns: COLUMNS } })
    const region = wrapper.get('[role="region"]')

    expect(region.classes().join(' ')).toContain('overflow-x-auto')
    expect(region.classes().join(' ')).toContain('max-w-full')
    // a scroll container has to be reachable by keyboard
    expect(region.attributes('tabindex')).toBe('0')
    expect(region.attributes('aria-label')).toBe('جدول ملزومات پروژه')
  })

  it('keeps the header on the same muted background as a row of labels', () => {
    const wrapper = mount(Table, { props: { rows: [requirement()], columns: COLUMNS } })
    expect(wrapper.get('thead tr').classes().join(' ')).toContain('bg-muted')
    expect(wrapper.get('tbody tr').classes().join(' ')).toContain('hover:bg-accent/40')
  })

  it('says when the project has no requirements yet', () => {
    const wrapper = mount(Table, { props: { rows: [], columns: COLUMNS } })

    expect(wrapper.findAll('tbody td')).toHaveLength(1)
    expect(wrapper.get('tbody td').attributes('colspan')).toBe(String(COLUMNS.length))
    expect(wrapper.get('tbody td').text()).toContain('هنوز ملزومی ثبت نشده است')
  })

  it('never shows a purchasing concept: no price, seller, stock or SKU', () => {
    const wrapper = mount(Table, { props: { rows: [requirement()], columns: COLUMNS } })
    const text = wrapper.text()

    for (const forbidden of ['تومان', 'فروشنده', 'انبار', 'کد کالا', 'سبد', 'پرداخت']) {
      expect(text).not.toContain(forbidden)
    }
  })

  it('renders no request of its own', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    const wrapper = mount(Table, { props: { rows: [requirement()], columns: COLUMNS } })
    await wrapper.vm.$nextTick()

    expect(fetchSpy).not.toHaveBeenCalled()
    fetchSpy.mockRestore()
  })
})
