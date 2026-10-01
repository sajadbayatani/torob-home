<script setup lang="ts">
/**
 * Empty state.
 *
 * VibeFarsi pattern: say what is missing, then offer the one action that fixes
 * it. Copy is specific — never «Oops» or «something went wrong».
 */
withDefaults(
  defineProps<{
    title: string
    description?: string
    icon?: string
  }>(),
  { description: undefined, icon: undefined },
)
</script>

<template>
  <div
    data-test="empty-state"
    class="card px-6 py-12 text-center"
  >
    <span
      v-if="icon"
      aria-hidden="true"
      class="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-full bg-primary/10 text-xl"
    >
      {{ icon }}
    </span>
    <p class="text-sm font-semibold text-foreground">{{ title }}</p>
    <p v-if="description" class="mx-auto mt-2 max-w-md text-xs leading-7 text-muted-foreground">
      {{ description }}
    </p>
    <div v-if="$slots.default" class="mt-4 flex justify-center">
      <slot />
    </div>
  </div>
</template>
