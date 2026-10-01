import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import AlertBox from '@/components/ui/AlertBox.vue'
import BudgetAmountInput from '@/components/basket/BudgetAmountInput.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import SearchBar from '@/components/search/SearchBar.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import { numberToWords, toLatinDigits, toPersianDigits } from '@/utils/format'

describe('Skeleton', () => {
  it('is decorative and inherits the caller sizing', () => {
    const wrapper = mount(Skeleton, { attrs: { class: 'h-4 w-24' } })
    expect(wrapper.attributes('aria-hidden')).toBe('true')
    expect(wrapper.classes()).toContain('animate-pulse')
    expect(wrapper.classes()).toContain('h-4')
    // motion is disabled when the OS asks for it
    expect(wrapper.classes().join(' ')).toContain('motion-reduce:animate-none')
  })
})

describe('EmptyState', () => {
  it('says what is missing and offers one next action', () => {
    const wrapper = mount(EmptyState, {
      props: { title: 'نتیجه‌ای پیدا نشد', description: 'در کاتالوگ دمو چیزی ثبت نشده است.' },
      slots: { default: '<button>شروع جست‌وجو</button>' },
    })
    const text = wrapper.text()
    expect(text).toContain('نتیجه‌ای پیدا نشد')
    expect(text).toContain('شروع جست‌وجو')
    // Material: a raised surface, not a dashed outline
    expect(wrapper.classes()).toContain('card')
    expect(wrapper.classes()).not.toContain('border-dashed')
    // never a generic "oops" style message
    expect(text).not.toContain('خطا')
  })
})

describe('AlertBox', () => {
  it('announces errors and can offer a retry', async () => {
    const wrapper = mount(AlertBox, {
      props: { tone: 'error', title: 'جست‌وجو انجام نشد', actionLabel: 'تلاش دوباره' },
      slots: { default: 'ارتباط با سرور برقرار نشد.' },
    })
    expect(wrapper.attributes('role')).toBe('alert')
    expect(wrapper.attributes('aria-live')).toBe('polite')
    expect(wrapper.text()).toContain('تلاش دوباره')

    await wrapper.find('button').trigger('click')
    expect(wrapper.emitted('action')).toHaveLength(1)
  })

  it('is a polite status for non-error tones', () => {
    const wrapper = mount(AlertBox, { props: { tone: 'info' } })
    expect(wrapper.attributes('role')).toBe('status')
  })
})

describe('BudgetAmountInput', () => {
  it('groups digits, keeps the unit after the number and spells the amount out', async () => {
    const wrapper = mount(BudgetAmountInput, { props: { modelValue: '55000000', label: 'بودجهٔ هدف' } })

    const input = wrapper.find('input')
    // label is associated with the control
    expect(wrapper.find('label').attributes('for')).toBe(input.attributes('id'))
    expect(wrapper.text()).toContain('تومان')
    expect(input.element.value).toBe('۵۵٬۰۰۰٬۰۰۰')
    expect(wrapper.find('[data-test="amount-words"]').text()).toBe('پنجاه و پنج میلیون تومان')
  })

  it('keeps a scale word visible instead of collapsing it to bare digits', async () => {
    // «۵۵ میلیون» must not re-render as «۵۵», which would read as 55 Toman
    const wrapper = mount(BudgetAmountInput, { props: { modelValue: '۵۵ میلیون', label: 'بودجه' } })
    expect(wrapper.find('input').element.value).toBe('۵۵ میلیون')
    expect(wrapper.find('[data-test="amount-words"]').text()).toContain('پنجاه و پنج میلیون تومان')
  })

  it('accepts a full Persian sentence and reports the parsed Toman', async () => {
    const wrapper = mount(BudgetAmountInput, { props: { modelValue: '', label: 'بودجه' } })
    await wrapper.find('input').setValue('بودجه من ۵۵ میلیون است')
    // v-model round trip, as a parent component would do
    await wrapper.setProps({ modelValue: 'بودجه من ۵۵ میلیون است' })

    expect(wrapper.emitted('parsed')?.at(-1)).toEqual([55_000_000])
    expect(wrapper.find('[data-test="amount-words"]').text()).toContain('پنجاه و پنج میلیون')
  })

  it('marks unparseable input invalid and explains what to write', async () => {
    const wrapper = mount(BudgetAmountInput, { props: { modelValue: '', label: 'بودجه' } })
    await wrapper.find('input').setValue('خیلی زیاد')
    await wrapper.setProps({ modelValue: 'خیلی زیاد' })

    expect(wrapper.find('input').attributes('aria-invalid')).toBe('true')
    expect(wrapper.find('[data-test="amount-error"]').text()).toContain('بودجه من ۵۵ میلیون است')
    expect(wrapper.emitted('parsed')?.at(-1)).toEqual([null])
  })
})

describe('SearchBar', () => {
  it('does not submit while an IME composition is open', async () => {
    const wrapper = mount(SearchBar)
    const input = wrapper.find('input')

    await input.setValue('بازسازی سرویس')
    await input.trigger('compositionstart')
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('submit')).toBeUndefined()

    // Enter commits the syllable first, then submits normally
    await input.trigger('compositionend')
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('submit')?.[0]).toEqual(['بازسازی سرویس'])
  })

  it('has no visible buttons, and submits on Enter', async () => {
    /**
     * The field is the control. Enter runs the search; nothing else does.
     *
     * The submit button is still in the DOM because a form with no submit control
     * is not submitted consistently, and an unnamed one is an unnamed one for a
     * screen reader — so it is hidden and labelled rather than removed.
     */
    const wrapper = mount(SearchBar, { props: { modelValue: '' } })

    expect(wrapper.find('[data-test="search-clear"]').exists()).toBe(false)
    const submit = wrapper.find('[data-test="search-submit"]')
    expect(submit.exists()).toBe(true)
    expect(submit.classes()).toContain('sr-only')
    expect(submit.attributes('type')).toBe('submit')
    expect(submit.text().trim()).not.toBe('')

    await wrapper.find('input').setValue('شیر توکار')
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('submit')?.[0]).toEqual(['شیر توکار'])
  })

  it('will not run a second search while one is in flight', async () => {
    /**
     * The guard used to live on the removed button's `disabled`.
     *
     * Enter is now the only trigger, so without this a second Enter mid-search would
     * submit and supersede the first rather than waiting for it.
     */
    const wrapper = mount(SearchBar, { props: { modelValue: 'شیر توکار', busy: true } })
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('submit')).toBeUndefined()
  })

  it('will not submit fewer than two characters', async () => {
    const wrapper = mount(SearchBar)
    await wrapper.find('input').setValue('ش')
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('submit')).toBeUndefined()
  })
})

describe('persian number helpers', () => {
  it('localises digits and separators', () => {
    expect(toPersianDigits(1234567.5)).toBe('۱٬۲۳۴٬۵۶۷٫۵')
    expect(toLatinDigits('۵۵٬۰۰۰')).toBe('55000')
  })

  it('spells amounts in Persian words', () => {
    expect(numberToWords(1_250_000)).toBe('یک میلیون و دویست و پنجاه هزار تومان')
    expect(numberToWords(1000)).toBe('یک هزار تومان')
    expect(numberToWords(0)).toBe('صفر تومان')
    expect(numberToWords(73910000)).toContain('هفتاد و سه میلیون')
  })
})
