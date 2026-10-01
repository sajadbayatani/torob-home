<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import SearchBar from '@/components/search/SearchBar.vue'
import ThinkingStates from '@/components/search/ThinkingStates.vue'
import { useThinkingStates } from '@/composables/useThinkingStates'
import AlertBox from '@/components/ui/AlertBox.vue'
import ExplanationPanel from '@/components/ui/ExplanationPanel.vue'
import { projectsApi } from '@/api/projects'
import { useSelectionStore } from '@/stores/selectionStore'
import { useSearchStore } from '@/stores/searchStore'
import { formatTomanShort, DOMAIN_FA, PROJECT_TYPE_FA } from '@/utils/format'
import type { ProjectAnalyzeResponse } from '@/types/api'

const router = useRouter()
const selection = useSelectionStore()
const search = useSearchStore()
const query = ref('')
const pending = ref<ProjectAnalyzeResponse | null>(null)
const busy = ref(false)
/** The real phase of the request in flight, and the sentence that names it. */
/**
 * `busy` is this view's, not the store's: it covers `/projects/analyze`, which
 * this view issues itself and the store knows nothing about. Reading the store's
 * `loading` here would blank the status line for the whole of that request.
 */
const thinking = useThinkingStates(() => busy.value)
const error = ref<string | null>(null)

/**
 * The product supports two starting points. They are presented as two plain
 * choices, not as a technical "intent" concept: buy one thing you can name, or
 * describe a job you want finished.
 */
const STARTING_POINTS = [
  {
    key: 'product',
    title: 'دنبال یک محصول مشخصم',
    body: 'نام محصول را بنویسید. فروشنده‌ها، قیمت‌ها و موجودی را کنار هم می‌بینید.',
    example: 'ماشین لباسشویی بوش',
  },
  {
    key: 'need',
    title: 'می‌خواهم یک کار را انجام دهم',
    body: 'کارتان را توصیف کنید. دسته‌های لازم، برآورد هزینه محاسبه می‌شود و یک فهرست کامل از انتخاب‌های پیشنهادی به شما می‌دهیم.',
    example: 'بازسازی سرویس بهداشتی ۱۲ متری، کیفیت متوسط',
  },
]

/**
 * Interpret once, then route.
 *
 * The interpretation is done by the shared search store, which is also what the
 * results view reads — so handing the query to that view does not have it
 * interpreted a second time. The route is the store's, made from the structured
 * intent, and the interpretation is passed into the project flow so the backend
 * does not ask the model about the same sentence again.
 */
