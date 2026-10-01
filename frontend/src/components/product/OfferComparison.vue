<script setup lang="ts">
/**
 * Seller comparison — the heart of the product page.
 *
 * Same product, different sellers, different prices. On narrow screens the table
 * becomes a stacked list so nothing needs horizontal scrolling; on wider screens
 * it stays a real table with a header.
 */
import { computed } from 'vue'

import AvailabilityBadge from './AvailabilityBadge.vue'
import PriceTag from '@/components/ui/PriceTag.vue'
import type { Offer } from '@/types/api'
import { faNumber } from '@/utils/format'

const props = defineProps<{ offers: Offer[] }>()
const emit = defineEmits<{ (e: 'choose', offer: Offer): void }>()

const cheapest = computed(() =>
  props.offers
    .filter((offer) => offer.available)
    .reduce<number | null>((min, offer) => (min === null || offer.price < min ? offer.price : min), null),
)

const spread = computed(() => {
  const prices = props.offers.map((offer) => offer.price)
  return prices.length > 1 ? Math.max(...prices) - Math.min(...prices) : 0
})

const saving = computed(() =>
  cheapest.value === null ? null : Math.max(...props.offers.map((o) => o.price)) - cheapest.value,
)

/** Show a column only when at least one seller record actually carries it. */
const hasDeliveryColumn = computed(() => props.offers.some((offer) => offer.delivery_days != null))
const hasWarrantyColumn = computed(() => props.offers.some((offer) => offer.warranty_months != null))
</script>

<template>
  <section class="card overflow-hidden" data-test="offer-comparison">
    <header class="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3">
      <h2 class="text-sm font-semibold">مقایسهٔ فروشندگان</h2>
      <p class="text-xs leading-6 text-muted-foreground">
        اختلاف قیمت: <PriceTag :value="spread" size="sm" tone="primary" />
      </p>
    </header>

    <!-- stacked list: phones and narrow viewports -->
    <ul class="divide-y divide-border md:hidden">
      <li
        v-for="offer in offers"
        :key="offer.id"
        class="space-y-2 px-4 py-3"
        :class="offer.price === cheapest ? 'bg-primary/10' : ''"
        data-test="offer-row"
      >
        <div class="flex items-start justify-between gap-4">
          <div class="min-w-0">
            <p class="truncate text-sm font-medium">{{ offer.seller.name }}</p>
            <p v-if="offer.seller.city" class="text-xs text-muted-foreground">{{ offer.seller.city }}</p>
          </div>
          <div class="shrink-0 text-end">
            <PriceTag :value="offer.price" size="md" />
            <p v-if="offer.price === cheapest" class="mt-0.5 text-2xs font-medium text-primary">
              کمترین قیمت
            </p>
          </div>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <AvailabilityBadge :availability="offer.availability" :available="offer.available" />
          <!-- the catalogue has no delivery or warranty figure: shown only when present -->
          <span v-if="offer.delivery_days" class="text-xs text-muted-foreground">
            ارسال <span class="num">{{ faNumber(offer.delivery_days) }}</span> روز
          </span>
          <span v-if="offer.warranty_months" class="text-xs text-muted-foreground">
            گارانتی <span class="num">{{ faNumber(offer.warranty_months) }}</span> ماه
          </span>
          <span v-if="offer.is_price_unreliable" class="chip text-2xs">قیمت نیازمند تأیید</span>
          <button
            type="button"
            class="btn-secondary ms-auto !px-3 !py-1.5 text-xs"
            :disabled="!offer.available"
            @click="emit('choose', offer)"
          >
            انتخاب
          </button>
        </div>
      </li>
    </ul>

    <!-- real table: md and up -->
    <div class="hidden md:block">
      <table class="w-full text-start text-sm">
        <caption class="sr-only">
          مقایسهٔ قیمت و موجودی فروشندگان برای این محصول
        </caption>
        <thead class="bg-muted text-xs text-muted-foreground">
          <tr>
            <th scope="col" class="px-4 py-2 font-medium">فروشنده</th>
            <th scope="col" class="px-4 py-2 font-medium">قیمت</th>
            <th scope="col" class="px-4 py-2 font-medium">موجودی</th>
            <th v-if="hasDeliveryColumn" scope="col" class="px-4 py-2 font-medium">ارسال</th>
            <th v-if="hasWarrantyColumn" scope="col" class="px-4 py-2 font-medium">گارانتی</th>
            <th scope="col" class="px-4 py-2"><span class="sr-only">انتخاب</span></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="offer in offers"
            :key="offer.id"
            class="border-t border-border"
            :class="offer.price === cheapest ? 'bg-primary/10' : ''"
            data-test="offer-row"
          >
            <th scope="row" class="px-4 py-3 text-start font-medium">
              {{ offer.seller.name }}
              <span v-if="offer.seller.city" class="block text-xs font-normal text-muted-foreground">
                {{ offer.seller.city }}
              </span>
            </th>
            <td class="px-4 py-3">
              <PriceTag :value="offer.price" size="sm" />
              <span v-if="offer.price === cheapest" class="mt-1 block text-2xs font-medium text-primary">
                کمترین قیمت
              </span>
            </td>
            <td class="px-4 py-3">
              <AvailabilityBadge :availability="offer.availability" :available="offer.available" />
            </td>
            <td v-if="hasDeliveryColumn" class="px-4 py-3 text-muted-foreground">
              <span class="num">{{ faNumber(offer.delivery_days) }}</span> روز
            </td>
            <td v-if="hasWarrantyColumn" class="px-4 py-3 text-muted-foreground">
              <span class="num">{{ faNumber(offer.warranty_months) }}</span> ماه
            </td>
            <td class="px-4 py-3 text-end">
              <button
                type="button"
                class="btn-secondary !px-3 !py-1.5 text-xs"
                :disabled="!offer.available"
                @click="emit('choose', offer)"
              >
                انتخاب
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <p class="border-t border-border bg-muted px-4 py-2 text-xs leading-6 text-muted-foreground">
      <template v-if="saving && saving > 0">
        با خرید از ارزان‌ترین فروشنده <PriceTag :value="saving" size="sm" tone="primary" /> کمتر پرداخت
        می‌کنید.
      </template>
      <template v-else-if="offers.length">
        همهٔ فروشندگان این محصول یک قیمت دارند.
      </template>
      <template v-else>
        برای این محصول پیشنهاد فروشنده‌ای ثبت نشده است.
      </template>
    </p>
  </section>
</template>
