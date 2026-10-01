/**
 * Persian formatting helpers — the single path for every visible number.
 *
 * Rules (VibeFarsi): visible digits are Persian ۰-۹, the thousands separator is
 * «٬» (U+066C), the decimal mark is «٫», the unit follows the number, and
 * truncation never splits Persian letters.
 *
 * Values arriving from the API are always plain integers (Toman) or plain
 * numeric strings; only the display layer converts.
 */

const FA_DIGITS = ['۰', '۱', '۲', '۳', '۴', '۵', '۶', '۷', '۸', '۹']
const THOUSANDS = '٬' // U+066C
const DECIMAL = '٫' // U+066B

const PERSIAN_TO_LATIN = new Map(FA_DIGITS.map((d, i) => [d, String(i)] as const))

/** Persian/Arabic digits and separators → a plain Latin numeric string. */
export function toLatinDigits(input: string): string {
  let out = ''
  for (const char of input) {
    const mapped = PERSIAN_TO_LATIN.get(char)
    if (mapped) {
      out += mapped
      continue
    }
    if (char === THOUSANDS || char === '٬' || char === ',' || char === '،') {
      out += ''
      continue
    }
    if (char === DECIMAL || char === '٫' || char === '.') {
      out += '.'
      continue
    }
    out += char
  }
  return out
}

/** 1234567.5 → «۱٬۲۳۴٬۵۶۷٫۵» */
export function toPersianDigits(value: string | number): string {
  // JS already renders 12.0 as "12", so a whole area reads as «۱۲» not «۱۲٫۰»
  const raw = String(value)
  const negative = raw.trim().startsWith('-')
  const [integerPart, fractionPart] = raw.replace('-', '').split('.')
  const grouped = integerPart.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  const joined = fractionPart === undefined ? grouped : `${grouped}.${fractionPart}`
  const localized = joined
    .replace(/[0-9]/g, (d) => FA_DIGITS[Number(d)])
    .replace(/,/g, THOUSANDS)
    .replace(/\./g, DECIMAL)
  return negative ? `‎${localized}` : localized
}

/** Plain number formatting without a unit. */
export function faNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return toPersianDigits(value)
}

/** Money. The unit always follows the number: «۱۲٬۴۵۰٬۰۰۰ تومان». */
export function formatToman(amount: number | null | undefined): string {
  if (amount === null || amount === undefined || Number.isNaN(amount)) return '—'
  return `${toPersianDigits(amount)} تومان`
}

/** Compact money for headline figures: 73_910_000 → «۷۳٫۹ میلیون تومان». */
export function formatTomanShort(amount: number | null | undefined): string {
  if (amount === null || amount === undefined || Number.isNaN(amount)) return '—'
  const abs = Math.abs(amount)
  if (abs >= 1_000_000_000) return `${toPersianDigits(trimZero(amount / 1_000_000_000))} میلیارد تومان`
  if (abs >= 1_000_000) return `${toPersianDigits(trimZero(amount / 1_000_000))} میلیون تومان`
  if (abs >= 1_000) return `${toPersianDigits(trimZero(amount / 1_000))} هزار تومان`
  return formatToman(amount)
}

function trimZero(value: number): string {
  const fixed = value.toFixed(1)
  return fixed.endsWith('.0') ? fixed.slice(0, -2) : fixed
}

/**
 * Accepts either a bare amount («۵۵ میلیون», «55000000») or a full Persian
 * sentence («بودجه من ۵۵ میلیون است») and returns Toman.
 */
export function parseToman(input: string): number | null {
  if (!input) return null
  const hasPersian = /[\u0600-\u06FF]/.test(input)
  const numerals = toLatinDigits(input)
  const scale = input.includes('میلیارد')
    ? 1_000_000_000
    : input.includes('میلیون')
      ? 1_000_000
      : input.includes('هزار')
        ? 1_000
        : 1
  const match = numerals.match(/\d[\d.]*/)
  if (!match) return null
  const value = Number.parseFloat(match[0])
  if (!Number.isFinite(value) || value <= 0) return null
  // A sentence with no scale word but a big number is already in Toman.
  if (scale === 1 && !hasPersian && value < 1000) return null
  return Math.round(value * scale)
}

