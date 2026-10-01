import { http } from './client'
import type { InterpretedIntent } from '@/types/api'

/**
 * Where a search goes, decided by the backend from the catalogue.
 *
 * Free, and called before anything else. `product` means the catalogue can
 * account for every meaningful word in the query, so it is answered with no
 * inference at all; `llm` means it could not decide, and only then is the model
 * asked what the person actually wants.
 */
export interface SearchRoutingDecision {
  route: 'product' | 'llm'
  is_product: boolean
  explained: string[]
  unexplained: string[]
  reason: string
}

/** Intent interpretation — reached only when the deterministic router is unsure. */
export const searchApi = {
  route(query: string) {
    return http.get<SearchRoutingDecision>('/search/route', { q: query })
  },
  interpret(query: string) {
    return http.post<InterpretedIntent>('/search/interpret', { query })
  },
}
