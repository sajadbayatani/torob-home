<script setup lang="ts">
/**
 * "Why does this look like that?" — every AI or recommendation decision explains
 * itself. Material language: a filled container (no outline, no elevation) with
 * a 4dp radius, and a tone mapped to the theme's semantic tokens.
 */
withDefaults(
  defineProps<{
    title?: string
    lines?: string[]
    tone?: 'neutral' | 'info' | 'warn' | 'brand'
    /** test hook; several panels can appear on one page, so each needs its own */
    testId?: string
  }>(),
  { lines: () => [], tone: 'neutral', testId: 'explanation' },
)

const TONES: Record<string, string> = {
  neutral: 'bg-muted text-muted-foreground',
  info: 'bg-muted text-foreground',
  warn: 'bg-warning/12 text-warning',
  brand: 'bg-primary/8 text-primary',
}
</script>

<template>
  <aside
    v-if="lines.length"
    :data-tone="tone"
    :data-test="testId"
    class="rounded-surface px-4 py-3 text-sm leading-6"
    :class="TONES[tone]"
  >
    <p v-if="title" class="mb-1 text-sm font-semibold">{{ title }}</p>
    <ul class="space-y-1">
      <li v-for="(line, index) in lines" :key="index" class="flex gap-2">
        <span aria-hidden="true" class="mt-2.5 h-1 w-1 shrink-0 rounded-full bg-current opacity-60" />
        <span>{{ line }}</span>
      </li>
    </ul>
  </aside>
</template>
