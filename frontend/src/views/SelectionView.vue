<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AlertBox from '@/components/ui/AlertBox.vue'
import AvailabilityBadge from '@/components/product/AvailabilityBadge.vue'
import BudgetAmountInput from '@/components/basket/BudgetAmountInput.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import ExplanationPanel from '@/components/ui/ExplanationPanel.vue'
import PriceTag from '@/components/ui/PriceTag.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import { useSelectionStore } from '@/stores/selectionStore'
import {
  ORIGIN_FA,
  faNumber,
  formatTomanShort,
  numberToWords,
} from '@/utils/format'

const props = defineProps<{ id: string }>()
const route = useRoute()
const router = useRouter()
const selection = useSelectionStore()

const busy = ref(false)
const clearing = ref(false)
const error = ref<string | null>(null)
const notice = ref<string | null>(null)
const budgetText = ref('')
const parsedBudget = ref<number | null>(null)
const optimization = ref<typeof selection.lastOptimization>(null)

const items = computed(() => selection.items)
const total = computed(() => selection.total)
const budget = computed(() => parsedBudget.value ?? selection.targetBudget)
const gap = computed(() => (budget.value === null ? null : total.value - budget.value))
const saved = computed(() => {
  const result = optimization.value ?? selection.lastOptimization
  if (!result) return null
  return result.saved > 0 ? result.saved : null
})

/**
 * Clear the whole basket.
 *
 * The server deletes the project analysis with it, so the project title and the
 * original query go too. The route is replaced without the query as well, so a
 * reload cannot bring the project back — otherwise the header would still show
 * "بازسازی سرویس بهداشتی" above an empty basket.
 */
async function clearEverything() {
  clearing.value = true
  notice.value = null
  optimization.value = null
  budgetText.value = ''
  try {
    const cleared = await selection.clearList()
    if (cleared) {
      notice.value = 'فهرست انتخاب‌ها و پروژه پاک شد.'
      await router.replace({ name: 'home' })
    }
  } finally {
    clearing.value = false
  }
}

async function toggleLock(itemId: string, locked: boolean) {
  await selection.setLocked(itemId, locked)
}

async function remove(itemId: string) {
  busy.value = true
  try {
    await selection.removeItem(itemId)
    notice.value = 'این قلم از لیست انتخاب‌ها حذف شد.'
  } finally {
    busy.value = false
  }
}

/** The budget field already understands digits and Persian sentences. */
async function optimize() {
  const text = budgetText.value.trim()
  if (!text && parsedBudget.value === null) {
    error.value = 'اول بودجهٔ هدف را بنویسید تا انتخاب‌ها بر اساس آن بهینه شوند.'
    return
  }
  busy.value = true
  error.value = null
  try {
    const result = await selection.optimize(
      parsedBudget.value
        ? { target_budget: parsedBudget.value, apply: true }
        : { query: text, apply: true },
    )
    if (!result) {
      error.value = selection.error ?? 'بهینه‌سازی انجام نشد.'
      return
    }
    optimization.value = result
    parsedBudget.value = result.target_budget
    notice.value = 'انتخاب‌ها بهینه شد.'
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'بهینه‌سازی انجام نشد.'
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  await selection.load(props.id)
  if (typeof route.query.q === 'string' && route.query.q) {
    budgetText.value = route.query.q
    await optimize()
  }
})
</script>

