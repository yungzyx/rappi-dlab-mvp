// Lecturas del catálogo (/catalog de rappi-ia): tiendas, productos, restaurantes, ofertas y Home, ya en el formato del
// prototipo. Las pantallas las llaman con `useApi`; si fallan lanzan un `ApiError` (`status` 404 = «no está en el catálogo»,
// que cada pantalla cuenta a su manera; `offline` y `timeout` son «Sin conexión»).

import { PLACEHOLDER_IMG } from '../components/Img'
import { screenForBackend } from '../data/verticals'
import { parsePrice } from '../state/CartContext'
import { placeList } from './attribution'
import { request, toPrototypeProduct } from './client'

const CATALOG_TIMEOUT_MS = 10_000 // más que una pregunta al agente: una tienda grande suma precios vigentes en SQL

/** `path` con su query; lo que no viene (`undefined`, `null` o vacío) no se manda. */
function withQuery(path, params = {}) {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value != null && value !== '') query.set(key, value)
  }
  const text = query.toString()
  return text ? `${path}?${text}` : path
}

const read = (path, params) => request(withQuery(path, params), { timeout: CATALOG_TIMEOUT_MS })
const segment = encodeURIComponent

/** Nota de la API (4.6) → texto del prototipo ('4.6'); sin nota, nada. */
const ratingText = (rating) => (Number(rating) > 0 ? Number(rating).toFixed(1) : undefined)

/**
 * Tarjeta de tienda o de restaurante de la API → tarjeta del prototipo.
 * - Tienda (`logo`): `img` es su logo (`logo: true`) y `vertical` el id del prototipo.
 * - Restaurante (`cover`): la base no guarda logos, así que `img` es la foto de un plato (`logo: false`).
 * Lo que la API no sabe (tiempo, nota) queda `undefined`, y un envío de $0 también: es un dato que falta, no «envío gratis».
 * - `hours`: abierto o cerrado según lo publicado el día de la descarga (`source`: `horario` de un restaurante comparado
 *   con la hora local, o `descarga` de una tienda), nunca el estado en vivo; `null` si no se sabe.
 * - `promos`: las promos que la tienda publicó (`{ type, title, value, threshold }`); `promo`: un restaurante con algún
 *   plato rebajado.
 */
export function toPrototypeStore(card) {
  const restaurant = 'cover' in card
  const eta = card.eta || undefined
  return {
    id: card.id,
    name: card.name,
    img: (restaurant ? card.cover : card.logo) || PLACEHOLDER_IMG,
    logo: !restaurant,
    eta,
    etaIcon: eta ? 'clock' : 'none',
    vertical: restaurant ? 'restaurants' : (screenForBackend(card.vertical) ?? card.vertical),
    rating: ratingText(card.rating),
    fee: parsePrice(card.fee) > 0 ? card.fee : undefined,
    hours: card.hours ?? null,
    promos: card.promos ?? [],
    promo: Boolean(card.promo),
  }
}

/**
 * La tienda de un producto o plato de la API, para abrir su página (`push('store', { store })`): se abre por su id.
 * Un plato (`vertical: 'restaurants'`) abre el menú de su restaurante.
 */
export const storeOfProduct = (product) => ({ id: product.storeId, name: product.store, vertical: product.vertical })

/** Las tiendas de una vertical (código del backend o id del prototipo), `limit` como máximo: `{ vertical, stores }`. */
export async function verticalStores(vertical, { limit } = {}) {
  const reply = await read(`/catalog/verticals/${segment(vertical)}/stores`, { limit })
  return { vertical: screenForBackend(reply.vertical) ?? reply.vertical, stores: reply.stores.map(toPrototypeStore) }
}

/**
 * Una tienda con sus pasillos y una página de productos de uno (el primero, si no se pide):
 * `{ store, aisles: [{ id, name, products }], aisle, products, page, hasMore }`.
 */
