/**
 * The façade the views use for product data.
 *
 * The frontend does not know where the backend keeps its catalogue. It knows the
 * API contract: products, sellers and prices are read from `/api/v1/products/*`,
 * and the backend owns the catalogue file. Nothing here fetches or imports the
 * catalogue itself.
 */
import { http } from './client'
import type {
  Category,
  ComplementaryResponse,
  Facets,
  ProductDetail,
  ProductSearchResponse,
  SimilarProduct,
} from '@/types/api'

export interface ProductSearchParams {
  q: string
  limit?: number
  offset?: number
  domain?: string
  /** A catalogue subcategory slug, e.g. `refrigerator`. */
  category?: string
  /** A brand name, exactly as the catalogue records it. */
  brand?: string
  onlyAvailable?: boolean
  /** Ask the backend to interpret the query as well (default: yes). */
  interpret?: boolean
}

export const productsApi = {
  /** Search the catalogue. The response keeps the shape the results view expects. */
  search(params: ProductSearchParams): Promise<ProductSearchResponse> {
    return http.get<ProductSearchResponse>('/products/search', {
      q: params.q,
      limit: params.limit ?? 20,
      offset: params.offset ?? 0,
      domain: params.domain,
      category: params.category,
      brand: params.brand,
      only_available: params.onlyAvailable ? 'true' : undefined,
      interpret: params.interpret === false ? 'false' : undefined,
    })
  },

  /** One product, with its sellers. */
  detail(productId: string): Promise<ProductDetail> {
    return http.get<ProductDetail>(`/products/${productId}`)
  },

  /** Same-kind products. */

  /** The subcategories the catalogue actually contains. */
  categories(domain?: string): Promise<Category[]> {
    return http.get<Category[]>('/categories', { domain })
  },

  /**
   * Similar products, chosen deterministically by the backend from the
   * catalogue: same subcategory first, then same brand.
   */
  similar(productId: string, limit = 6): Promise<SimilarProduct[]> {
    return http.get<SimilarProduct[]>(`/products/${productId}/similar`, { limit })
  },

  /**
   * Complementary products. The backend picks a bounded candidate set from the
   * catalogue, lets the model choose from it by id, and validates every returned
   * id before answering.
   */
  complementary(productId: string, limit = 6): Promise<ComplementaryResponse> {
    return http.get<ComplementaryResponse>(`/products/${productId}/complementary`, { limit })
  },

  /** The filter options, counted by the backend from its catalogue. */
  facets(): Promise<Facets> {
    return http.get<Facets>('/products/facets')
  },
}
