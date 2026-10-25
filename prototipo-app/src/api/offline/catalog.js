// `/catalog/*` sin conexión (api/catalog.py): las listas y páginas grabadas en la muestra. Lo que la muestra no tiene
// responde 404, como un producto o una tienda que no está en el catálogo.
import { entityKey } from './snapshot'
import { backendVertical } from './search'

const NOT_FOUND = { status: 404, body: { detail: 'No está en la muestra de la demo sin conexión' } }
const minutes = (eta) => Number.parseInt(eta, 10) || Number.POSITIVE_INFINITY
const pesos = (fee) => Number(String(fee ?? '').replace(/\D/g, '')) || 0
const SORTS = { eta: (a, b) => minutes(a.eta) - minutes(b.eta), fee: (a, b) => pesos(a.fee) - pesos(b.fee) }
const limitOf = (query, fallback) => Number(query.get('limit')) || fallback

/** `{ status, body }` de una ruta del catálogo, o undefined si la ruta no es del catálogo. */
export function catalogRoute(snapshot, method, path, query) {
  const catalog = snapshot.catalog
  if (method !== 'GET') return undefined
  if (path === '/catalog/home') return { body: catalog.home }
  if (path === '/catalog/restaurants') {
    const sort = query.get('sort') || 'rating'
    const cuisine = query.get('cuisine')
    const key = cuisine ? `rating|${cuisine}` : sort
    let list = catalog.restaurants[key]
    if (!list && cuisine)
      list = catalog.restaurants.rating.filter((r) =>
        r.cuisines?.some((c) => c.toLowerCase() === cuisine.toLowerCase()),
      )
    if (!list) list = [...catalog.restaurants.rating].sort(SORTS[sort] ?? (() => 0))
    return { body: list.slice(0, limitOf(query, 30)) }
  }
  if (path === '/catalog/deals') {
    const vertical = query.get('vertical')
    const code = backendVertical(vertical)
    if (vertical && !code) return NOT_FOUND
    return { body: (catalog.deals[code ?? ''] ?? []).slice(0, limitOf(query, 24)) }
  }
  let match = /^\/catalog\/verticals\/([^/]+)\/stores$/.exec(path)
  if (match) {
    const reply = catalog.verticalStores[backendVertical(decodeURIComponent(match[1]))]
    if (!reply) return NOT_FOUND
    return { body: { ...reply, stores: reply.stores.slice(0, limitOf(query, 30)) } }
  }
  match = /^\/catalog\/stores\/(\d+)$/.exec(path)
  if (match) {
    const shop = catalog.stores[match[1]]
    if (!shop) return NOT_FOUND
    const page = Number(query.get('page')) || 1
    const chosen = shop.pages[query.get('aisle')] ?? shop.pages[shop.aisles[0]?.id]
    // Solo la primera página de cada pasillo está en la muestra: «Ver más» no aparece.
    return {
      body: {
        store: shop.store,
        aisles: shop.aisles,
        aisle: chosen?.aisle ?? null,
        products: page === 1 ? (chosen?.products ?? []) : [],
        page,
        has_more: false,
      },
    }
  }
  match = /^\/catalog\/restaurants\/(\d+)\/menu$/.exec(path)
  if (match) return catalog.menus[match[1]] ? { body: catalog.menus[match[1]] } : NOT_FOUND
  match = /^\/catalog\/products\/([^/]+)\/([^/]+)$/.exec(path)
  if (match) {
    const product = snapshot.byEntity.get(entityKey(decodeURIComponent(match[1]), decodeURIComponent(match[2])))
    return product ? { body: product } : NOT_FOUND
  }
  return undefined
}
