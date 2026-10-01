<script setup lang="ts">
import { computed } from 'vue'

import AvailabilityBadge from './AvailabilityBadge.vue'
import CatalogueImage from '@/components/product/CatalogueImage.vue'
import PriceTag from '@/components/ui/PriceTag.vue'
import type { Product } from '@/types/api'
import { faNumber } from '@/utils/format'

const props = withDefaults(
  defineProps<{ product: Product; compact?: boolean; selectable?: boolean; selected?: boolean }>(),
  { compact: false, selectable: false, selected: false },
)

const emit = defineEmits<{ (e: 'select', product: Product): void }>()

const meta = computed(() =>
  [
    props.product.category.name,
    props.product.brand?.name,
    props.product.model ? `مدل ${props.product.model}` : null,
  ].filter(Boolean) as string[],
)

const visibleOffers = computed(() => props.product.offers.slice(0, 2))
</script>

<template>
  <article
    class="card group flex h-full flex-col p-4 transition-shadow hover:shadow-overlay"
    data-test="product-card"
  >
    <!-- the catalogue's own image URL: nothing is downloaded or re-hosted -->
    <RouterLink
      v-if="product.image_url && !compact"
      :to="{ name: 'product', params: { id: product.id } }"
      class="mb-4 block overflow-hidden rounded-field bg-muted"
      tabindex="-1"
      aria-hidden="true"
    >
      <CatalogueImage
        :src="product.image_url"
        :alt="product.name"
        class="aspect-square w-full object-contain"
        :width="320"
        :height="320"
        testid="product-image"
      />
    </RouterLink>

    <div class="flex items-start justify-between gap-4">
      <div class="min-w-0">
        <p class="label">{{ product.category.name }}</p>
        <RouterLink
          :to="{ name: 'product', params: { id: product.id } }"
          class="clamp-2 mt-1 block text-sm font-semibold leading-7 text-foreground hover:text-primary"
        >
          {{ product.name }}
        </RouterLink>
        <p v-if="!compact && product.subtitle" class="clamp-2 mt-1 text-xs leading-6 text-muted-foreground">
          {{ product.subtitle }}
        </p>
      </div>
      <span v-if="product.quality_fa" class="chip shrink-0">{{ product.quality_fa }}</span>
    </div>

    <ul v-if="!compact && meta.length" class="mt-3 flex flex-wrap gap-1.5">
      <li v-for="item in meta" :key="item" class="chip">{{ item }}</li>
    </ul>

    <dl v-if="!compact && product.attributes.length" class="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
      <div v-for="attribute in product.attributes.slice(0, 4)" :key="attribute.key" class="flex gap-1">
        <dt class="shrink-0 text-muted-foreground">{{ attribute.label }}:</dt>
        <dd class="truncate text-muted-foreground">{{ attribute.value }}</dd>
      </div>
    </dl>

    <div class="mt-4 flex items-end justify-between gap-4">
      <div>
        <p class="label">کمترین قیمت</p>
        <PriceTag :value="product.min_price" size="lg" />
      </div>
      <p class="text-xs leading-6 text-muted-foreground">
        <span class="num">{{ faNumber(product.available_offers_count) }}</span>
        فروشندهٔ موجود
      </p>
    </div>

    <ul v-if="!compact" class="mt-3 space-y-2 border-t border-border pt-3">
      <li
        v-for="offer in visibleOffers"
        :key="offer.id"
        class="flex items-center justify-between gap-2 text-xs"
      >
        <span class="truncate text-muted-foreground">{{ offer.seller.name }}</span>
        <span class="flex shrink-0 items-center gap-2">
          <AvailabilityBadge :availability="offer.availability" :available="offer.available" />
          <PriceTag :value="offer.price" size="sm" bare />
        </span>
      </li>
      <li v-if="product.offers_count > visibleOffers.length" class="text-2xs text-muted-foreground">
        <span class="num">{{ faNumber(product.offers_count - visibleOffers.length) }}</span>
        فروشندهٔ دیگر
      </li>
    </ul>

    <button
      v-if="selectable"
      type="button"
      class="mt-4 w-full"
      :class="selected ? 'btn-secondary' : 'btn-primary'"
      @click="emit('select', product)"
    >
      {{ selected ? 'انتخاب‌شده' : 'انتخاب' }}
    </button>
  </article>
</template>
