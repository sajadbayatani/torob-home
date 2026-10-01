<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import AlertBox from '@/components/ui/AlertBox.vue'
import BudgetAmountInput from '@/components/basket/BudgetAmountInput.vue'
import ExplanationPanel from '@/components/ui/ExplanationPanel.vue'
import PriceTag from '@/components/ui/PriceTag.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import AvailabilityBadge from '@/components/product/AvailabilityBadge.vue'
import { projectsApi } from '@/api/projects'
import { useSelectionStore } from '@/stores/selectionStore'
import { DOMAIN_FA, PROJECT_TYPE_FA, QUALITY_FA, faNumber, formatTomanShort, numberToWords } from '@/utils/format'
import type { ProjectAnalysis, ProjectCandidate, Quality } from '@/types/api'

const props = defineProps<{ id: string }>()
const router = useRouter()
const selection = useSelectionStore()

const analysis = ref<ProjectAnalysis | null>(null)
const areaInput = ref<number | ''>('')
const budgetText = ref('')
const parsedBudget = ref<number | null>(null)
const quality = ref<Quality | ''>('')
const styleInput = ref<string | null>(null)
const loading = ref(true)
const busy = ref(false)
const error = ref<string | null>(null)
const notice = ref<string | null>(null)
const addingRole = ref<string | null>(null)
/** True while the whole project's recommendations are being selected at once. */
const addingAll = ref(false)
const optimization = ref<Awaited<ReturnType<typeof selection.optimize>>>(null)

const qualities: Quality[] = ['low', 'medium', 'high', 'ultra']

const total = computed(() => analysis.value?.estimated_total ?? 0)
/**
 * The budget shown in the results header.
 *
 * Read from the form only. It used to fall back to `analysis.budget`, which meant
 * that emptying the field still displayed — and re-sent — the previous number.
 */
const budget = computed(() => parsedBudget.value)
const overBudget = computed(() => (budget.value === null ? false : total.value > budget.value))
const saving = computed(() => {
  const result = optimization.value
  if (!result) return null
  return result.original_total - result.optimized_total
})

function hydrate(source: ProjectAnalysis) {
  analysis.value = source
  areaInput.value = source.area_m2 ?? ''
  quality.value = source.quality
  budgetText.value = ''
  parsedBudget.value = source.budget ?? null
  styleInput.value = source.style ?? null
}

