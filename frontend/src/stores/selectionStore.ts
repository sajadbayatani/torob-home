/**
 * Selection list store: the products the user is keeping to compare and consider.
 *
 * This is a **selection list**, not a shopping cart. Nothing here is an order,
 * nothing is reserved and no purchase is completed on our side — the user selects
 * a product, compares the sellers, and leaves for the seller themselves. The list
 * is shortlist-shaped: it feeds project optimization, so it means "products the
 * user is currently considering for a concrete need", not favourites.
 *
 * The server owns every monetary total; this store only mirrors it. The transport
 * still speaks the backend's original `basket` vocabulary — that is a legacy
 * internal name, isolated to `api/baskets.ts`, and not the user-facing concept.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { ApiError } from '@/api/client'
import { basketsApi, type AddItemInput } from '@/api/baskets'
import type { Basket, OptimizationResult } from '@/types/api'

const STORAGE_KEY = 'home-procurement.selection-id'

export const useSelectionStore = defineStore('selection', () => {
  /** the list itself; the payload type is still the backend's `Basket` */
  const list = ref<Basket | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const lastOptimization = ref<OptimizationResult | null>(null)
  const listId = ref<string | null>(localStorage.getItem(STORAGE_KEY))

  const items = computed(() => list.value?.items ?? [])
  const total = computed(() => list.value?.total ?? 0)
  const itemsCount = computed(() => list.value?.items_count ?? 0)
  const targetBudget = computed(() => list.value?.target_budget ?? null)
  const budgetGap = computed(() => list.value?.budget_gap ?? null)
  /** a list created by a project, rather than a loose one */
  const isProjectList = computed(() => list.value?.kind === 'project')

  function persist(id: string | null) {
    listId.value = id
    if (id) localStorage.setItem(STORAGE_KEY, id)
    else localStorage.removeItem(STORAGE_KEY)
  }

  async function load(id?: string) {
    const target = id ?? listId.value
    if (!target) {
      list.value = null
      return null
    }
    loading.value = true
    error.value = null
    try {
      list.value = await basketsApi.get(target)
      persist(target)
      return list.value
    } catch (e) {
      error.value = e instanceof ApiError ? e.message : 'لیست انتخاب‌ها بارگذاری نشد'
      if (e instanceof ApiError && e.status === 404) persist(null)
      list.value = null
      return null
    } finally {
      loading.value = false
    }
  }

  async function ensureList(init: { kind?: string; title?: string } = {}): Promise<string> {
    if (list.value && list.value.kind === (init.kind ?? list.value.kind)) {
      return list.value.id
    }
    const created = await basketsApi.create(init)
    list.value = created
    persist(created.id)
    return created.id
  }

  async function addItem(input: AddItemInput) {
    const id = await ensureList({ kind: input.origin === 'project' ? 'project' : 'product' })
    await basketsApi.addItem(id, input)
    await load(id)
  }

  /**
   * Select several products as one action.
   *
   * The same guarantees as {@link addItem} — one line per product, no count
   * of our own, and re-adding a product that is already there leaves it as it
   * was — but the
   * list is loaded once at the end rather than after every item. Without that, a
   * project with six recommendations cost twelve requests instead of seven, and
   * the list visibly re-rendered once per product on the way.
   *
   * @returns how many products were sent.
   */
  async function addItems(inputs: AddItemInput[]): Promise<number> {
    if (!inputs.length) return 0
    const kind =
      inputs.every((input) => input.origin === 'project') ? 'project' : 'product'
    const id = await ensureList({ kind })
    for (const input of inputs) {
      await basketsApi.addItem(id, input)
    }
    await load(id)
    return inputs.length
  }

  async function setLocked(itemId: string, isLocked: boolean) {
    if (!list.value) return
    await basketsApi.updateItem(list.value.id, itemId, { is_locked: isLocked })
    await load()
  }

  async function removeItem(itemId: string) {
    if (!list.value) return
    await basketsApi.removeItem(list.value.id, itemId)
    await load()
  }

  async function adopt(next: Basket) {
    list.value = next
    persist(next.id)
  }

  async function optimize(input: { target_budget?: number; query?: string; apply?: boolean }) {
    if (!list.value) return null
    loading.value = true
    error.value = null
    try {
      const result = await basketsApi.optimize(list.value.id, input)
      lastOptimization.value = result
      if (result.basket) list.value = result.basket
      return result
    } catch (e) {
      error.value = e instanceof ApiError ? e.message : 'بهینه‌سازی انجام نشد'
      return null
    } finally {
      loading.value = false
    }
  }

  /**
   * Remove the whole list.
   *
   * The server deletes the project analysis along with the list, so the project
   * title and the original query go with it. Local state and the stored id are
   * dropped as well, so a reload cannot resurrect a basket the user just emptied.
   * Returns whether the basket is now gone; the caller navigates, because routing
   * is the view's job and must not be needed to test this.
   */
  async function clearList(): Promise<boolean> {
    const id = list.value?.id ?? listId.value
    if (!id) {
      reset()
      return true
    }
    loading.value = true
    error.value = null
    try {
      await basketsApi.clear(id)
      reset()
      return true
    } catch (e) {
      error.value = e instanceof ApiError ? e.message : 'لیست انتخاب‌ها پاک نشد'
      return false
    } finally {
      loading.value = false
    }
  }

  function reset() {
    list.value = null
    lastOptimization.value = null
    error.value = null
    persist(null)
  }

  return {
    list,
    listId,
    loading,
    error,
    lastOptimization,
    items,
    total,
    itemsCount,
    targetBudget,
    budgetGap,
    isProjectList,
    load,
    ensureList,
    addItem,
    addItems,
    setLocked,
    removeItem,
    adopt,
    clearList,
    optimize,
    reset,
  }
})