async function onSubmit(text: string) {
  error.value = null
  // The preview is the last submission's project. It goes before the new query is
  // sent, so a failure below leaves nothing on screen that belongs to another
  // search — `pending` was only ever assigned on success and never cleared.
  pending.value = null
  busy.value = true
  try {
    const applied = await search.search(text)
    if (!applied) {
      // `search` already recorded the reason; stop here rather than branching on
      // a route and an intent that belong to the previous query.
      error.value = search.error ?? 'درخواست انجام نشد'
      return
    }
    if (search.route === 'project_analysis') {
      if (!search.intent) {
        error.value = 'این درخواست یک نیاز است، ولی تفسیر آن در دسترس نبود.'
        return
      }
      // The analysis is this view's own request, so it reports its own phase —
      // the store cannot know when a call it never made starts or finishes.
      search.setPhase('analysing')
      const result = await projectsApi.analyze(text, {}, search.intent)
      pending.value = result
      await selection.adopt(result.basket)
      await router.push({ name: 'project', params: { id: result.analysis.id } })
    } else {
      await router.push({ name: 'search', query: { q: text } })
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'درخواست انجام نشد'
  } finally {
    busy.value = false
    search.setPhase('idle')
  }
}

async function startWith(example: string) {
  query.value = example
  await onSubmit(example)
}
</script>

<template>
  <div class="space-y-12">
    <section class="pb-8">
      <div class="mx-auto max-w-3xl text-center">
        <p class="label">انتخاب هوشمند لوازم خانه</p>
        <h1 class="mt-3 text-3xl sm:text-4xl">برای خونه‌ت چی لازم داری؟</h1>

        <div class="mt-8">
          <SearchBar v-model="query" large :busy="busy" @submit="onSubmit">
            <template #status>
              <ThinkingStates
                :states="thinking.states.value"
                :active-index="thinking.activeIndex.value"
                :visible="thinking.visible.value"
              />
            </template>
          </SearchBar>
        </div>

        <AlertBox
          v-if="error"
          class="mt-4 text-start"
          tone="error"
          title="درخواست انجام نشد"
          action-label="تلاش دوباره"
          data-test="home-error"
          @action="onSubmit(query)"
        >
          {{ error }}
        </AlertBox>
      </div>
    </section>

    <!-- Two ways to start, shown as plain choices rather than a technical concept. -->
    <section aria-labelledby="starting-points" class="mx-auto max-w-4xl">
      <h2 id="starting-points" class="text-center text-sm font-semibold text-foreground">
        از کجا شروع کنم؟
      </h2>
      <div class="mt-5 grid gap-4 sm:grid-cols-2">
        <article
          v-for="point in STARTING_POINTS"
          :key="point.key"
          class="card flex flex-col gap-4 p-6"
          :data-test="`starting-point-${point.key}`"
        >
          <div class="flex items-center gap-4">
            <span
              aria-hidden="true"
              class="grid h-16 w-16 shrink-0 place-items-center rounded-control"
              :class="point.key === 'need' ? 'bg-brand/15 text-brand' : 'text-foreground'"
            >
              <!-- Need icon -->
              <svg
                v-if="point.key === 'need'"
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 100 100"
                class="h-16 w-16"
                fill="currentColor"
              >
                <g transform="translate(0 100) scale(0.1 -0.1)">
                  <path d="M763 828 c-5 -7 -36 -70 -68 -139 l-59 -126 -37 16 c-27 11 -35 20 -31 34 6 23 -23 54 -57 62 -55 12 -167 -22 -301 -91 -72 -37 -129 -68 -127 -70 2 -2 64 27 138 65 153 78 254 104 306 79 31 -15 41 -49 20 -67 -8 -6 -41 -16 -72 -21 -31 -5 -64 -15 -72 -22 -8 -7 -32 -49 -53 -95 -21 -45 -51 -95 -67 -110 -26 -25 -26 -26 -3 -12 14 9 39 41 56 73 16 31 33 53 37 50 4 -4 7 3 7 15 0 53 38 90 93 91 17 0 17 -2 -2 -26 -12 -15 -21 -34 -21 -43 0 -8 8 0 18 19 22 41 75 71 114 63 15 -3 43 -19 63 -37 27 -24 33 -35 25 -46 -8 -13 -10 -13 -10 3 0 10 -7 17 -17 16 -11 0 -13 -3 -5 -6 6 -2 12 -9 12 -14 0 -6 -5 -7 -12 -3 -7 4 -8 3 -4 -5 4 -6 12 -9 17 -6 5 4 9 0 9 -7 0 -18 -37 -78 -48 -78 -5 0 -19 -9 -32 -20 -13 -11 -29 -20 -37 -20 -26 0 -72 30 -78 51 -4 11 -9 18 -12 16 -2 -3 0 -15 7 -26 13 -25 8 -26 -30 -6 -16 8 -32 24 -35 36 -4 11 -9 18 -12 15 -10 -10 28 -57 54 -67 21 -8 23 -12 13 -24 -17 -21 -5 -60 22 -72 21 -10 20 -11 -22 -23 -25 -7 -83 -16 -130 -21 l-85 -8 90 4 c50 1 110 10 135 18 25 8 57 17 71 21 14 3 37 16 51 29 22 20 23 25 10 33 -22 15 -8 43 28 55 16 6 28 15 27 21 -4 19 20 19 43 0 28 -23 22 -63 -12 -80 -18 -8 -19 -11 -6 -11 25 -1 52 44 44 74 -4 14 -10 25 -14 25 -5 0 -17 7 -28 15 -18 14 -17 15 17 9 74 -12 110 46 52 83 -16 9 -30 18 -32 20 -2 1 20 54 50 118 45 96 58 115 77 115 25 0 26 7 12 44 -8 21 -16 26 -44 26 -18 0 -38 -6 -43 -12z m73 -15 c21 -28 16 -34 -23 -28 -25 3 -31 2 -19 -3 19 -8 19 -9 0 -28 -11 -11 -18 -26 -16 -32 2 -7 -1 -12 -8 -12 -6 0 -8 -5 -5 -11 4 -6 -3 -13 -16 -16 -19 -5 -20 -7 -6 -12 17 -6 16 -8 -1 -26 -10 -11 -17 -26 -14 -33 2 -6 -1 -12 -8 -12 -6 0 -8 -5 -5 -11 4 -6 -3 -13 -15 -16 -16 -4 -18 -8 -8 -14 9 -6 10 -9 1 -9 -7 0 -10 -7 -7 -15 4 -8 13 -15 22 -15 21 0 52 -30 52 -50 0 -27 -49 -40 -78 -21 -10 6 -11 13 -1 34 10 23 9 28 -14 49 l-27 23 60 124 60 123 35 -4 c19 -2 35 0 35 4 0 4 -13 8 -30 8 -16 0 -30 5 -30 10 0 17 52 11 66 -7z m-260 -487 c8 -24 -27 -56 -60 -56 -43 0 -84 49 -60 73 4 3 31 5 60 4 44 -2 55 -6 60 -21z" />
                  <path d="M515 515 c-29 -28 -34 -85 -9 -109 39 -40 104 -3 104 59 0 37 -28 75 -55 75 -9 0 -27 -11 -40 -25z m67 -2 c22 -20 23 -70 1 -95 -18 -21 -53 -24 -71 -6 -19 19 -14 76 8 98 24 24 38 25 62 3z" />
                  <path d="M517 483 c-14 -13 -6 -25 8 -13 10 9 15 9 15 1 0 -6 7 -11 15 -11 18 0 20 -26 3 -33 -10 -4 -10 -6 0 -6 23 -2 25 29 4 50 -22 20 -34 23 -45 12z" />
                  <path d="M442 450 c0 -14 2 -19 5 -12 2 6 2 18 0 25 -3 6 -5 1 -5 -13z" />
                  <path d="M628 303 c7 -3 16 -2 19 1 4 3 -2 6 -13 5 -11 0 -14 -3 -6 -6z" />
                </g>
              </svg>

              <!-- Non-need icon -->
              <svg
                v-else
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 100 100"
                class="h-16 w-16"
                fill="currentColor"
              >
                <g transform="translate(0 100) scale(0.1 -0.1)">
                  <path d="M290 614 c0 -130 2 -128 -80 -82 l-35 20 25 -21 c14 -11 40 -26 58 -32 26 -9 32 -16 32 -40 0 -25 -4 -29 -27 -29 -16 1 -45 7 -65 14 -21 8 -35 10 -32 5 8 -14 77 -29 129 -28 28 1 40 4 28 6 -23 4 -23 7 -23 149 l0 144 90 0 90 0 0 -70 0 -70 75 0 75 0 0 70 0 70 90 0 90 0 0 -255 0 -255 -109 0 -110 0 -66 50 c-36 28 -79 57 -95 65 l-30 15 20 33 c11 17 20 38 20 46 0 8 -11 -8 -25 -34 -13 -27 -23 -49 -22 -50 23 -8 180 -120 184 -131 10 -26 -7 -29 -55 -11 -77 30 -90 30 -37 3 l50 -26 -70 4 c-38 2 -61 1 -50 -1 11 -3 26 -10 33 -15 16 -14 132 10 139 29 4 10 33 13 119 13 l114 0 0 265 0 265 -265 0 -265 0 0 -116z m330 41 l0 -65 -65 0 -65 0 0 65 0 65 65 0 65 -65z" />
                  <path d="M370 455 c-29 -31 -15 -33 18 -2 23 22 24 22 38 3 11 -16 14 -17 14 -4 0 14 -19 28 -39 28 -4 0 -18 -11 -31 -25z" />
                  <path d="M637 333 c18 -2 50 -2 70 0 21 2 7 4 -32 4 -38 0 -55 -2 -38 -4z" />
                  <path d="M673 273 c15 -2 37 -2 50 0 12 2 0 4 -28 4 -27 0 -38 -2 -22 -4z" />
                  <path d="M140 214 c0 -7 52 -25 57 -20 2 2 -10 8 -26 14 -17 6 -31 9 -31 6z" />
                  <path d="M275 165 c22 -8 51 -13 65 -13 14 0 0 6 -30 13 -69 18 -88 17 -35 0z" />
                  <path d="M393 143 c9 -2 25 -2 35 0 9 3 1 5 -18 5 -19 0 -27 -2 -17 -5z" />
                </g>
              </svg>
            </span>

            <h3 class="text-sm font-semibold text-foreground">{{ point.title }}</h3>
          </div>

          <p class="text-xs leading-7 text-muted-foreground">{{ point.body }}</p>

          <button
            type="button"
            class="btn-secondary mt-auto w-full !min-h-[2.5rem] text-xs"
            :disabled="busy"
            @click="startWith(point.example)"
          >
            {{ point.example }}
          </button>
        </article>
      </div>
    </section>

    <section v-if="pending" class="card mx-auto max-w-3xl p-6" data-test="home-preview">
      <p class="label">پروژهٔ شما</p>
      <h2 class="mt-1 text-base font-semibold">
        {{ DOMAIN_FA[pending.analysis.domain] }} · {{ PROJECT_TYPE_FA[pending.analysis.project_type] }}
      </h2>
      <p class="mt-3 text-sm text-muted-foreground">برآورد هزینهٔ کل پروژه</p>
      <p class="text-2xl text-primary">
        {{ formatTomanShort(pending.analysis.estimated_total) }}
      </p>
      <RouterLink :to="{ name: 'project', params: { id: pending.analysis.id } }" class="btn-primary mt-4">
        دیدن لیست پیشنهادی
      </RouterLink>
    </section>

    <section class="card mx-auto max-w-3xl p-6">
      <h2 class="text-sm font-semibold">این نسخه چطور کار می‌کند؟</h2>
      <ExplanationPanel
        class="mt-3"
        tone="info"
        title="از پرسش شما تا فهرست انتخاب‌ها"
        :lines="[
          'پرسش شما به ساختار نیاز تبدیل می‌شود: یا جست‌وجوی محصول، یا فهرست نیاز‌های یک پروژه.',
          'الزامات پروژه از قواعد مشخص محاسبه می‌شود، نه از حدس مدل زبانی.',
          'محصول، فروشنده و قیمت فقط از کاتالوگ خوانده می‌شود؛ چیزی ساخته نمی‌شود.',
          'جمع مبالغ همیشه در سرور محاسبه می‌شود.',
        ]"
      />
    </section>
  </div>
</template>