<template>
  <div class="space-y-6">
    <!--
      The basket is a manifest for a job, not a shopping cart: the header states
      what it is for, then shows the total and the budget state.

      It is only rendered while the basket holds something. An empty basket gets
      the empty state below, with no project title left hanging over it.
    -->
    <header
      v-if="items.length"
      class="rounded-overlay bg-card shadow-overlay"
      data-test="basket-manifest"
    >
      <div class="rounded-overlay bg-brand/10 px-6 py-4">
        <p class="label">لیست انتخاب‌های شما</p>
        <h1 class="mt-1 text-lg font-semibold leading-snug text-foreground">
          {{ selection.list?.title ?? 'لیست انتخاب‌های من' }}
        </h1>
        <p class="mt-1 text-xs leading-6 text-muted-foreground">
          محصولاتی که برای این کار در نظر دارید، اینجا کنار هم می‌مانند. قیمت‌ها را بین فروشنده‌ها مقایسه کنید و اگر
          بودجه‌تان کمتر بود، جایگزین‌های سازگار را ببینید.
        </p>
      </div>

      <div class="flex flex-wrap items-end justify-between gap-4 px-6 py-4">
        <div class="flex flex-wrap items-center gap-2">
          <span class="chip">
            <span class="num">{{ faNumber(selection.itemsCount) }}</span> قلم
          </span>
          <span v-if="budget" class="chip">
            بودجهٔ هدف: <span class="num">{{ faNumber(budget) }}</span> تومان
          </span>
          <span v-if="saved" class="chip bg-success/15 text-success">
            <span class="num">{{ faNumber(saved) }}</span> تومان صرفه‌جویی
          </span>
        </div>
        <div class="flex shrink-0 items-end gap-3">
          <div class="text-end">
            <p class="label">برآورد کل (محاسبهٔ سرور)</p>
            <p class="text-3xl leading-tight text-primary">{{ formatTomanShort(total) }}</p>
            <p
              v-if="gap !== null"
              class="mt-1 text-xs leading-6"
              :class="gap > 0 ? 'text-warning' : 'text-success'"
            >
              <template v-if="gap > 0">{{ formatTomanShort(gap) }} بالاتر از بودجه</template>
              <template v-else>در بودجهٔ شماست</template>
            </p>
          </div>

          <button
            type="button"
            class="btn-secondary !px-3 !py-1.5 text-xs"
            :disabled="clearing"
            data-test="clear-basket"
            @click="clearEverything"
          >
            حذف کل فهرست
          </button>
        </div>
      </div>
    </header>

    <AlertBox v-if="error" tone="error" title="بهینه‌سازی انجام نشد" data-test="basket-error">
      {{ error }}
    </AlertBox>

    <div v-if="selection.loading" class="space-y-3" aria-busy="true" data-test="basket-skeleton">
      <div v-for="n in 2" :key="n" class="card space-y-3 p-4">
        <Skeleton class="h-3 w-24" />
        <Skeleton class="h-4 w-3/4" />
        <Skeleton class="h-3 w-1/2" />
        <Skeleton class="h-8 w-32" />
      </div>
    </div>

    <section v-else-if="items.length" class="space-y-3" data-test="basket-items">
      <article v-for="item in items" :key="item.id" class="card p-4">
        <div class="flex flex-wrap items-start justify-between gap-4">
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-1.5">
              <span class="chip">{{ item.product.category.name }}</span>
              <span class="chip">{{ item.product.quality_fa }}</span>
              <span class="chip">{{ ORIGIN_FA[item.origin] ?? item.origin }}</span>
            </div>
            <RouterLink
              :to="{ name: 'product', params: { id: item.product.id } }"
              class="clamp-2 mt-2 block text-sm font-semibold leading-7 text-foreground hover:text-primary"
            >
              {{ item.product.name }}
            </RouterLink>
            <p class="mt-1 text-xs leading-6 text-muted-foreground">
              فروشنده: <span class="text-foreground">{{ item.offer.seller.name }}</span> ·
              <AvailabilityBadge
                :availability="item.offer.availability"
                :available="item.offer.available"
              />
            </p>
            <p v-if="item.reason" class="mt-2 rounded-field bg-muted px-3 py-2 text-xs leading-6 text-muted-foreground">
              {{ item.reason }}
            </p>
            <p
              v-if="!item.is_best_price && item.best_price"
              class="mt-1 text-xs leading-6 text-warning"
            >
              ارزان‌ترین قیمت این محصول:
              <PriceTag :value="item.best_price" size="sm" tone="primary" />
            </p>
          </div>

          <div class="flex items-end gap-4">
            <div class="min-w-28 text-end">
              <p class="label">قیمت این محصول</p>
              <PriceTag :value="item.line_total" size="lg" tone="primary" />
            </div>
          </div>
        </div>

        <footer class="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-3 text-xs">
          <button type="button" class="btn-ghost !min-h-[2.25rem] !px-4 !py-1.5" @click="toggleLock(item.id, !item.is_locked)">
            {{ item.is_locked ? 'باز کردن قفل' : 'قفل کردن این قلم' }}
          </button>
          <button
            type="button"
            class="btn-ghost !min-h-[2.25rem] !px-4 !py-1.5 hover:bg-destructive/10 hover:text-destructive"
            :aria-label="`حذف ${item.product.name} از لیست انتخاب‌ها`"
            @click="remove(item.id)"
          >
            حذف
          </button>
          <p v-if="item.is_locked" class="text-muted-foreground">
            قلم قفل‌شده در بهینه‌سازی تغییر نمی‌کند.
          </p>
        </footer>
      </article>
    </section>

    <EmptyState
      v-else
      icon="🔖"
      title="هنوز محصولی انتخاب نکرده‌اید"
      description="هر محصولی که برای این کار در نظر دارید، از صفحهٔ محصول یا پروژه به این فهرست اضافه کنید تا فروشنده‌ها و قیمت‌هایشان را کنار هم ببینید."
      data-test="selection-empty"
    >
      <RouterLink :to="{ name: 'home' }" class="btn-primary">شروع جست‌وجو</RouterLink>
    </EmptyState>

    <section v-if="items.length" class="card p-6">
      <h2 class="text-sm font-semibold">بهینه‌سازی بودجه</h2>
      <p class="mt-1 text-xs leading-7 text-muted-foreground">
        بودجهٔ خود را بنویسید. انتخاب‌ها با جایگزین‌های سازگار و توضیح هر تغییر تنظیم می‌شوند.
      </p>
      <div class="mt-3 flex flex-wrap items-end gap-4">
        <BudgetAmountInput
          v-model="budgetText"
          class="min-w-0 flex-1"
          label="بودجهٔ هدف"
          hint="مثلاً ۵۵ میلیون، یا جملهٔ «بودجه من ۵۵ میلیون است»."
          data-test="budget-field"
          @parsed="(value) => (parsedBudget = value)"
        />
        <button type="button" class="btn-primary" :disabled="busy" data-test="optimize" @click="optimize">
          بهینه‌سازی انتخاب‌ها
        </button>
      </div>

      <section v-if="optimization" class="mt-4 space-y-3" data-test="optimization-result">
        <p class="text-xs leading-7 text-foreground">{{ optimization.explanation }}</p>
        <ul class="grid gap-2 sm:grid-cols-3">
          <li class="rounded-field bg-muted p-3 text-xs">
            <span class="label">قبل</span>
            <PriceTag :value="optimization.original_total" size="sm" />
          </li>
          <li class="rounded-field bg-muted p-3 text-xs">
            <span class="label">هدف</span>
            <PriceTag :value="optimization.target_budget" size="sm" />
          </li>
          <li class="rounded-field bg-primary/10 p-3 text-xs">
            <span class="label">بعد</span>
            <PriceTag :value="optimization.optimized_total" size="sm" tone="primary" />
            <p v-if="optimization.saved" class="mt-1 text-2xs leading-6 text-success">
              {{ numberToWords(optimization.saved) }} صرفه‌جویی
            </p>
          </li>
        </ul>
        <ul class="space-y-2">
          <li
            v-for="change in optimization.changes"
            :key="change.item_id"
            class="rounded-surface bg-muted p-4 text-xs"
            data-test="optimization-change"
          >
            <div class="flex flex-wrap items-center justify-between gap-2">
              <span class="font-medium text-foreground">{{ change.item }}</span>
              <span class="font-semibold text-success">
                <PriceTag :value="change.saving" size="sm" /> صرفه‌جویی
              </span>
            </div>
            <p class="mt-1 text-muted-foreground">
              {{ change.from_product }} ← {{ change.to_product }}
            </p>
            <p class="mt-1 text-xs leading-6 text-muted-foreground">{{ change.reason }}</p>
          </li>
        </ul>
      </section>
    </section>

    <ExplanationPanel
      tone="info"
      title="چرا این نتیجه را می‌بینید؟"
      :lines="[
        'همهٔ قیمت‌ها و جمع‌ها در سرور محاسبه می‌شود؛ مرورگر عددی را تعیین نمی‌کند.',
        'بهینه‌سازی فقط جایگزین‌های ارزان‌تر و سازگار را پیشنهاد می‌کند و دلیل هر تغییر را می‌گوید.',
        'قلم‌های قفل‌شده هرگز جایگزین نمی‌شوند.',
      ]"
    />

    <p v-if="notice" class="text-xs leading-6 text-success" role="status" data-test="notice">
      {{ notice }}
    </p>
  </div>
</template>
