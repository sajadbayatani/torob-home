<script setup lang="ts">
/**
 * جدول ملزومات پروژه — the project's requirements as a table.
 *
 * Presentational on purpose: it receives rows from its parent and knows nothing
 * about where they came from. It fetches nothing, holds no state beyond the
 * hovered row's own formatting, and never touches the API.
 *
 * The rows are the API's own `RecommendedCategory`, used as it is. A requirement
 * has no price, no seller and no stock: `quantity` here is how much of a thing
 * the *job* takes, which is a different question from how many to buy, so the
 * table never grows a purchasing column.
 */
import { computed } from 'vue'

import type { RecommendedCategory } from '@/types/api'
import { formatToman, faNumber } from '@/utils/format'

/** How a cell's value is read. */
export type CellFormat =
  /** Prose. Persian digits are left alone; a Latin run stays Latin. */
  | 'text'
  /** A plain figure, e.g. the floor area. */
  | 'number'
  /** A requirement quantity: the figure plus the unit the project measures in. */
  | 'quantity'
  /** A monetary amount. Rendered by the project's one money formatter. */
  | 'money'
  /** Whether the need is required, and whether we can actually meet it. */
  | 'status'

export interface RequirementColumn {
  /** A field of `RecommendedCategory`. Nothing here is a shape of our own. */
  field: keyof RecommendedCategory
  header: string
  format: CellFormat
  /** Defaults to the start, which is where Persian reading begins. */
  align?: 'start' | 'end'
}

const props = withDefaults(
  defineProps<{
    rows: RecommendedCategory[]
    columns: RequirementColumn[]
    /**
     * Announced to a screen reader and left out of sight: the surrounding page
     * already carries a visible heading, and two headings saying the same thing
     * is noise rather than clarity.
     */
    caption?: string
  }>(),
  { caption: 'جدول ملزومات پروژه' },
)

const columnCount = computed(() => props.columns.length)

function cellValue(row: RecommendedCategory, column: RequirementColumn): unknown {
  return row[column.field]
}

/**
 * A figure cell only ever shows a figure.
 *
 * A column can be pointed at any field, and the model is not uniform — one field
 * holds a number, the next holds a quality enum. Formatting an enum as money
 * would print «low تومان», which is worse than saying nothing, so anything that
 * is not a finite number is left empty and the project formatters never see it.
 */
function figureOf(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/**
 * The figures in this table are read against each other — two square-metre
 * counts side by side — so they must not reflow as the digits change.
 */
const NUMERIC_FORMAT: ReadonlySet<CellFormat> = new Set<CellFormat>([
  'number',
  'quantity',
  'money',
])

const ALIGNED_END: ReadonlySet<CellFormat> = new Set<CellFormat>(['number', 'quantity', 'money'])

function isNumeric(column: RequirementColumn): boolean {
  return NUMERIC_FORMAT.has(column.format)
}

function alignOf(column: RequirementColumn): 'start' | 'end' {
  if (column.align) return column.align
  return ALIGNED_END.has(column.format) ? 'end' : 'start'
}

/** A requirement's status, in words, so it never depends on colour to be read. */
interface RequirementStatus {
  text: string
  detail: string | null
}

function statusOf(row: RecommendedCategory): RequirementStatus {
  // A need we cannot supply is still a need of the project, and saying so is the
  // whole point of this table: it is reported, not quietly dropped.
  if (!row.catalog_match) {
    const why =
      row.unavailable_reason === 'not_stocked'
        ? 'این قلم در سایت موجود نیست.'
        : row.unavailable_reason === 'not_suitable'
          ? 'کالای موجودی با این مشخصات پیدا نشد.'
          : 'در حال حاضر قابل تأمین نیست.'
    return { text: 'قابل تأمین نیست', detail: row.note ?? why }
  }
  return row.is_required
    ? { text: 'ضروری', detail: null }
    : { text: 'اختیاری', detail: null }
}
</script>

<template>
  <!--
    The scroll lives here, on the wrapper, so a narrow screen scrolls this table
    and nothing else. `max-w-full` is what keeps it from pushing the page wide.
    The region is focusable because a scroll container that cannot be reached by
    the keyboard is a scroll container some people cannot use.
  -->
  <div
    class="w-full max-w-full overflow-x-auto"
    role="region"
    tabindex="0"
    :aria-label="caption"
  >
    <table dir="rtl" class="w-full border-collapse text-sm">
      <caption class="sr-only">{{ caption }}</caption>

      <thead>
        <tr class="bg-muted">
          <th
            v-for="column in columns"
            :key="column.field"
            scope="col"
            class="whitespace-nowrap px-4 py-3 text-start text-xs font-medium text-muted-foreground"
            :class="alignOf(column) === 'end' ? 'text-end' : 'text-start'"
          >
            {{ column.header }}
          </th>
        </tr>
      </thead>

      <tbody>
        <tr v-if="!rows.length">
          <td
            :colspan="columnCount"
            class="px-4 py-8 text-center text-sm text-muted-foreground"
          >
            برای این پروژه هنوز ملزومی ثبت نشده است.
          </td>
        </tr>

        <tr
          v-for="row in rows"
          :key="row.role"
          class="border-b border-border transition-colors duration-short hover:bg-accent/40 motion-reduce:transition-none"
        >
          <td
            v-for="column in columns"
            :key="column.field"
            class="px-4 py-3 align-top"
            :class="[
              alignOf(column) === 'end' ? 'text-end' : 'text-start',
              isNumeric(column) ? 'num whitespace-nowrap text-foreground' : '',
            ]"
          >
            <!--
              A parent that needs a cell this table cannot phrase may render it
              itself; everything it does not override is formatted below, so
              there is still only one number formatter and one money formatter.
            -->
            <slot
              :name="`cell-${column.field}`"
              :row="row"
              :column="column"
              :value="cellValue(row, column)"
              :status="statusOf(row)"
            >
              <template v-if="column.format === 'status'">
                <span class="font-medium text-foreground">{{ statusOf(row).text }}</span>
                <span
                  v-if="statusOf(row).detail"
                  class="block text-xs leading-6 text-muted-foreground"
                >
                  {{ statusOf(row).detail }}
                </span>
              </template>

              <!-- A quantity is a figure and the unit the project measures in. -->
              <template v-else-if="column.format === 'quantity'">
                {{ faNumber(figureOf(row.quantity)) }}
                <span class="text-muted-foreground">{{ row.unit }}</span>
              </template>

              <!-- Money, from the project's own formatter: «۳۰٬۰۰۰٬۰۰۰ تومان». -->
              <template v-else-if="column.format === 'money'">
                {{ formatToman(figureOf(cellValue(row, column))) }}
              </template>

              <template v-else-if="column.format === 'number'">
                {{ faNumber(figureOf(cellValue(row, column))) }}
              </template>

              <template v-else>{{ cellValue(row, column) }}</template>
            </slot>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
