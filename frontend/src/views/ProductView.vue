<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import AlertBox from '@/components/ui/AlertBox.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import CatalogueImage from '@/components/product/CatalogueImage.vue'
import OfferComparison from '@/components/product/OfferComparison.vue'
import SimilarList from '@/components/product/SimilarList.vue'
import ExplanationPanel from '@/components/ui/ExplanationPanel.vue'
import PriceTag from '@/components/ui/PriceTag.vue'
import { productsApi } from '@/api/products'
import { useSelectionStore } from '@/stores/selectionStore'
import { DOMAIN_FA, STYLE_FA, faNumber } from '@/utils/format'
import type {
  Offer,
  ProductDetail,
  SimilarProduct,
} from '@/types/api'

const props = defineProps<{ id: string }>()
const router = useRouter()
const selection = useSelectionStore()

const product = ref<ProductDetail | null>(null)
const similar = ref<SimilarProduct[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const notice = ref<string | null>(null)

async function load() {
  loading.value = true
  error.value = null
  try {
    product.value = await productsApi.detail(props.id)
    // "similar" is the one contextual section left, and it is fetched on its own so
    // a failure cannot blank the page
    const similarResult = await Promise.allSettled([productsApi.similar(props.id, 6)])
    similar.value = similarResult[0].status === 'fulfilled' ? similarResult[0].value : []
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'این محصول بارگذاری نشد.'
  } finally {
    loading.value = false
  }
}

async function addToBasket(offer?: Offer) {
  if (!product.value) return
  await selection.addItem({
    product_id: product.value.id,
    offer_id: offer?.id ?? null,
    origin: 'search',
  })
  notice.value = `به لیست انتخاب‌ها اضافه شد. ${faNumber(selection.itemsCount)} قلم در فهرست شماست.`
  await router.push({ name: 'selection', params: { id: selection.list?.id ?? '' } })
}


async function addSimilar(item: SimilarProduct) {
  await selection.addItem({ product_id: item.product.id, origin: 'search' })
  notice.value = `«${item.product.name}» به لیست انتخاب‌ها اضافه شد.`
}

onMounted(load)
</script>

<template>
  <div class="space-y-6">
    <!-- loading: skeleton shaped like the page, no centered spinner -->
    <div v-if="loading" class="space-y-4" aria-busy="true" data-test="product-skeleton">
      <Skeleton class="h-3 w-48" />
      <div class="card space-y-4 p-6">
        <Skeleton class="h-3 w-32" />
        <Skeleton class="h-6 w-3/4" />
        <div class="flex gap-2">
          <Skeleton class="h-6 w-20 rounded-control" />
          <Skeleton class="h-6 w-24 rounded-control" />
        </div>
        <Skeleton class="h-10 w-40" />
      </div>
      <div class="card space-y-3 p-6">
        <Skeleton class="h-4 w-28" />
        <Skeleton class="h-3 w-full" />
        <Skeleton class="h-3 w-2/3" />
      </div>
    </div>

    <AlertBox
      v-else-if="error"
      tone="error"
      title="محصول باز نشد"
      action-label="تلاش دوباره"
      data-test="product-error"
      @action="load"
    >
      {{ error }}
    </AlertBox>

    <template v-else-if="product">
      <nav aria-label="مسیر" class="text-xs leading-6 text-muted-foreground">
        <RouterLink :to="{ name: 'home' }" class="hover:text-primary">خانه</RouterLink>
        <span aria-hidden="true" class="mx-1">/</span>
        <span>{{ product.category.name }}</span>
        <span aria-hidden="true" class="mx-1">/</span>
        <span class="text-muted-foreground">{{ product.name }}</span>
      </nav>

      <section class="card p-6">
        <div class="flex flex-wrap items-start gap-6">
          <!-- the catalogue's own image URL; nothing is downloaded or re-hosted -->
          <div
            v-if="product.image_url"
            class="w-40 shrink-0 overflow-hidden rounded-surface bg-muted sm:w-52"
          >
            <CatalogueImage
              :src="product.image_url"
              :alt="product.name"
              class="aspect-square w-full object-contain"
              :width="320"
              :height="320"
              testid="detail-image"
            />
          </div>

          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-start justify-between gap-4">
              <div class="min-w-0 flex-1">
                <p class="label">{{ product.category.name }} · {{ DOMAIN_FA[product.domain] }}</p>
                <h1 class="mt-1 text-xl font-bold leading-tight">{{ product.name }}</h1>
                <p v-if="product.subtitle" class="mt-1 text-sm leading-7 text-muted-foreground">
                  {{ product.subtitle }}
                </p>
              </div>

              <div class="shrink-0 text-end">
                <p class="label">کمترین قیمت</p>
                <PriceTag :value="product.min_price" size="xl" />
                <p class="mt-1 text-xs leading-6 text-muted-foreground">
                  <span class="num">{{ faNumber(product.offers_count) }}</span> فروشنده ·
                  <span class="num">{{ faNumber(product.available_offers_count) }}</span> قابل خرید
                </p>
              </div>
            </div>

            <!-- only fields the catalogue actually records -->
            <dl
              class="mt-4 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2"
              data-test="product-facts"
            >
              <div class="flex items-baseline justify-between gap-3 border-b border-border py-1.5">
                <dt class="text-muted-foreground">برند</dt>
                <dd class="font-medium">
                  {{ product.brand?.name ?? '—' }}
                </dd>
              </div>
              <div class="flex items-baseline justify-between gap-3 border-b border-border py-1.5">
                <dt class="text-muted-foreground">مدل</dt>
                <dd class="font-medium">{{ product.model ?? '—' }}</dd>
              </div>
              <div class="flex items-baseline justify-between gap-3 border-b border-border py-1.5">
                <dt class="text-muted-foreground">دسته</dt>
                <dd class="font-medium">{{ product.category.name }}</dd>
              </div>
              <div class="flex items-baseline justify-between gap-3 border-b border-border py-1.5">
                <dt class="text-muted-foreground">بیشترین قیمت فروشنده</dt>
                <dd class="font-medium"><PriceTag :value="product.max_price" size="sm" /></dd>
              </div>
              <div
                v-if="product.quality_fa"
                class="flex items-baseline justify-between gap-3 border-b border-border py-1.5"
              >
                <dt class="text-muted-foreground">کیفیت</dt>
                <dd class="font-medium">{{ product.quality_fa }}</dd>
              </div>
              <div
                v-if="product.style"
                class="flex items-baseline justify-between gap-3 border-b border-border py-1.5"
              >
                <dt class="text-muted-foreground">سبک</dt>
                <dd class="font-medium">{{ STYLE_FA[product.style] ?? product.style }}</dd>
              </div>
              <div
                v-if="product.warranty_months"
                class="flex items-baseline justify-between gap-3 border-b border-border py-1.5"
              >
                <dt class="text-muted-foreground">گارانتی</dt>
                <dd class="font-medium">
                  <span class="num">{{ faNumber(product.warranty_months) }}</span> ماه
                </dd>
              </div>
              <div
                v-if="product.source_url"
                class="flex items-baseline justify-between gap-3 border-b border-border py-1.5"
              >
                <dt class="text-muted-foreground">منبع</dt>
                <dd class="font-medium">
                  <a
                    :href="product.source_url"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="text-primary underline-offset-4 hover:underline"
                  >
                    مشاهده در ترب
                  </a>
                </dd>
              </div>
            </dl>
          </div>
        </div>

        <p v-if="product.description" class="clamp-3 mt-4 max-w-2xl text-sm leading-7 text-muted-foreground">
          {{ product.description }}
        </p>

        <div class="mt-4 flex flex-wrap items-end gap-4">
          <button type="button" class="btn-primary" data-test="add-to-basket" @click="addToBasket()">
            افزودن به لیست انتخاب‌ها
          </button>
        </div>
      </section>

      <section v-if="product.attributes.length" class="card p-6">
        <h2 class="text-sm font-semibold">مشخصات</h2>
        <dl class="mt-3 grid gap-x-6 gap-y-2 sm:grid-cols-2">
          <div
            v-for="attribute in product.attributes"
            :key="attribute.key"
            class="flex items-baseline justify-between gap-4 border-b border-border py-2 text-sm"
          >
            <dt class="text-muted-foreground">{{ attribute.label }}</dt>
            <dd class="text-end font-medium">
              {{ attribute.value }}<span v-if="attribute.unit" class="text-muted-foreground"> {{ attribute.unit }}</span>
            </dd>
          </div>
        </dl>
      </section>

      <OfferComparison :offers="product.offers" @choose="addToBasket" />

      <SimilarList :items="similar" @add="addSimilar" />


      <ExplanationPanel
        tone="info"
        title="دربارهٔ قیمت‌ها"
        :lines="[
          'قیمت‌ها مستقیماً از پیشنهادهای ثبت‌شدهٔ فروشندگان در ترب خوانده می‌شود.',
          'برای هر محصول حداکثر پنج فروشندهٔ ارزان‌تر نگه داشته می‌شود.',
          'قیمت‌ها مربوط به زمان ثبت پیشنهاد است و ممکن است تغییر کند.',
        ]"
      />

      <p v-if="notice" class="text-xs leading-6 text-primary" role="status" data-test="notice">
        {{ notice }}
      </p>
    </template>
  </div>
</template>
