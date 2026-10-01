<script setup lang="ts">
/**
 * Inline alert, expressed with Material language: a filled container, a 4dp
 * corner radius and 8dp elevation (the MD2 elevation the spec assigns to menus
 * and raised panels). Errors announce themselves with `role="alert"`; anything
 * else is a polite status so a screen reader is not interrupted by a notice.
 */
withDefaults(
  defineProps<{
    tone?: 'error' | 'warn' | 'info' | 'success'
    title?: string
    actionLabel?: string
  }>(),
  { tone: 'info', title: undefined, actionLabel: undefined },
)

const emit = defineEmits<{ (e: 'action'): void }>()

/** Container tint, text colour and the rail that carries the tone. */
const TONES: Record<string, string> = {
  error: 'bg-destructive/8 text-destructive',
  warn: 'bg-warning/12 text-warning',
  info: 'bg-muted text-foreground',
  success: 'bg-success/8 text-success',
}
</script>

<template>
  <div
    :role="tone === 'error' ? 'alert' : 'status'"
    aria-live="polite"
    data-test="alert"
    :data-tone="tone"
    class="flex flex-wrap items-start gap-3 overflow-hidden rounded-surface bg-card p-4 shadow-overlay"
  >
    <span
      aria-hidden="true"
      class="w-1 self-stretch shrink-0 rounded-full"
      :class="{
        'bg-destructive': tone === 'error',
        'bg-warning': tone === 'warn',
        'bg-foreground/40': tone === 'info',
        'bg-success': tone === 'success',
      }"
    />
    <div :class="['min-w-0 flex-1 rounded-surface px-3 py-1', TONES[tone]]">
      <p v-if="title" class="text-sm font-semibold">{{ title }}</p>
      <div class="text-sm leading-7"><slot /></div>
    </div>
    <button
      v-if="actionLabel"
      type="button"
      class="btn-secondary shrink-0 !min-h-button !px-4 text-xs"
      @click="emit('action')"
    >
      {{ actionLabel }}
    </button>
  </div>
</template>
