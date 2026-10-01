<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AlertBox from '@/components/ui/AlertBox.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import ProductCard from '@/components/product/ProductCard.vue'
import SearchBar from '@/components/search/SearchBar.vue'
import ThinkingStates from '@/components/search/ThinkingStates.vue'
import { useThinkingStates } from '@/composables/useThinkingStates'
import ExplanationPanel from '@/components/ui/ExplanationPanel.vue'
import { useSelectionStore } from '@/stores/selectionStore'
import { useCatalogStore } from '@/stores/catalogStore'
import { useSearchStore } from '@/stores/searchStore'
import { projectsApi } from '@/api/projects'
import { faNumber } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const search = useSearchStore()
const selection = useSelectionStore()
const catalog = useCatalogStore()

const notice = ref<string | null>(null)

const intentLabel = computed(() => {
  switch (search.intent?.intent) {
    case 'PRODUCT_SEARCH':
      return 'جست‌وجوی محصول'
    case 'NEED_SEARCH':
      return 'نیاز یا پروژه'
    default:
      return 'نتیجهٔ جست‌وجو'
  }
})
const showSkeleton = computed(() => search.loading && !search.results)
/** The real phase of the request in flight, and the sentence that names it. */
// the store owns every request a product search makes, so its flag is the right one
const thinking = useThinkingStates(() => search.loading)

/** Filter options are counted from the catalogue itself. */
// const subcategoryOptions = computed(() => catalog.subcategoryOptions)
// const brandOptions = computed(() => catalog.brandOptions)

async function run(text: string) {
  notice.value = null
  if (text.trim().length < 2) {
    search.reset()
    return
  }
  const applied = await search.search(text)
  if (!applied) {
    // A failed search keeps its own query and reports its own error; the previous
    // search's interpretation is not a valid basis for routing this one.
    notice.value = search.error ?? 'جستجو انجام نشد.'
    return
  }

  // Routing is the store's decision, made from the interpretation it holds.
  // A project goes to the project flow, and the interpretation is handed over so
  // the backend does not ask the model to read the same sentence again.
  if (search.route === 'project_analysis') {
    if (!search.intent) {
      notice.value = 'این درخواست یک نیاز است، ولی تفسیر آن در دسترس نبود. لطفاً دوباره تلاش کنید.'
      return
    }
    const result = await projectsApi.analyze(text, {}, search.intent)
    await selection.adopt(result.basket)
    await router.push({ name: 'project', params: { id: result.analysis.id } })
    return
  }
  // A pure budget sentence belongs to the basket.
  if (search.intent?.constraint_kind === 'BUDGET' && selection.list) {
    await router.push({ name: 'selection', params: { id: selection.list.id }, query: { q: text } })
  }
}

async function reloadCatalog() {
  await catalog.load({ force: true })
  if (search.submittedQuery) await search.search(search.submittedQuery, { interpret: false })
}


watch(
  () => route.query.q,
  (value) => {
    if (typeof value === 'string' && value !== search.submittedQuery) void run(value)
  },
  { immediate: true },
)

onMounted(() => {
  // the filter options come from the backend; loading is cached, so calling this
  // from more than one place is harmless
  void catalog.load()
  if (route.query.intent === 'need' && search.isProjectIntent) {
    notice.value = 'این درخواست یک نیاز است، نه جست‌وجوی محصول. از دکمهٔ زیر پروژه را بسازید.'
  }
})
</script>

<template>
  <div class="space-y-6">
    <SearchBar :model-value="search.query" :busy="search.loading" @submit="run">
      <template #status>
        <ThinkingStates
          :states="thinking.states.value"
          :active-index="thinking.activeIndex.value"
          :visible="thinking.visible.value"
        />
      </template>
    </SearchBar>

    <AlertBox
      v-if="search.error"
      tone="error"
      title="جست‌وجو انجام نشد"
      :action-label="search.submittedQuery ? 'تلاش دوباره' : undefined"
      data-test="search-error"
      @action="run(search.submittedQuery)"
    >
      {{ search.error }}
    </AlertBox>

    <AlertBox
      v-if="catalog.isBroken && catalog.error"
      tone="error"
      title="دسته‌بندی محصولات بارگذاری نشد"
      action-label="تلاش دوباره"
      data-test="catalog-error"
      @action="reloadCatalog"
    >
      {{ catalog.error }}
    </AlertBox>

    <div v-if="search.isProjectIntent" class="rounded-overlay bg-primary/10 p-6 shadow-overlay" data-test="need-intent-hint">
      <p class="text-sm font-semibold text-primary">این یک نیاز است، نه جست‌وجوی یک محصول.</p>
      <p class="mt-1 text-xs leading-7 text-primary/80">
        برای دیدن دسته‌های لازم، تعداد و برآورد هزینه، پروژه را تحلیل کنید.
      </p>
      <RouterLink :to="{ name: 'home' }" class="btn-primary mt-3" data-test="analyze-project">
        تحلیل این نیاز
      </RouterLink>
    </div>

    <!-- loading: skeletons shaped like the results grid, so nothing jumps -->
    <div
      v-else-if="showSkeleton"
      class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
      aria-hidden="false"
      aria-busy="true"
      data-test="results-skeleton"
    >
      <div v-for="n in 6" :key="n" class="card space-y-3 p-4">
        <Skeleton class="h-3 w-24" />
        <Skeleton class="h-4 w-full" />
        <Skeleton class="h-4 w-4/5" />
        <Skeleton class="h-8 w-32" />
        <Skeleton class="h-3 w-full" />
      </div>
    </div>

    <template v-else-if="search.results">
      <header class="card p-4">
        <div class="flex flex-wrap items-center gap-2">
          <span class="chip bg-primary/15 text-primary">{{ intentLabel }}</span>
          <span v-if="search.detectedCategory" class="chip">دسته: {{ search.detectedCategory }}</span>
          <span class="chip">
            <span class="num">{{ faNumber(search.results.total) }}</span> نتیجه
          </span>
        </div>

        <ExplanationPanel
          v-if="search.results.explanations.length"
          class="mt-3"
          title="چرا این نتایج؟"
          :lines="search.results.explanations"
        />

        <p
          v-if="search.results.total === 0 && catalog.isEmpty"
          class="mt-3 text-2xs leading-6 text-muted-foreground"
          data-test="catalog-empty"
        >
          کاتالوگ محصولات خالی است.
        </p>
      </header>

      <div v-if="search.results.items.length" class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <ProductCard v-for="item in search.results.items" :key="item.product.id" :product="item.product" />
      </div>

      <EmptyState
        v-else
        icon="🔍"
        title="نتیجه‌ای پیدا نشد"
        description="در کاتالوگ محصولی با این مشخصات ثبت نشده است. عبارت کوتاه‌تر یا نام دستهٔ محصول را امتحان کنید."
      >
        <RouterLink :to="{ name: 'home' }" class="btn-secondary">نمونه‌های جست‌وجو</RouterLink>
      </EmptyState>
    </template>

    <p v-if="notice" class="text-xs leading-6 text-primary" role="status" data-test="notice">
      {{ notice }}
    </p>
  </div>
</template>
