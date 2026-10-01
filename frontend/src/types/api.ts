/**
 * Shared types.
 *
 * Money is always an integer amount of Toman.
 *
 * Products come from the backend's catalogue through `/api/v1/products/*`. The
 * frontend does not know where the backend keeps it. The catalogue is narrower
 * than the old seeded payload, so the fields it does not carry are nullable and
 * the UI hides them: there is no quality, style, warranty, delivery time or
 * rating.
 */

export type Intent = 'PRODUCT_SEARCH' | 'NEED_SEARCH' | 'UNKNOWN'
export type Quality = 'low' | 'medium' | 'high' | 'ultra'
export type Domain = 'appliance' | 'bathroom' | 'furniture' | 'kitchen'
export type ProjectType = 'renovation' | 'new_build' | 'redesign' | 'repair'
export type Availability =
  | 'in_stock'
  | 'low_stock'
  | 'preorder'
  | 'out_of_stock'
export type ConstraintKind =
  | 'BUDGET'
  | 'QUALITY'
  | 'STYLE'
  | 'AREA'
  | 'PRIORITY'
  | 'NONE'
export type ItemOrigin = 'search' | 'project' | 'optimization' | 'manual'

export interface Seller {
  id: string
  slug: string
  name: string
  city: string | null
  is_demo: boolean
}

export interface Offer {
  id: string
  seller: Seller
  price: number
  original_price: number | null
  availability: Availability
  available: boolean
  /** null when the catalogue does not carry it; the UI omits the column. */
  stock_count: number | null
  delivery_days: number | null
  warranty_months: number | null
  url: string | null
  /** The seller record's own wording, not an ISO timestamp. */
  price_updated_at: string | null
  /** Torob flags some prices as unreliable; such an offer is ranked last. */
  is_price_unreliable?: boolean
  guarantee_status?: string | null
}

export interface Category {
  id: string
  slug: string
  name: string
  domain: Domain
  kind: string
  description_fa: string | null
  product_count: number
}

export interface Brand {
  id: string
  slug: string
  name: string
  name_en: string | null
  country: string | null
}

export interface ProductAttribute {
  key: string
  label: string
  value: string
  value_num: string | number | null
  unit: string | null
}

export interface Product {
  id: string
  slug: string
  name: string
  subtitle: string | null
  brand: Brand | null
  category: Category
  domain: Domain
  /** Catalogue fields, kept as they are on disk. */
  subcategory: string
  model: string | null
  image_url: string
  source_url: string | null
  /** null across the board: the catalogue carries none of these. */
  quality: Quality | null
  quality_fa: string | null
  style: string | null
  unit: string | null
  rating: string | number | null
  warranty_months: number | null
  origin_country: string | null
  attributes: ProductAttribute[]
  offers: Offer[]
  offers_count: number
  min_price: number | null
  max_price: number | null
  available_offers_count: number
  is_demo: boolean
  match_score: number | null
}

export interface ProductDetail extends Product {
  description: string | null
  reference_price: number
}

/**
 * A "similar product", picked deterministically by the backend from the
 * catalogue: same subcategory first, then same brand.
 */
export interface SimilarProduct {
  product: Product
  match_type: 'same_subcategory' | 'same_brand' | 'same_category'
  reason: string
}

/**
 * A complementary product.
 *
 * `product_id` is the id the backend validated against the catalogue. The model
 * only ever sees a bounded candidate set and only ever returns ids, so an id it
 * invented is discarded server-side and can never arrive here.
 */
export interface ComplementaryProduct {
  product_id: string
  product: Product
  reason: string
  source: 'llm' | 'heuristic'
}

export interface ComplementaryResponse {
  items: ComplementaryProduct[]
  llm_available: boolean
  candidate_count: number
  note: string | null
  discarded_ids: string[]
}

export interface FacetValue {
  value: string
  label: string
  count: number
}

export interface Facets {
  categories: FacetValue[]
  brands: FacetValue[]
  subcategories: FacetValue[]
}

export interface ProductSearchItem {
  product: Product
  matched_terms: string[]
  reasons: string[]
}

export interface ProductSearchResponse {
  query: string
  total: number
  limit: number
  offset: number
  detected_category: string | null
  /** Human label for `detected_category`, so a deterministic search still reads well. */
  detected_category_name: string | null
  detected_domain: Domain | null
  intent: string | null
  items: ProductSearchItem[]
  facets: Facets
  explanations: string[]
  suggestions: string[]
}

export interface ProductQuery {
  text: string
  tokens: string[]
  raw_brand: string | null
  brand_id: string | null
  brand_name: string | null
  category_slug: string | null
  category_name: string | null
  domain: Domain | null
  quality: Quality | null
  style: string | null
}

export interface RequirementSpec {
  area_m2: number | null
  quality: Quality | null
  style: string | null
  budget: number | null
  priorities: string[]
  extra: Record<string, string | number | boolean>
}