export async function store(id, { aisle, page } = {}) {
  const reply = await read(`/catalog/stores/${segment(id)}`, { aisle, page })
  return {
    store: toPrototypeStore(reply.store),
    aisles: reply.aisles,
    aisle: reply.aisle,
    products: reply.products.map(toPrototypeProduct),
    page: reply.page,
    hasMore: reply.has_more,
  }
}

/** Un producto (`catalog_item`) o un plato (`menu_item`). */
export async function product(entityType, id) {
  return toPrototypeProduct(await read(`/catalog/products/${segment(entityType)}/${segment(id)}`))
}

/**
 * Restaurantes con algún plato con precio, de una cocina si se pide, por `sort` (`recommended`, `rating`, `eta` o `fee`),
 * con los filtros de la lista: hasta `maxEta` minutos, desde `minRating`, destacados (`top`) o con platos rebajados
 * (`promo`). Los cerrados según su horario publicado llegan al final.
 */
export async function restaurants({ cuisine, sort, limit, maxEta, minRating, top, promo } = {}) {
  const cards = await read('/catalog/restaurants', {
    cuisine,
    sort,
    limit,
    max_eta: maxEta,
    min_rating: minRating,
    top: top || undefined,
    promo: promo || undefined,
  })
  return cards.map(toPrototypeStore)
}

/** Una tienda de la comparación de `productStores` en el formato del prototipo. */
const toOfferStore = (entry) => ({
  storeId: entry.store_id,
  store: entry.store,
  logo: entry.logo || PLACEHOLDER_IMG,
  vertical: screenForBackend(entry.vertical) ?? entry.vertical,
  backendVertical: entry.vertical,
  price: entry.price,
  before: entry.before ?? undefined,
  eta: entry.eta ?? undefined,
  fee: entry.fee ?? undefined,
  available: entry.available,
  lowStock: entry.low_stock,
  bestPrice: entry.best_price,
  fastest: entry.fastest,
})

/**
 * Dónde está un producto del catálogo (`entityId`): `{ count, stores, here, similar }`. `stores`: cada tienda con su
 * precio, tiempo y envío publicados y las marcas «Mejor precio» y «Más rápido», con su lugar en la ficha
 * (`comparar-tiendas`); `here`: la tienda `storeId` (con «Pocas unidades»), o null; `similar`: si ahí está agotado, los
 * del mismo concepto que esa tienda sí tiene (`similares`). Con `substitutes`, esos mismos aunque ahí esté disponible: los
 * sustitutos de los cambios en vivo del seguimiento.
 */
export async function productStores(entityId, storeId, { substitutes = false } = {}) {
  const reply = await read(`/catalog/products/catalog_item/${segment(entityId)}/stores`, {
    store_id: storeId,
    ...(substitutes ? { sustitutos: true } : {}),
  })
  return {
    count: reply.count,
    stores: placeList(reply.stores.map(toOfferStore), { surface: 'store', origin: 'comparar-tiendas' }),
    here: reply.here ? toOfferStore(reply.here) : null,
    similar: placeList(reply.similar.map(toPrototypeProduct), { surface: 'store', origin: 'similares' }),
  }
}

// Lo que ya se revisó al agregar desde la lista de una tienda: producto@tienda → si está agotado ahí.
const stockChecks = new Map()

/**
 * ¿Está agotado este producto en su tienda? Lo dice la ficha (`productStores`: sin stock o con 0 unidades), que el
 * listado del pasillo no trae. Una vez por producto y tienda; si la API no contesta, no se sabe (false) y se vuelve a
 * preguntar la próxima vez. Un plato no tiene stock.
 */
export function soldOutHere(product) {
  if (product?.entityType !== 'catalog_item' || product.entityId == null || product.storeId == null)
    return Promise.resolve(false)
  const key = `${product.entityId}@${product.storeId}`
  if (!stockChecks.has(key))
    stockChecks.set(
      key,
      productStores(product.entityId, product.storeId).then(
        (reply) => reply.here?.available === false,
        () => {
          stockChecks.delete(key)
          return false
        },
      ),
    )
  return stockChecks.get(key)
}

