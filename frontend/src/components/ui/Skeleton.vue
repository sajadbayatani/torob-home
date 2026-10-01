<script setup lang="ts">
/**
 * Skeleton placeholder.
 *
 * VibeFarsi pattern: a pulsing block that reserves the shape of the final
 * content, so async data never shifts the layout. Always `aria-hidden`; the
 * surrounding region carries the accessible busy/loading state.
 *
 * Sizing comes from the caller's `class`, which Vue merges onto the root
 * element: `<Skeleton class="h-4 w-24" />`.
 */
</script>

<template>
  <div
    aria-hidden="true"
    data-test="skeleton"
    class="animate-pulse rounded-control bg-muted motion-reduce:animate-none"
  />
</template>