export interface InterpretedIntent {
  intent: Intent
  domain: Domain | null
  project_type: ProjectType | null
  template_slug: string | null
  product_query: ProductQuery | null
  requirements: RequirementSpec
  constraint_kind: ConstraintKind
  confidence: number
  interpreter: string
  explanations: string[]
  /**
   * Catalogue subcategories the interpreter matched, already verified against
   * the catalogue by the backend. An empty list means nothing the shop stocks
   * was recognised — the model never gets to name a slug we do not have.
   */
  matched_subcategories: string[]
  /**
   * Things this need would normally require that the catalogue does not stock.
   * Shown to the user as a gap; never turned into a product.
   */
  missing_categories: string[]
  /** The room the user named, in their own words. */
  room: string | null
  /** What the user wants to achieve, in their own words. */
  goal: string | null
}

export interface BasketItem {
  id: string
  product: Product
  offer: Offer
  unit_price: number
  line_total: number
  role: string
  origin: ItemOrigin
  is_locked: boolean
  reason: string | null
  replaced_item_id: string | null
  is_best_price: boolean
  best_price: number | null
  alternative_count: number
  alternative_min_price: number | null
}

export interface Basket {
  id: string
  kind: 'product' | 'project'
  title: string | null
  currency: string
  items: BasketItem[]
  items_count: number
  total: number
  project_id: string | null
  target_budget: number | null
  budget_gap: number | null
  within_budget: boolean | null
  intent: InterpretedIntent | null
  notes: string | null
  created_at: string
  updated_at: string
}

export interface OptimizationChange {
  item: string
  item_id: string
  role: string
  from_product: string
  from_product_id: string
  to_product: string
  to_product_id: string
  from_price: number
  to_price: number
  saving: number
  reason: string
  quality_from: string
  quality_to: string
}

export interface OptimizationResult {
  original_total: number
  /** absent when the project states no budget, so there is no ceiling to work to */
  target_budget: number | null
  optimized_total: number
  saved: number
  within_budget: boolean
  unfilled_gap: number
  changes: OptimizationChange[]
  applied: boolean
  /** true when the plan found a real change: over budget, with a valid cheaper
   *  alternative. Drives the accept action and the button's enabled state.
   *  Optional so payloads written before these fields still typecheck. */
  can_optimize?: boolean
  /** true when the selected products as they stand exceed the target budget */
  over_budget?: boolean
  basket: Basket | null
  explanation: string
  trade_offs: string[]
}

export interface ProjectConstraints {
  area_m2?: number | null
  quality?: Quality | null
  style?: string | null
  budget?: number | null
  priorities?: string[]
}

export interface RecommendedCategory {
  role: string
  label: string
  category: Category
  /** how many units of this need the project takes — a project quantity, not a
   *  product one, and the reason it survives the removal of item quantity */
  quantity: number
  unit: string
  is_required: boolean
  quality_min: Quality
  reason: string
  /** always true: this row is a need of the project, decided from project
   *  context alone and never withdrawn for want of a product */
  project_need: boolean
  /** whether the catalogue can actually cover this need. Independent of
   *  project_need: a need with no match is kept and reported as unavailable */
  catalog_match: boolean
  /** kept for existing consumers; always equal to catalog_match */
  in_catalog: boolean
  /** fixed wording shown when the need cannot be met here */
  note: string | null
  /** machine-readable companion to note: not_stocked or not_suitable.
   *  null when the need is met. */
  unavailable_reason: 'not_stocked' | 'not_suitable' | null
}

/**
 * One optimization: the project as it now stands, plus explicit
 * proposals. Both come from the same reasoning step.
 */
export interface ProjectOptimizeResponse {
  analysis: ProjectAnalysis
  basket: Basket
  budget_status: Record<string, number | boolean | null>
  optimization: OptimizationResult
}

export interface ProjectCandidate {
  role: string
  label: string
  /** as `RecommendedCategory.quantity`: a project requirement count */
  quantity: number
  unit: string
  product: Product
  offer: Offer
  unit_price: number
  line_total: number
  seller_name: string
  reason: string
  quality: Quality
  quality_fa: string
}

export interface ProjectAnalysis {
  id: string
  template_slug: string
  title: string
  domain: Domain
  project_type: ProjectType
  area_m2: number | null
  quality: Quality
  quality_fa: string
  style: string | null
  budget: number | null
  requirements: ProjectConstraints
  estimated_total: number
  confidence: number
  interpreter: string
  interpretation: InterpretedIntent
  categories: RecommendedCategory[]
  /** the subcategories of our catalogue that are relevant to this project */
  available_categories: Category[]
  candidates: ProjectCandidate[]
  /** advice only — never added to the selection list, and not a requirement */
  complementary: ProjectCandidate[]
  missing_categories: RecommendedCategory[]
  basket_id: string | null
  explanations: string[]
  created_at: string
}

export interface ProjectAnalyzeResponse {
  analysis: ProjectAnalysis
  basket: Basket
  budget_status: Record<string, number | boolean | null>
}

export interface ProjectTemplate {
  id: string
  slug: string
  name: string
  domain: Domain
  project_type: ProjectType
  description_fa: string | null
  requirement_count: number
}
