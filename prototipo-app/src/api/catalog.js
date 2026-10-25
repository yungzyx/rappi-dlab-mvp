// Lecturas del catálogo (/catalog de rappi-ia): tiendas, productos, restaurantes, ofertas y Home, ya en el formato del
// prototipo. Las pantallas las llaman con `useApi`; si fallan lanzan un `ApiError` (`status` 404 = «no está en el catálogo»,
// que cada pantalla cuenta a su manera; `offline` y `timeout` son «Sin conexión»).

import { PLACEHOLDER_IMG } from '../components/Img'
import { screenForBackend } from '../data/verticals'
import { parsePrice } from '../state/CartContext'
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

/** Restaurantes con algún plato con precio, de una cocina si se pide, por `sort` (`rating`, `eta` o `fee`). */
export async function restaurants({ cuisine, sort, limit } = {}) {
  const cards = await read('/catalog/restaurants', { cuisine, sort, limit })
  return cards.map(toPrototypeStore)
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

/** Las listas de la Home: `{ nearbyStores, fastRestaurants, lowFeeRestaurants }`. */
export async function home() {
  const reply = await read('/catalog/home')
  return {
    nearbyStores: reply.nearby_stores.map(toPrototypeStore),
    fastRestaurants: reply.fast_restaurants.map(toPrototypeStore),
    lowFeeRestaurants: reply.low_fee_restaurants.map(toPrototypeStore),
  }
}
