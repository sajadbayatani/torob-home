<script setup lang="ts">
import { onMounted } from 'vue'
import { RouterLink, RouterView } from 'vue-router'

import { useSelectionStore } from '@/stores/selectionStore'
import { useCatalogStore } from '@/stores/catalogStore'
import { toPersianDigits } from '@/utils/format'

const selection = useSelectionStore()
const catalog = useCatalogStore()

onMounted(() => {
  // the product catalogue is loaded once, here, so search and its filters are
  // ready before the first query
  void catalog.load()
  if (selection.listId && !selection.list) void selection.load()
})
</script>

<template>
  <div class="flex min-h-screen flex-col">
    <header class="sticky top-0 z-20 bg-background shadow-appbar">
      <div class="mx-auto flex min-h-appbar max-w-content items-center gap-2 px-4 sm:px-6">
        <RouterLink to="/" class="flex items-center gap-2">
          <span class="grid h-9 w-9 place-items-center rounded-field bg-primary text-sm font-bold text-primary-foreground">خ</span>
          <span class="leading-tight">
            <span class="block text-sm font-bold">ترب خونه</span>
            <span class="block text-2xs text-muted-foreground">انتخاب هوشمند لوازم خانه</span>
          </span>
        </RouterLink>

        <nav class="ms-auto hidden items-center gap-1 text-sm sm:flex">
          <RouterLink :to="{ name: 'home' }" class="btn !px-3 !py-1.5">خانه</RouterLink>
          <RouterLink :to="{ name: 'search' }" class="btn !px-3 !py-1.5">جست‌وجو</RouterLink>
        </nav>

        <RouterLink
          v-if="selection.list"
          :to="{ name: 'selection', params: { id: selection.list.id } }"
          class="btn-primary relative"
          data-test="header-selection"
        >
          <span>لیست انتخاب‌ها</span>
          <span
            class="num grid h-5 min-w-5 place-items-center rounded-full bg-primary-foreground/20 px-1.5
                   text-2xs font-semibold text-primary-foreground"
          >
            {{ toPersianDigits(selection.itemsCount) }}
          </span>
        </RouterLink>
        <RouterLink v-else :to="{ name: 'home' }" class="btn-secondary">لیست انتخاب‌ها</RouterLink>
      </div>
    </header>

    <main class="mx-auto w-full max-w-content flex-1 px-4 py-8 sm:px-6">
      <RouterView />
    </main>

    <footer class="border-t border-border bg-card">
      <div class="mx-auto max-w-content px-4 py-6 text-xs text-muted-foreground sm:px-6">
        <p>
          نسخهٔ نمایشی (v0.1) — محصولات، فروشندگان و قیمت‌ها از کاتالوگ بک‌اند و
          پیشنهادهای ثبت‌شده در ترب خوانده می‌شوند؛ برآورد پروژه از قالب‌های
          نمایشی و قواعد کمّی محاسبه می‌شود.
        </p>
      </div>
    </footer>
  </div>
</template>