/** Para los tests: olvida lo revisado. */
export const forgetStockChecks = () => stockChecks.clear()

/**
 * «Para ti» en una tienda (solo la propuesta): `{ requestId, products, basis }`, los productos de la tienda que calzan
 * con los intereses de la persona, ya con las guardias de las ofertas y marcados con su lugar (`para-ti` en la tienda:
 * abrirlos es un `recommendation_click`).
 */
export async function storeForYou(storeId, userId) {
  const reply = await read(`/catalog/stores/${segment(storeId)}/para-ti`, { user_id: userId })
  const requestId = reply.request_id ?? null
  return {
    requestId,
    basis: reply.basis ?? [],
    products: placeList(reply.products.map(toPrototypeProduct), { surface: 'store', origin: 'para-ti', requestId }),
  }
}

/** El restaurante y su menú: `{ restaurant, sections: [{ name, items }] }`. El `storeId` de un plato es el del restaurante. */
export async function menu(id) {
  const reply = await read(`/catalog/restaurants/${segment(id)}/menu`)
  return {
    restaurant: toPrototypeStore(reply.restaurant),
    sections: reply.sections.map((section) => ({ name: section.name, items: section.items.map(toPrototypeProduct) })),
  }
}

/** Productos que bajaron de precio o que su tienda rebajó, de una vertical si se pide. */
export async function deals(vertical) {
  const products = await read('/catalog/deals', { vertical })
  return products.map(toPrototypeProduct)
}

/**
 * Las listas de la Home: `{ requestId, nearbyStores, fastRestaurants, lowFeeRestaurants }`, cada tienda marcada con su lugar
 * (`placement`: su lista, su posición y el `request_id` de la respuesta) para los eventos de abrirla.
 */
export async function home() {
  const reply = await read('/catalog/home')
  const requestId = reply.request_id ?? null
  const list = (stores, origin) => placeList(stores.map(toPrototypeStore), { surface: 'home', origin, requestId })
  return {
    requestId,
    nearbyStores: list(reply.nearby_stores, 'cerca-de-ti'),
    fastRestaurants: list(reply.fast_restaurants, 'restaurantes-rapidos'),
    lowFeeRestaurants: list(reply.low_fee_restaurants, 'envio-barato'),
  }
}

// Las condiciones de compra ya pedidas, por tienda (null = la API no la conoce): el carro y el checkout las leen sin
// volver a pedirlas. Son datos del catálogo, no de la persona.
const knownTerms = new Map()
const TERMS_PER_REQUEST = 20 // api/catalog.py: hasta 20 tiendas por consulta

/**
 * Lo que el catálogo sabe de las condiciones de compra de cada tienda (`/catalog/terms`): `Map(storeId → { deliveryFee,
 * minOrder, servicePct, hours, spans } | null)`. Cada dato puede ser null (el catálogo no lo trae): el checkout pone su supuesto.
 */
export async function storeTerms(storeIds) {
  const missing = [...new Set(storeIds)].filter((id) => !knownTerms.has(id))
  for (let i = 0; i < missing.length; i += TERMS_PER_REQUEST) {
    const chunk = missing.slice(i, i + TERMS_PER_REQUEST)
    const reply = await read('/catalog/terms', { stores: chunk.join(',') })
    const found = new Map(reply.stores.map((t) => [t.store_id, t]))
    for (const id of chunk) {
      const t = found.get(id)
      knownTerms.set(
        id,
        t
          ? {
              deliveryFee: t.delivery_fee,
              minOrder: t.min_order,
              servicePct: t.service_pct,
              // Para programar: abierto o cerrado según lo publicado y, en un restaurante, sus tramos de hoy y mañana.
              hours: t.hours ?? null,
              spans: t.spans ?? null,
            }
          : null,
      )
    }
  }
  return new Map(storeIds.map((id) => [id, knownTerms.get(id) ?? null]))
}

/** Solo para los tests: olvida las condiciones ya pedidas. */
export const forgetStoreTerms = () => knownTerms.clear()
