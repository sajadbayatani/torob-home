/**
 * Catalogue store: the reactive state the views read.
 *
 * It holds no product data of its own. Every product, price and filter option
 * comes from the backend through `api/products`; this store only tracks whether
 * that call is in flight, has succeeded, or failed, and caches the filter options
 * so the results view can render them.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { productsApi } from '@/api/products'
import { ApiError } from '@/api/client'
import type { FacetValue, Facets } from '@/types/api'

export type CatalogStatus = 'idle' | 'loading' | 'ready' | 'error'

const EMPTY_FACETS: Facets = { categories: [], brands: [], subcategories: [] }

export const useCatalogStore = defineStore('catalog', () => {
  const status = ref<CatalogStatus>('idle')
  const error = ref<string | null>(null)
  const facets = ref<Facets>(EMPTY_FACETS)

  const isLoading = computed(() => status.value === 'loading' || status.value === 'idle')
  const isReady = computed(() => status.value === 'ready')
  const isBroken = computed(() => status.value === 'error')
  /** The catalogue loaded but holds no subcategory at all. */
  const isEmpty = computed(() => isReady.value && facets.value.subcategories.length === 0)
  /** Filter options, as the backend counted them from its catalogue. */
  const subcategoryOptions = computed<FacetValue[]>(() => facets.value.subcategories)
  const brandOptions = computed<FacetValue[]>(() => facets.value.brands)
  const categoryOptions = computed<FacetValue[]>(() => facets.value.categories)

  /**
   * Load the filter options. Safe to call more than once: the options are cached
   * once loaded, and `force` re-reads them.
   */
  async function load(options: { force?: boolean } = {}) {
    if (isReady.value && !options.force) return
    status.value = 'loading'
    error.value = null
    try {
      facets.value = await productsApi.facets()
      status.value = 'ready'
    } catch (e) {
      facets.value = EMPTY_FACETS
      status.value = 'error'
      error.value =
        e instanceof ApiError ? e.message : 'دسته‌بندی محصولات بارگذاری نشد. دوباره تلاش کنید.'
    }
  }

  return {
    status,
    error,
    facets,
    isLoading,
    isReady,
    isBroken,
    isEmpty,
    subcategoryOptions,
    brandOptions,
    categoryOptions,
    load,
  }
})
