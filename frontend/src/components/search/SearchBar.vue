<script setup lang="ts">
import { ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{ modelValue?: string; large?: boolean; busy?: boolean }>(),
  { modelValue: '', large: false, busy: false },
)
const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'submit', value: string): void
}>()


const local = ref(props.modelValue)
/** True while a Persian/Latin IME session is open. */
const composing = ref(false)

watch(
  () => props.modelValue,
  (value) => {
    if (value !== local.value) local.value = value
  },
)

function submit(value?: string) {
  const text = (value ?? local.value).trim()
  // Never submit mid-composition: Enter is what commits a Persian syllable.
  // `busy` is checked here rather than on a disabled button, because the button is
  // gone: Enter is now the only way to run a search, and a second one mid-flight
  // would supersede the first rather than wait for it.
  if (props.busy || text.length < 2 || composing.value) return
  emit('update:modelValue', text)
  emit('submit', text)
}

// function pick(example: string) {
//   local.value = example
//   submit(example)
// }
</script>

<template>
  <form class="space-y-3" data-test="search-bar" @submit.prevent="submit()">
    <div
      class="flex items-center gap-3 rounded-md bg-card px-3 shadow-control
             transition-shadow duration-short ease-motion focus-within:shadow-d4"
      :class="large ? 'min-h-14 py-2' : 'min-h-field py-1.5'"
    >
      <svg aria-hidden="true" class="h-5 w-5 shrink-0 text-foreground" viewBox="0 0 20 20" fill="none">
        <circle cx="9" cy="9" r="6" stroke="currentColor" stroke-width="1.5" />
        <path d="m13.5 13.5 3 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
      </svg>

      <input
        v-model="local"
        type="search"
        :placeholder="large ? 'مثلاً: بازسازی سرویس بهداشتی ۱۲ متری، کیفیت متوسط' : 'جست‌وجوی محصول یا نیاز خانه'"
        class="min-h-[var(--control-size)] w-full bg-transparent py-2 text-base text-foreground outline-none"
        aria-label="جست‌وجوی محصول یا نیاز خانه"
        autocomplete="off"
        data-test="search-input"
        :disabled="busy"
        @compositionstart="composing = true"
        @compositionend="composing = false"
      />


      <!--
        No visible button: this is a search field, and Enter is how a search is run.
        A submit control is still present because a form with no submit button is not
        reliably submitted by every browser, and a submit with no accessible name is
        an unnamed control — so it carries the field's own label and is hidden from
        sight rather than dropped.
      -->
      <button type="submit" class="sr-only" data-test="search-submit">جست‌وجو</button>
    </div>

    <!--
      A slot for live status about the search in flight (the thinking states).
      Outside the flex row rather than inside it, so the sentence cannot squeeze
      the field, and so the input keeps its own width and its 16px type — the size
      that stops iOS Safari zooming when the field takes focus.
    -->
    <div v-if="$slots.status" class="px-1">
      <slot name="status" />
    </div>
  </form>
</template>
