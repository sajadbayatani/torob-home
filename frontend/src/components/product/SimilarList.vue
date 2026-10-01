<script setup lang="ts">
/**
 * A "similar products" row, chosen deterministically by the backend from the
 * catalogue: same subcategory first, then the same brand, then the same
 * top-level category. Nothing here is generated — every item is a catalogue
 * product the API returned.
 */
import CatalogueImage from '@/components/product/CatalogueImage.vue'
import PriceTag from '@/components/ui/PriceTag.vue'
import type { SimilarProduct } from '@/types/api'

defineProps<{ items: SimilarProduct[] }>()
const emit = defineEmits<{ (e: 'add', item: SimilarProduct): void }>()

/** How the match was decided, in Persian. */
const MATCH_FA: Record<string, string> = {
  same_subcategory: 'همان دسته',
  same_brand: 'همان برند',
  same_category: 'همان دسته‌بندی',
}
</script>

<template>
  <section v-if="items.length" class="space-y-3" data-test="similar-products">
    <h2 class="text-sm font-semibold">محصولات مشابه</h2>

    <ul class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <li
        v-for="item in items"
        :key="item.product.id"
        class="card flex gap-3 p-3"
        data-test="similar-item"
      >
        <RouterLink
          :to="{ name: 'product', params: { id: item.product.id } }"
          class="shrink-0 overflow-hidden rounded-field bg-muted"
          tabindex="-1"
          aria-hidden="true"
        >
          <CatalogueImage
            :src="item.product.image_url"
            :alt="item.product.name"
            class="h-20 w-20 object-contain"
            :width="80"
            :height="80"
          />
        </RouterLink>

        <div class="flex min-w-0 flex-1 flex-col">
          <RouterLink
            :to="{ name: 'product', params: { id: item.product.id } }"
            class="clamp-2 text-sm font-medium leading-7 hover:text-primary"
          >
            {{ item.product.name }}
          </RouterLink>
          <p class="mt-1 text-2xs leading-6 text-muted-foreground">
            {{ MATCH_FA[item.match_type] ?? item.match_type }} — {{ item.reason }}
          </p>
          <div class="mt-auto flex items-center justify-between gap-2 pt-1">
            <PriceTag :value="item.product.min_price" size="sm" />
            <button
              type="button"
              class="btn-secondary !px-3 !py-1.5 text-xs"
              @click="emit('add', item)"
            >
              افزودن
            </button>
          </div>
        </div>
      </li>
    </ul>
  </section>
</template>