// --------------------------------------------------------------------------- //
// Persian amount in words (VibeFarsi `number-to-words` pattern, re-implemented)
// --------------------------------------------------------------------------- //
const ONES = ['', 'یک', 'دو', 'سه', 'چهار', 'پنج', 'شش', 'هفت', 'هشت', 'نه']
const TEENS = [
  'ده',
  'یازده',
  'دوازده',
  'سیزده',
  'چهارده',
  'پانزده',
  'شانزده',
  'هفده',
  'هجده',
  'نوزده',
]
const TENS = ['', '', 'بیست', 'سی', 'چهل', 'پنجاه', 'شصت', 'هفتاد', 'هشتاد', 'نود']
const HUNDREDS = [
  '',
  'یکصد',
  'دویست',
  'سیصد',
  'چهارصد',
  'پانصد',
  'ششصد',
  'هفتصد',
  'هشتصد',
  'نهصد',
]
const SCALES = ['', ' هزار', ' میلیون', ' میلیارد', ' بیلیون']

function threeDigitsToWords(value: number): string {
  const parts: string[] = []
  const hundreds = Math.floor(value / 100)
  const rest = value % 100
  if (hundreds) parts.push(HUNDREDS[hundreds])
  if (rest >= 10 && rest < 20) {
    parts.push(TEENS[rest - 10])
  } else {
    const tens = Math.floor(rest / 10)
    const ones = rest % 10
    if (tens) parts.push(TENS[tens])
    if (ones) parts.push(ONES[ones])
  }
  return parts.join(' و ')
}

/**
 * 1_250_000 → «یک میلیون و دویست و پنجاه هزار تومان».
 * Used under amount inputs so the user can confirm what the system understood.
 */
export function numberToWords(amount: number | null | undefined, unit = 'تومان'): string {
  if (amount === null || amount === undefined || !Number.isFinite(amount)) return ''
  const rounded = Math.round(amount)
  if (rounded === 0) return `صفر ${unit}`

  const negative = rounded < 0
  const abs = Math.abs(rounded)
  const groups: number[] = []
  let rest = abs
  while (rest > 0) {
    groups.push(rest % 1000)
    rest = Math.floor(rest / 1000)
  }

  const words: string[] = []
  for (let i = groups.length - 1; i >= 0; i -= 1) {
    const group = groups[i]
    if (!group) continue
    const chunk = threeDigitsToWords(group)
    // «هزار» on its own for 1000, «یک میلیون» for 1e6
    words.push(`${chunk}${SCALES[i] ?? ''}`)
  }

  const body = words.join(' و ')
  return `${negative ? 'منفی ' : ''}${body} ${unit}`.trim()
}

// --------------------------------------------------------------------------- //
// Lookup labels
// --------------------------------------------------------------------------- //
export const AVAILABILITY_FA: Record<string, string> = {
  in_stock: 'موجود',
  low_stock: 'موجودی کم',
  preorder: 'پیش‌سفارش',
  out_of_stock: 'ناموجود',
}

export const RELATION_FA: Record<string, string> = {
  same_kind: 'هم‌دسته',
  install_kit: 'کیت نصب',
  compatible_fitting: 'اتصال سازگار',
  required_material: 'مصالح لازم',
  accessory_pair: 'مکمل کاربردی',
  room_pair: 'اقلام هم‌پروژه',
  alternative: 'جایگزین',
}

export const ORIGIN_FA: Record<string, string> = {
  search: 'جست‌وجو',
  project: 'پروژه',
  optimization: 'بهینه‌سازی',
  manual: 'دستی',
}

export const PROJECT_TYPE_FA: Record<string, string> = {
  renovation: 'بازسازی',
  new_build: 'نوسازی',
  redesign: 'بازطراحی',
  repair: 'تعمیر',
}

export const DOMAIN_FA: Record<string, string> = {
  appliance: 'لوازم برقی',
  bathroom: 'سرویس بهداشتی',
  furniture: 'مبلمان',
  kitchen: 'آشپزخانه',
}

export const QUALITY_FA: Record<string, string> = {
  low: 'اقتصادی',
  medium: 'متوسط',
  high: 'بالا',
  ultra: 'لوکس',
}

export const STYLE_FA: Record<string, string> = {
  modern: 'مدرن',
  classic: 'کلاسیک',
  minimal: 'مینیمال',
  industrial: 'صنعتی',
}
