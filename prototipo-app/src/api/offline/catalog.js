// `/catalog/*` sin conexión (api/catalog.py): las listas y páginas grabadas en la muestra. Muchos productos grabados
// (de búsquedas, preguntas y ofertas) son de tiendas o restaurantes cuya página no se grabó: esa página se abre con lo
// que la muestra trae de ellos (sampleShop). Lo que la muestra no tiene responde 404, como un producto o una tienda que
// no está en el catálogo.
import { entityKey } from './snapshot'
import { backendVertical } from './search'

const NOT_FOUND = { status: 404, body: { detail: 'No está en la muestra de la demo sin conexión' } }
const SAMPLE_SECTION = 'En la muestra de la demo'
const minutes = (eta) => Number.parseInt(eta, 10) || Number.POSITIVE_INFINITY
const pesos = (fee) => Number(String(fee ?? '').replace(/\D/g, '')) || 0
const SORTS = {
  eta: (a, b) => minutes(a.eta) - minutes(b.eta),
  fee: (a, b) => pesos(a.fee) - pesos(b.fee),
  recommended: (a, b) => (b.reviews ?? -1) - (a.reviews ?? -1),
}
const limitOf = (query, fallback) => Number(query.get('limit')) || fallback
// catalog/restaurants.py: TOP_MIN_RATING y TOP_MIN_REVIEWS ("Destacados", regla propia de la demo).
const TOP_MIN_RATING = 4.5
const TOP_MIN_REVIEWS = 100
/**
 * La demo sin conexión se presenta a cualquier hora: toda tienda y todo restaurante están abiertos. Cada respuesta
 * (index.js: route) pasa por aquí, así que también lo grabado en la muestra a la hora de la descarga (tiendas, menús,
 * listas, las tiendas de una búsqueda). Sin "Cerrado", "Abre a las…" ni "Abierto hasta las…", y sin programar a la
 * fuerza. Con la API real, abierto o cerrado sale de catalog/hours.py a la hora de cada request.
 */
const OPEN = { open: true, closes_at: null, opens_at: null, opens_tomorrow: false }
export const alwaysOpen = (value) => {
  if (Array.isArray(value)) return value.map(alwaysOpen)
  if (!value || typeof value !== 'object') return value
  return Object.fromEntries(
    Object.entries(value).map(([key, v]) => [
      key,
      key === 'hours' && v && typeof v === 'object' ? { ...v, ...OPEN } : alwaysOpen(v),
    ]),
  )
}

/** Los filtros de la lista de restaurantes (api/catalog.py: restaurant_list). */
function filtered(list, query) {
  const maxEta = Number(query.get('max_eta')) || null
  const minRating = Number(query.get('min_rating')) || null
  const top = query.get('top') === 'true'
  const promo = query.get('promo') === 'true'
  return list.filter(
    (r) =>
      (!maxEta || minutes(r.eta) <= maxEta) &&
      (!minRating || (r.rating ?? 0) >= minRating) &&
      (!top || ((r.rating ?? 0) >= TOP_MIN_RATING && (r.reviews ?? 0) >= TOP_MIN_REVIEWS)) &&
      (!promo || r.promo),
  )
}

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
    return { body: filtered(list, query).slice(0, limitOf(query, 30)) }
  }
  if (path === '/catalog/deals') {
    const vertical = query.get('vertical')
    const code = backendVertical(vertical)
    if (vertical && !code) return NOT_FOUND
    return { body: (catalog.deals[code ?? ''] ?? []).slice(0, limitOf(query, 24)) }
  }
  if (path === '/catalog/terms') return { body: { stores: storeTerms(catalog, query.get('stores')) } }
  let match = /^\/catalog\/verticals\/([^/]+)\/stores$/.exec(path)
  if (match) {
    const reply = catalog.verticalStores[backendVertical(decodeURIComponent(match[1]))]
    if (!reply) return NOT_FOUND
    return { body: { ...reply, stores: reply.stores.slice(0, limitOf(query, 30)) } }
  }
  match = /^\/catalog\/stores\/(\d+)$/.exec(path)
  if (match) {
    const shop = catalog.stores[match[1]]
    if (!shop) return sampleShop(snapshot, 'catalog_item', match[1]) ?? NOT_FOUND
    const page = Number(query.get('page')) || 1
    const chosen = shop.pages[query.get('aisle')] ?? shop.pages[shop.aisles[0]?.id]
    // Solo la primera página de cada pasillo está en la muestra: "Ver más" no aparece.
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
  if (match) {
    const found = catalog.menus[match[1]]
    return found ? { body: found } : (sampleShop(snapshot, 'menu_item', match[1]) ?? NOT_FOUND)
  }
  match = /^\/catalog\/products\/([^/]+)\/([^/]+)$/.exec(path)
  if (match) {
    const product = snapshot.byEntity.get(entityKey(decodeURIComponent(match[1]), decodeURIComponent(match[2])))
    return product ? { body: product } : NOT_FOUND
  }
  return undefined
}

/**
 * La página de una tienda (`catalog_item`) o del menú de un restaurante (`menu_item`) que la muestra no grabó, con los
 * productos que sí trae de ella (sin repetir), en un solo pasillo o sección rotulado "En la muestra de la demo". Sin
 * foto, tiempo ni nota: la muestra no los tiene. Sin ningún producto suyo, undefined (un 404).
 */
function sampleShop(snapshot, type, id) {
  const seen = new Set()
  const products = (snapshot.pool ?? []).filter((p) => {
    if (p.entity_type !== type || String(p.store_id) !== id || seen.has(p.entity_id)) return false
    seen.add(p.entity_id)
    return true
  })
  if (!products.length) return undefined
  const [first] = products
  const card = { id: Number(id), name: first.store, hours: null }
  if (type === 'menu_item')
    return {
      body: {
        restaurant: { ...card, cover: first.img ?? null, cuisines: [], promo: false },
        sections: [{ name: SAMPLE_SECTION, items: products }],
      },
    }
  const aisle = { id: 0, name: SAMPLE_SECTION, products: products.length }
  return {
    body: {
      store: { ...card, vertical: first.vertical, logo: null, promos: [] },
      aisles: [aisle],
      aisle,
      products,
      page: 1,
      has_more: false,
    },
  }
}

/**
 * `/catalog/terms` sin conexión (catalog/terms.py), en corto: la muestra guarda las tarjetas, no el `raw` de las
 * tiendas, así que solo sabe el envío de los restaurantes grabados (`fee` de su tarjeta); lo demás va en null y la app
 * pone su supuesto rotulado, como con la API real cuando el catálogo no lo trae.
 */
function storeTerms(catalog, ids) {
  return String(ids ?? '')
    .split(',')
    .map(Number)
    .filter((id) => Number.isInteger(id) && (catalog.menus[id] || catalog.stores[id]))
    .map((id) => ({
      store_id: id,
      delivery_fee: pesos(catalog.menus[id]?.restaurant?.fee) || null,
      min_order: null,
      service_pct: null,
    }))
}