async function load(id: string) {
  loading.value = true
  error.value = null
  // Cleared before the request, not after it. The template already renders its
  // "could not load" state for `error && !analysis`, which this makes reachable:
  // a failed reload used to leave the *previous* project on screen, under the
  // new id.
  analysis.value = null
  try {
    const loaded = await projectsApi.detail(id)
    hydrate(loaded)
    if (loaded.basket_id) await selection.load(loaded.basket_id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'این پروژه باز نشد.'
  } finally {
    loading.value = false
  }
}

/**
 * The values currently in the form, and nothing else.
 *
 * Each field is read from its own input, so what the user sees is what is sent.
 * A cleared field becomes `null`, which the backend reads as *cleared*: it falls
 * back to the project's own default and never to a value the user entered
 * earlier. There is deliberately no `?? analysis.budget` in here — that fallback
 * is what used to bring an emptied budget back from the dead.
 */
function currentValues() {
  return {
    area_m2: areaInput.value === '' ? null : Number(areaInput.value),
    quality: quality.value === '' ? null : quality.value,
    budget: parsedBudget.value,
    style: styleInput.value === '' ? null : styleInput.value,
  }
}

/**
 * «بهینه‌سازی» — the project's recommendations and its current basket, together.
 *
 * This is the one action the page offers. Recalculating the project and
 * optimising the basket are not two things: the server re-evaluates the
 * requirements and the recommendations from the values entered above, and the
 * basket proposals come out of the same reasoning step. The project's stored
 * interpretation is reused, so the model is not asked to read the query again.
 *
 * Nothing is written to the basket unless `apply` is set, and even then only the
 * replacements shown to the user are carried out.
 */
async function optimize(apply = false) {
  if (!analysis.value) return
  busy.value = true
  error.value = null
  if (!apply) notice.value = null
  try {
    const result = await projectsApi.optimize(analysis.value.id, currentValues(), apply)
    hydrate(result.analysis)
    await selection.adopt(result.basket)
    if (result.analysis.id !== props.id) {
      await router.replace({ name: 'project', params: { id: result.analysis.id } })
    }
    optimization.value = result.optimization
    notice.value = apply
      ? result.optimization.applied
        ? 'تغییرهای پیشنهادی اعمال شد.'
        : 'تغییری برای اعمال وجود نداشت.'
      : 'پروژه و فهرست انتخاب‌ها با همین مقادیر دوباره ارزیابی شد؛ انتخاب‌های شما تا تأییدتان تغییری نمی‌کند.'
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'بهینه‌سازی انجام نشد.'
  } finally {
    busy.value = false
  }
}

/** Apply the proposals on screen. The same action, this time confirmed. */
async function applyOptimization() {
  if (!optimization.value?.can_optimize) return
  await optimize(true)
}

/**
 * Put one recommendation in the basket — because the user asked.
 *
 * This is the only route from a recommendation to the basket. Nothing is ever
 * added automatically, which is why a project starts with an empty basket.
 */
async function addCandidate(candidate: ProjectCandidate) {
  addingRole.value = candidate.role
  error.value = null
  try {
    await selection.addItem({
      product_id: candidate.product.id,
      offer_id: candidate.offer.id,
      role: candidate.role,
      reason: candidate.reason,
      origin: 'project',
    })
    notice.value = `«${candidate.label}» به لیست انتخاب‌ها اضافه شد.`
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'به لیست انتخاب‌ها اضافه نشد.'
  } finally {
    addingRole.value = null
  }
}

/**
 * Put the whole project's recommendations in the selection list, as one action.
 *
 * The per-item buttons above remain the careful route — pick what you actually
 * want. This is the impatient one: someone who came to price a job usually wants
 * the plan in front of them and can remove anything they disagree with.
 *
 * Still an explicit action, so still nothing automatic: a project starts with an
 * empty list, and this is the click that fills it.
 */
async function addAllCandidates() {
  const candidates = analysis.value?.candidates ?? []
  if (!candidates.length) return
  addingAll.value = true
  error.value = null
  notice.value = null
  try {
    const added = await selection.addItems(
      candidates.map((candidate) => ({
        product_id: candidate.product.id,
        offer_id: candidate.offer.id,
        role: candidate.role,
        reason: candidate.reason,
        origin: 'project' as const,
      })),
    )
    notice.value = `${faNumber(added)} قلم از پیشنهادهای این پروژه به لیست انتخاب‌ها اضافه شد.`
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'پیشنهادها به لیست انتخاب‌ها اضافه نشد.'
  } finally {
    addingAll.value = false
  }
}

/** The project's needs, kept apart from what we happen to stock. */
const projectNeeds = computed(() =>
  (analysis.value?.categories ?? []).map((entry) => ({
    role: entry.role,
    label: entry.label,
    quantity: entry.quantity,
    unit: entry.unit,
    is_required: entry.is_required,
    project_need: entry.project_need,
    catalog_match: entry.catalog_match,
    note: entry.note,
    unavailable_reason: entry.unavailable_reason,
  })),
)

watch(() => props.id, (id) => void load(id), { immediate: true })
</script>

<template>
  <div class="space-y-6">
    <div v-if="loading" class="space-y-4" aria-busy="true" data-test="project-skeleton">
      <div class="card space-y-4 p-6">
        <Skeleton class="h-3 w-24" />
        <Skeleton class="h-6 w-2/3" />
        <div class="flex gap-2">
          <Skeleton class="h-6 w-20 rounded-control" />
          <Skeleton class="h-6 w-24 rounded-control" />
        </div>
      </div>
      <div class="card space-y-3 p-6">
        <Skeleton class="h-4 w-40" />
        <Skeleton class="h-3 w-full" />
        <Skeleton class="h-3 w-4/5" />
        <Skeleton class="h-3 w-3/5" />
      </div>
    </div>

    <AlertBox
      v-else-if="error && !analysis"
      tone="error"
      title="پروژه باز نشد"
      action-label="تلاش دوباره"
      data-test="project-error"
      @action="load(props.id)"
    >
      {{ error }}
    </AlertBox>

    <template v-else-if="analysis">
      <!--
        A project brief, deliberately not a product card: the band is brand
        tinted and the estimate is the hero, so this page never reads like a
        normal search result page.
      -->
      <section
        class="overflow-hidden rounded-overlay bg-card shadow-overlay"
        data-test="project-brief"
      >
        <header class="border-b border-border bg-brand/10 px-6 py-5">
          <div class="flex flex-wrap items-start justify-between gap-4">
            <div class="min-w-0">
              <p class="label">پروژهٔ شما</p>
              <h1 class="mt-1 text-xl leading-snug">{{ analysis.title }}</h1>
              <ul class="mt-3 flex flex-wrap gap-2 text-xs">
                <li class="chip bg-card">{{ DOMAIN_FA[analysis.domain] }}</li>
                <li class="chip bg-card">{{ PROJECT_TYPE_FA[analysis.project_type] }}</li>
                <li v-if="analysis.area_m2" class="chip bg-card">
                  <span class="num">{{ faNumber(analysis.area_m2) }}</span> متر مربع
                </li>
                <li class="chip bg-card">کیفیت {{ analysis.quality_fa }}</li>
              </ul>
            </div>

            <div class="shrink-0 text-end">
              <p class="label">برآورد هزینهٔ کل پروژه</p>
              <p class="text-3xl leading-tight" :class="overBudget ? 'text-warning' : 'text-primary'">
                {{ formatTomanShort(total) }}
              </p>
              <p
                v-if="budget"
                class="mt-1 text-xs leading-6"
                :class="overBudget ? 'text-warning' : 'text-success'"
              >
                <template v-if="overBudget">
                  {{ formatTomanShort(total - budget) }} بالاتر از بودجهٔ شماست
                </template>
                <template v-else>در محدودهٔ بودجهٔ شماست</template>
              </p>
            </div>
          </div>

          <p v-if="analysis.interpreter === 'rules'" class="mt-3 max-w-xl text-2xs leading-6 text-muted-foreground">
            این برآورد از قواعد پروژه و قیمت کاتالوگ به دست آمده است، نه از حدس مدل زبانی.
          </p>
        </header>

        <div class="px-6 py-4">
          <h2 class="text-sm font-semibold">نیازهای این پروژه</h2>
          <p class="mt-1 text-xs leading-6 text-muted-foreground">
            هر قلم از قواعد پروژه به دست آمده است. قلمی که در سایت موجود نیست همچنان
            نیاز پروژه است و حذف نمی‌شود.
          </p>
          <ul class="mt-3 grid gap-2 sm:grid-cols-2">
            <li
              v-for="need in projectNeeds"
              :key="need.role"
              class="flex flex-wrap items-center gap-2 rounded-field bg-muted px-4 py-2.5 text-sm"
              data-test="project-need"
            >
              <span class="font-medium text-foreground">{{ need.label }}</span>
              <!--
                A project need is a count of something the job takes ("how many
                square metres of tile"), so it stays: removing the *product*
                quantity elsewhere in the application does not reach this number,
                because the two answer different questions.
              -->
              <span class="num text-xs text-muted-foreground">
                {{ faNumber(need.quantity) }} {{ need.unit }}
              </span>

              <span v-if="need.is_required" class="chip shrink-0">ضروری</span>
              <!--
                The state is carried by a glyph and a word, not by colour alone.
                A need we cannot supply stays a need.
              -->
              <span
                v-if="need.project_need && !need.catalog_match"
                class="chip shrink-0 gap-1 !text-warning"
                data-test="need-unavailable"
              >
                <span aria-hidden="true" class="font-bold">!</span>
                {{ need.unavailable_reason === 'not_suitable'
                  ? 'برای این اتاق موجود نیست'
                  : 'در سایت موجود نیست' }}
              </span>
            </li>
          </ul>
        </div>

        <div class="border-t border-border px-6 py-4">
          <h2 class="text-sm font-semibold">تغییر محدودیت‌ها</h2>
          <div class="mt-3 grid gap-4 sm:grid-cols-3">
            <div>
              <label for="project-area" class="label mb-1 block">متراژ (متر مربع)</label>
              <input
                id="project-area"
                v-model="areaInput"
                type="number"
                min="1"
                inputmode="numeric"
                class="field"
                data-test="area-input"
              />
            </div>
            <div>
              <label for="project-quality" class="label mb-1 block">کیفیت</label>
              <select id="project-quality" v-model="quality" class="field" data-test="quality-select">
                <option value="">بدون تغییر</option>
                <option v-for="option in qualities" :key="option" :value="option">
                  {{ QUALITY_FA[option] }}
                </option>
              </select>
            </div>
            <BudgetAmountInput
              v-model="budgetText"
              label="بودجهٔ هدف"
              hint="عدد را بنویسید یا جمله‌ای مثل «بودجه من ۵۵ میلیون است»."
              data-test="budget-input"
              @parsed="parsedBudget = $event"
            />
          </div>

          <div class="mt-4 flex flex-wrap gap-2">
            <!--
              One action. It re-evaluates the project and its current basket
              together, using the values entered above; the separate
              "recalculate the basket" button is gone, because recalculating the
              project and optimising the basket are the same decision.
            -->
            <button
              type="button"
              class="btn-primary"
              :disabled="busy"
              data-test="optimize"
              @click="optimize()"
            >
              بهینه‌سازی
            </button>
            <!--
              The whole project in one click, for someone who wants the plan rather
              than a part of it. It sits with the other project-level actions
              because it acts on the project, not on one recommendation.
            -->
            <button
              type="button"
              class="btn-ghost"
              :disabled="busy || addingAll || !(analysis.candidates?.length)"
              data-test="add-all-candidates"
              @click="addAllCandidates()"
            >
              {{ addingAll ? 'در حال افزودن…' : 'افزودن همهٔ پیشنهادها به لیست انتخاب‌ها' }}
            </button>
            <RouterLink
              v-if="analysis.basket_id"
              :to="{ name: 'selection', params: { id: analysis.basket_id } }"
              class="btn-ghost"
            >
              دیدن لیست انتخاب‌ها
            </RouterLink>
          </div>
        </div>
      </section>

      <AlertBox v-if="error" tone="error" title="انجام نشد" data-test="project-inline-error">
        {{ error }}
      </AlertBox>

      <section class="card p-6">
        <h2 class="text-sm font-semibold">اقلام پیشنهادی و فروشندهٔ هر قلم</h2>

        <!-- stacked on phones: no horizontal scrolling -->
        <ul class="mt-3 space-y-3 md:hidden">
          <li
            v-for="candidate in analysis.candidates"
            :key="candidate.role"
            class="card p-4"
            data-test="candidate-card"
          >
            <div class="flex items-baseline justify-between gap-4">
              <p class="text-sm font-medium">{{ candidate.label }}</p>
              <!-- <p class="text-xs text-muted-foreground"> -->
                <!-- {{ candidate.unit }} -->
                <!-- <span class="num">{{ faNumber(candidate.quantity) }}</span>  -->
              <!-- </p> -->
            </div>
            <RouterLink
              :to="{ name: 'product', params: { id: candidate.product.id } }"
              class="clamp-2 mt-1 block text-sm leading-7 hover:text-primary"
            >
              {{ candidate.product.name }}
            </RouterLink>
            <div class="mt-1.5 flex flex-wrap items-center gap-1.5">
              <!-- <span class="chip">{{ candidate.quality_fa }}</span> -->
              <AvailabilityBadge
                :availability="candidate.offer.availability"
                :available="candidate.offer.available"
              />
              <span class="text-xs text-muted-foreground">{{ candidate.seller_name }}</span>
            </div>
            <p class="mt-2 text-xs leading-6 text-muted-foreground">{{ candidate.reason }}</p>
            <div class="mt-2 flex items-baseline justify-between gap-4 border-t border-border pt-2">
              <span class="text-xs text-muted-foreground">قیمت</span>
              <PriceTag :value="candidate.unit_price" size="sm" />
            </div>
            <!-- A recommendation is advice. Nothing reaches the basket by itself. -->
            <button
              type="button"
              class="btn-primary mt-3 w-full"
              :disabled="busy || addingRole === candidate.role"
              :data-test="`candidate-add-${candidate.role}`"
              @click="addCandidate(candidate)"
            >
              افزودن به لیست انتخاب‌ها
            </button>
          </li>
        </ul>

        <!--
          Complements satisfy no requirement of their own; they only complete the
          project. Kept in their own block so they cannot be read as needs, and
          added only by an explicit click.
        -->
        <div
          v-if="analysis.complementary?.length"
          class="mt-4 border-t border-border pt-4"
          data-test="project-complementary"
        >
          <h3 class="text-sm font-semibold">پیشنهاد مکمل</h3>
          <p class="mt-1 text-xs text-muted-foreground">
            این‌ها نیاز پروژه نیستند؛ فقط کنار انتخاب‌های شما کامل‌ترش می‌کنند.
          </p>
          <ul class="mt-2 space-y-2">
            <li
              v-for="extra in analysis.complementary"
              :key="extra.product.id"
              class="flex flex-wrap items-center justify-between gap-2 rounded-field bg-muted px-4 py-2.5 text-sm"
            >
              <RouterLink
                :to="{ name: 'product', params: { id: extra.product.id } }"
                class="clamp-2 block hover:text-primary"
              >
                {{ extra.product.name }}
              </RouterLink>
              <div class="flex items-center gap-2">
                <PriceTag :value="extra.unit_price" size="sm" />
                <button
                  type="button"
                  class="btn-secondary"
                  :disabled="busy || addingRole === extra.product.id"
                  :data-test="`complement-add-${extra.product.id}`"
                  @click="addCandidate(extra)"
                >
                  افزودن به لیست انتخاب‌ها
                </button>
              </div>
            </li>
          </ul>
        </div>

        <div class="mt-3 hidden md:block">
          <table class="w-full text-start text-sm">
            <caption class="sr-only">اقلام پیشنهادی پروژه به همراه فروشنده و قیمت</caption>
            <thead class="bg-muted text-xs text-muted-foreground">
              <tr>
                <th scope="col" class="px-3 py-2 font-medium">قلم</th>
                <th scope="col" class="px-3 py-2 font-medium">محصول</th>
                <th scope="col" class="px-3 py-2 font-medium">فروشنده</th>
                <th scope="col" class="px-3 py-2 font-medium">قیمت</th>
                <th scope="col" class="px-3 py-2 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="candidate in analysis.candidates" :key="candidate.role" class="border-t border-border align-top">
                <th scope="row" class="px-3 py-3 text-start font-medium">{{ candidate.label }}</th>
                <td class="px-3 py-3">
                  <RouterLink
                    :to="{ name: 'product', params: { id: candidate.product.id } }"
                    class="clamp-2 text-foreground hover:text-primary"
                  >
                    {{ candidate.product.name }}
                  </RouterLink>
                  <div class="mt-1 flex flex-wrap items-center gap-1.5">
                    <!-- <span class="chip">{{ candidate.quality_fa }}</span> -->
                    <AvailabilityBadge
                      :availability="candidate.offer.availability"
                      :available="candidate.offer.available"
                    />
                  </div>
                  <p class="mt-1 max-w-sm text-xs leading-6 text-muted-foreground">{{ candidate.reason }}</p>
                </td>
                <td class="px-3 py-3 text-muted-foreground">{{ candidate.seller_name }}</td>
                <td class="px-3 py-3"><PriceTag :value="candidate.unit_price" size="sm" /></td>
                <!-- <td class="px-3 py-3"><PriceTag :value="candidate.line_total" size="sm" /></td> -->
              </tr>
            </tbody>
            <tfoot>
              <tr class="border-t-2 border-border bg-muted">
                <td class="px-3 py-3 text-xs font-medium" colspan="5">برآورد کل</td>
                <td class="px-3 py-3"><PriceTag :value="total" size="md" /></td>
              </tr>
            </tfoot>
          </table>
        </div>
      </section>

      <section v-if="optimization" class="card p-6" data-test="optimization-result">
        <h2 class="text-sm font-semibold">بهینه‌سازی بودجه</h2>
        <div class="mt-3 grid gap-4 sm:grid-cols-3">
          <div class="rounded-field bg-muted p-3">
            <p class="label">قبل</p>
            <PriceTag :value="optimization.original_total" size="md" />
          </div>
          <div class="rounded-field bg-muted p-3">
            <p class="label">هدف</p>
            <PriceTag :value="optimization.target_budget" size="md" />
          </div>
          <div class="rounded-field bg-primary/10 p-3">
            <p class="label">بعد</p>
            <PriceTag :value="optimization.optimized_total" size="md" tone="primary" />
            <p v-if="saving" class="mt-1 text-2xs leading-6 text-success">
              {{ numberToWords(saving) }} صرفه‌جویی
            </p>
          </div>
        </div>

        <p class="mt-3 text-xs leading-7 text-muted-foreground">{{ optimization.explanation }}</p>

        <ul v-if="optimization.changes.length" class="mt-3 space-y-2">
          <li
            v-for="change in optimization.changes"
            :key="change.item_id"
            class="rounded-surface bg-muted p-4 text-xs"
            data-test="optimization-change"
          >
            <div class="flex flex-wrap items-center justify-between gap-2">
              <span class="font-medium">{{ change.item }}</span>
              <span class="font-semibold text-primary">
                <PriceTag :value="change.saving" size="sm" /> صرفه‌جویی
              </span>
            </div>
            <p class="mt-1 text-muted-foreground">
              {{ change.from_product }} ← {{ change.to_product }}
              <span class="text-muted-foreground">({{ change.quality_from }} به {{ change.quality_to }})</span>
            </p>
            <p class="mt-1 text-xs leading-6 text-muted-foreground">{{ change.reason }}</p>
          </li>
        </ul>

        <div
          v-if="optimization.can_optimize && !optimization.applied"
          class="mt-3 flex flex-wrap items-center gap-2"
        >
          <button
            type="button"
            class="btn-primary"
            :disabled="busy"
            data-test="optimization-apply"
            @click="applyOptimization"
          >
            اعمال این تغییرها
          </button>
          <span class="text-2xs text-muted-foreground">
            تا زمانی که تأیید نکنید، انتخاب‌های شما تغییری نمی‌کند.
          </span>
        </div>
        <p v-else-if="optimization.applied" class="mt-3 text-2xs text-success">
          تغییرها اعمال شد.
        </p>
      </section>

      <ExplanationPanel tone="info" title="این پروژه چطور ساخته شد؟" :lines="analysis.explanations" />

      <p v-if="notice" class="text-xs leading-6 text-primary" role="status" data-test="notice">
        {{ notice }}
      </p>
    </template>
  </div>
</template>
