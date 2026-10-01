<script setup lang="ts">
/**
 * Budget amount field.
 *
 * Re-implementation of the VibeFarsi `amount-input` pattern in Vue 3:
 * the raw text is kept, the number is re-rendered with Persian digits and «٬»,
 * the unit sits after the number, and the understood amount is spelled out
 * underneath so the user can confirm it before submitting.
 *
 * It also accepts a full Persian sentence («بودجه من ۵۵ میلیون است») because the
 * optimiser understands natural language too.
 */
import { computed, useId } from 'vue'

import { numberToWords, parseToman, toPersianDigits } from '@/utils/format'

const props = withDefaults(
  defineProps<{
    modelValue: string
    label: string
    hint?: string
    placeholder?: string
    disabled?: boolean
  }>(),
  { hint: undefined, placeholder: '۵۵ میلیون', disabled: false },
)

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'parsed', amount: number | null): void
}>()

const uid = useId()
const inputId = computed(() => `amount-${uid}`)
const describedBy = computed(() => (props.hint || parsed.value ? `${inputId.value}-help` : undefined))

/** Only digits and separators may be regrouped; anything else is left as typed. */
const PLAIN_NUMBER = /^[\d۰-۹\s.,٬٫]+$/

/**
 * Re-group plain numbers with Persian digits, and leave anything containing a
 * scale word («۵۵ میلیون») or a full sentence exactly as the user typed it, so the
 * magnitude the field displays always matches the budget that is used.
 */
const displayValue = computed(() => {
  const raw = props.modelValue
  if (!raw) return ''
  if (!PLAIN_NUMBER.test(raw)) return raw
  const digits = raw.replace(/[^\d۰-۹]/g, '')
  if (!digits) return raw
  const latin = digits.replace(/[۰-۹]/g, (d) => String('۰۱۲۳۴۵۶۷۸۹'.indexOf(d)))
  const value = Number(latin)
  return Number.isFinite(value) ? toPersianDigits(value) : raw
})

const parsed = computed(() => parseToman(props.modelValue))
const words = computed(() => numberToWords(parsed.value))
const hasText = computed(() => props.modelValue.trim().length > 0)
const invalid = computed(() => hasText.value && parsed.value === null)

function onInput(event: Event) {
  const value = (event.target as HTMLInputElement).value
  emit('update:modelValue', value)
  emit('parsed', parseToman(value))
}
</script>

<template>
  <div class="min-w-0">
    <label :for="inputId" class="label mb-1 block">{{ label }}</label>

    <div class="relative">
      <input
        :id="inputId"
        :value="displayValue"
        type="text"
        inputmode="text"
        autocomplete="off"
        :placeholder="placeholder"
        :disabled="disabled"
        :aria-invalid="invalid || undefined"
        :aria-describedby="describedBy"
        class="field text-start"
        data-test="amount-input"
        @input="onInput"
      />
      <span
        aria-hidden="true"
        class="pointer-events-none absolute inset-y-0 end-3 flex items-center text-xs text-muted-foreground"
      >
        تومان
      </span>
    </div>

    <p
      v-if="words"
      :id="`${inputId}-help`"
      class="mt-1.5 text-xs leading-6 text-muted-foreground"
      data-test="amount-words"
    >
      {{ words }}
    </p>
    <p v-else-if="hint" :id="`${inputId}-help`" class="mt-1.5 text-xs leading-6 text-muted-foreground">
      {{ hint }}
    </p>
    <p
      v-if="invalid"
      class="mt-1.5 text-xs leading-6 text-danger"
      role="alert"
      data-test="amount-error"
    >
      عدد را به رقم فارسی یا لاتین بنویسید، یا جمله‌ای مثل «بودجه من ۵۵ میلیون است».
    </p>
  </div>
</template>
