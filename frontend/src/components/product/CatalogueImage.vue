<script setup lang="ts">
/**
 * A catalogue product image, loaded straight from the URL the catalogue carries.
 *
 * Nothing is downloaded, resized or re-hosted: the catalogue's own `image_url` is
 * the source, so a product always looks the way the seller published it.
 *
 * The image host may be unreachable — a network that blocks it, a corporate
 * proxy, or a CDN that refuses the request. A broken-image icon in the middle of
 * a product grid reads as a bug in the shop, so a failure falls back to a quiet
 * placeholder and the product name carries the card instead.
 */
import { ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    src: string | null | undefined
    alt: string
    class?: string
    width?: number
    height?: number
    testid?: string
  }>(),
  { src: null, class: '', width: 320, height: 320 },
)

const failed = ref(false)

// a new product means a new URL, so the failure state must not stick
watch(
  () => props.src,
  () => {
    failed.value = false
  },
)
</script>

<template>
  <img
    v-if="src && !failed"
    :src="src"
    :alt="alt"
    :class="props.class"
    :width="width"
    :height="height"
    loading="lazy"
    decoding="async"
    :data-test="testid"
    @error="failed = true"
  />
  <!-- neutral, and the same shape as the image it replaces, so nothing jumps -->
  <span
    v-else
    :class="props.class"
    :data-test="testid ? `${testid}-fallback` : 'product-image-fallback'"
    :aria-hidden="src ? 'true' : undefined"
    :role="src ? undefined : 'img'"
    :aria-label="src ? undefined : alt"
  >
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="1.5"
      class="h-1/3 w-1/3 text-muted-foreground/60"
      aria-hidden="true"
    >
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <circle cx="8.5" cy="8.5" r="1.5" />
      <path d="m21 15-5-5L5 21" />
    </svg>
  </span>
</template>
