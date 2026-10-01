import { describe, expect, it } from 'vitest'

import { formatToman, formatTomanShort, parseToman, toPersianDigits } from '@/utils/format'

describe('persian number formatting', () => {
  it('converts latin digits to persian digits with a thousands separator', () => {
    expect(toPersianDigits(1234567)).toBe('۱٬۲۳۴٬۵۶۷')
  })

  it('formats money in Toman', () => {
    expect(formatToman(5900000)).toBe('۵٬۹۰۰٬۰۰۰ تومان')
    expect(formatToman(null)).toBe('—')
  })

  it('shortens large amounts for headline figures', () => {
    expect(formatTomanShort(73910000)).toBe('۷۳٫۹ میلیون تومان')
    expect(formatTomanShort(1200000)).toBe('۱٫۲ میلیون تومان')
  })
})

describe('budget parsing', () => {
  it('parses a plain Toman amount', () => {
    expect(parseToman('۵۵۰۰۰۰۰۰')).toBe(55000000)
  })

  it('parses millions and thousands', () => {
    expect(parseToman('۵۵ میلیون')).toBe(55000000)
    expect(parseToman('۲۰۰ هزار')).toBe(200000)
  })

  it('returns null for nonsense', () => {
    expect(parseToman('')).toBeNull()
    expect(parseToman('خیلی زیاد')).toBeNull()
  })
})
