/**
 * Two things are gone from this product, and this is what holds them gone.
 *
 * **Related products.** The endpoint, the store function, the projection and the
 * component are removed. Nothing should reintroduce a "these go with that" list:
 * the catalogue records no compatibility claims, so any such list would be the
 * same subcategory wearing a relevance costume — which is what `similar` already
 * says it is.
 *
 * **Quantity.** A product is not a number of units. There is no count on the
 * product page, none on the selection page, none in the selection store, and none
 * in the API types — so there is no control left to increment and no way for a
 * caller to send one that the server would honour.
 *
 * What is deliberately still there: a *project requirement*'s quantity, which
 * answers a different question ("how many tiles does this job take").
 */
import { describe, expect, it } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

const SRC = join(__dirname, '..', 'src')

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name)
    if (entry.isDirectory()) return sourceFiles(path)
    return /\.(vue|ts)$/.test(entry.name) ? [path] : []
  })
}

const SOURCES = sourceFiles(SRC).map((path) => ({
  path: path.slice(SRC.length + 1),
  text: readFileSync(path, 'utf-8'),
}))

describe('related products are gone', () => {
  it('no source file mentions a related-products feature', () => {
    const offenders = SOURCES.filter((f) =>
      /RelatedProduct|RelatedList|productsApi\.related|\/related\b|related_count/.test(f.text),
    ).map((f) => f.path)
    expect(offenders).toEqual([])
  })

  it('the component file is gone', () => {
    expect(() => readFileSync(join(SRC, 'components/product/RelatedList.vue'))).toThrow()
  })

  it('the product page fetches only what it still shows', () => {
    const view = SOURCES.find((f) => f.path === 'views/ProductView.vue')!.text
    expect(view).toContain('productsApi.similar')
    expect(view).not.toContain('productsApi.related')
  })
})

describe('quantity is gone from products and selections', () => {
  it('no product or selection view has a count control', () => {
    const offenders = SOURCES.filter(
      (f) =>
        /views\/(Product|Selection)View\.vue$/.test(f.path) && /quantity|تعداد/.test(f.text),
    ).map((f) => f.path)
    expect(offenders).toEqual([])
  })

  it('the selection store cannot set a count', () => {
    const store = SOURCES.find((f) => f.path === 'stores/selectionStore.ts')!.text
    expect(store).not.toContain('setQuantity')
    expect(store).not.toContain('quantity')
  })

  it('no addItem call anywhere sends a count', () => {
    const api = SOURCES.find((f) => f.path === 'api/baskets.ts')!.text
    expect(api).not.toContain('quantity')
    // matched at the call site, not the file: a view may legitimately *display* a
    // project requirement's count, it just must not send one when selecting
    const offenders = SOURCES.flatMap((f) =>
      [...f.text.matchAll(/addItem\(\{([\s\S]*?)\}\)/g)]
        .filter((match) => match[1].includes('quantity'))
        .map(() => f.path),
    )
    expect(offenders).toEqual([])
  })

  it('the API types carry no count on a product or a selection item', () => {
    const types = SOURCES.find((f) => f.path === 'types/api.ts')!.text
    for (const block of ['export interface BasketItem', 'export interface OptimizationChange']) {
      const body = types.slice(types.indexOf(block))
      const end = body.indexOf('\n}')
      expect(body.slice(0, end)).not.toContain('quantity')
    }
    const basket = types.slice(types.indexOf('export interface Basket '))
    expect(basket.slice(0, basket.indexOf('\n}'))).not.toContain('quantity')
  })

  it('a project requirement still has its own count', () => {
    const types = SOURCES.find((f) => f.path === 'types/api.ts')!.text
    // a project needs six tiles; that is not a product quantity and it stays
    for (const block of ['export interface RecommendedCategory', 'export interface ProjectCandidate']) {
      const body = types.slice(types.indexOf(block))
      const end = body.indexOf('\n}')
      expect(body.slice(0, end)).toContain('quantity')
    }
  })
})
