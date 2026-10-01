<script setup lang="ts">
/**
 * The single money display component.
 * Digits, grouping and unit placement come from `utils/format`; colour comes
 * from theme tokens (money is `primary`, muted money is `muted-foreground`).
 */
import { computed } from 'vue'

import { toPersianDigits } from '@/utils/format'

const props = withDefaults(
  defineProps<{
    value: number | null | undefined
    size?: 'sm' | 'md' | 'lg' | 'xl'
    tone?: 'default' | 'muted' | 'primary'
    suffix?: string
    /** Render without the unit (used where the unit already appears in the sentence). */
    bare?: boolean
  }>(),
  { size: 'md', tone: 'default', suffix: 'تومان', bare: false },
)

const sizeClass = computed(
  () =>
    ({
      sm: 'text-sm',
      md: 'text-base',
      lg: 'text-xl',
      xl: 'text-3xl',
    })[props.size],
)
</script>

<template>
  <span
    class="inline-flex items-baseline gap-1 font-semibold tabular-nums"
    :class="{
      'text-foreground': tone === 'default',
      'font-normal text-muted-foreground': tone === 'muted',
      'text-primary': tone === 'primary',
      [sizeClass]: true,
    }"
  >
    <span class="num">{{ value === null || value === undefined ? '—' : toPersianDigits(value) }}</span>
    <span
      v-if="!bare && value !== null && value !== undefined"
      class="text-xs font-normal text-muted-foreground"
    >
      {{ suffix }}
    </span>
  </span>
</template>
