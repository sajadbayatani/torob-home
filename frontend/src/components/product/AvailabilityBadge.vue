<script setup lang="ts">
/**
 * Availability badge.
 * `in_stock` → success, `low_stock`/`preorder` → warning, `out_of_stock` → muted.
 */
import { computed } from 'vue'

import type { Availability } from '@/types/api'
import { AVAILABILITY_FA } from '@/utils/format'

const props = defineProps<{ availability: Availability; available: boolean }>()

const label = computed(() => AVAILABILITY_FA[props.availability] ?? props.availability)

const tone = computed(() => {
  if (!props.available) return 'bg-muted text-muted-foreground'
  if (props.availability === 'low_stock') return 'bg-warning/15 text-warning'
  if (props.availability === 'preorder') return 'bg-accent text-foreground'
  return 'bg-success/15 text-success'
})
</script>

<template>
  <span class="chip" :class="tone" data-test="availability">
    <span aria-hidden="true" class="h-1.5 w-1.5 rounded-full bg-current" />
    {{ label }}
  </span>
</template>
