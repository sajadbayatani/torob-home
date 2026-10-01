/**
 * Transport for the selection list.
 *
 * The backend still models this as a `Basket` and the endpoints are still
 * `/baskets/...` — that is a legacy internal name, kept because renaming the
 * model would mean a risky migration for no user-visible gain. The user-facing
 * concept is «لیست انتخاب‌ها»; everything above this file uses that word, and
 * this is the only place the old vocabulary appears.
 */
import { http } from './client'
import type { Basket, BasketItem, OptimizationResult } from '@/types/api'

export interface AddItemInput {
  product_id: string
  offer_id?: string | null
  role?: string
  reason?: string | null
  origin?: string
  is_locked?: boolean
}

export const basketsApi = {
  create(input: { kind?: string; title?: string; product_id?: string } = {}) {
    return http.post<Basket>('/baskets', input)
  },
  get(basketId: string) {
    return http.get<Basket>(`/baskets/${basketId}`)
  },
  addItem(basketId: string, input: AddItemInput) {
    return http.post<BasketItem>(`/baskets/${basketId}/items`, input)
  },
  updateItem(basketId: string, itemId: string, input: Partial<AddItemInput>) {
    return http.patch<BasketItem>(`/baskets/${basketId}/items/${itemId}`, input)
  },
  /** Remove the whole basket, and the project analysis behind it. */
  clear(basketId: string) {
    return http.delete<void>(`/baskets/${basketId}`)
  },
  removeItem(basketId: string, itemId: string) {
    return http.delete<void>(`/baskets/${basketId}/items/${itemId}`)
  },
  optimize(basketId: string, input: { target_budget?: number; query?: string; apply?: boolean }) {
    return http.post<OptimizationResult>(`/baskets/${basketId}/optimize`, input)
  },
}
