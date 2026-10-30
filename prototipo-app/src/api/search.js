// Búsqueda híbrida de rappi-ia (`GET /search`), en el formato del prototipo.
import { screenForBackend } from '../data/verticals'
import { placeList } from './attribution'
import { toPrototypeStore } from './catalog'
import { request, toPrototypeProduct } from './client'

const SEARCH_TIMEOUT_MS = 8_000

const groupOf = (backendVertical, prototypeVertical, products) => ({
  // El id de la vertical en la app (el mismo de sus pantallas y del carrito); el código del backend va aparte.
  vertical: prototypeVertical ?? screenForBackend(backendVertical) ?? backendVertical,
  backendVertical,
  products: products.map(toPrototypeProduct),
})

/**
 * Busca `q` en el catálogo: `{ query, requestId, scope, groups: [{ vertical, backendVertical, products }], unmet,
 * unmetReason, correctedQuery }` (`query`: lo que se buscó, para saber a qué texto pertenece una respuesta;
 * `requestId`: el id de la respuesta, que es el de la búsqueda en sus eventos; `scope`: `global` o `vertical`). Cada
 * producto lleva su lugar en los resultados (`placement`, ver attribution.js).
 * - Sin `vertical`, busca en las verticales que corresponden a la consulta (más `current`, la de la pantalla) y
 *   devuelve un grupo por vertical, en el orden de la API. `limit` es por grupo.
 * - Con `vertical` (id del prototipo o código del backend), busca solo ahí y devuelve un único grupo.
 * - Si nada calzaba, la API corrige los errores de tipeo y busca de nuevo: `correctedQuery` es lo que buscó (null si
 *   no corrigió). Con `exact`, busca `q` tal cual.
 * - Sin `vertical`, también las tiendas y los restaurantes que se llaman así o son de esa cocina (`places: { stores,
 *   restaurants }`, cada uno con su lugar); si no hubo nada, `whimAllowed` dice si se puede ofrecer "Lo que sea"
 *   (RappiFavor) con lo escrito, según las guardias de la API.
 * - Con `userId` (solo en la propuesta), la dieta y las alergias que la persona le dijo a Mochi filtran los resultados
 *   (como en Mochi, sin ordenar por sus favoritas) y `preferencesNotice` lo dice (null si no filtró).
 * Un mismo producto puede salir en varios grupos con el mismo `id`: las llaves de la lista deben incluir la vertical.
 */
export async function searchAll(q, { vertical, current, limit, exact, userId } = {}) {
  const params = new URLSearchParams({ q })
  if (vertical) params.set('vertical', vertical)
  else if (current) params.set('current', current)
  if (limit) params.set('limit', String(limit))
  if (exact) params.set('correct', 'false')
  if (userId) params.set('user_id', userId)
  const response = await request(`/search?${params}`, { timeout: SEARCH_TIMEOUT_MS })
  const requestId = response.request_id ?? null
  const found = response.groups
    ? response.groups.map((g) => groupOf(g.vertical, g.prototype_vertical, g.products))
    : [groupOf(response.vertical, null, response.products ?? [])]
  // Cada producto con su lugar en los resultados: la posición cuenta de corrido, grupo tras grupo, como se muestran.
  let start = 0
  const groups = found.map((group) => {
    const products = placeList(group.products, { surface: 'search', origin: 'resultados', requestId, start })
    start += products.length
    return { ...group, products }
  })
  const places = (cards, origin) =>
    placeList((cards ?? []).map(toPrototypeStore), { surface: 'search', origin, requestId })
  return {
    query: q,
    requestId,
    scope: vertical ? 'vertical' : 'global',
    groups,
    places: {
      stores: places(response.places?.stores, 'resultados-tiendas'),
      restaurants: places(response.places?.restaurants, 'resultados-restaurantes'),
    },
    whimAllowed: Boolean(response.whim_allowed),
    unmet: Boolean(response.unmet),
    unmetReason: response.unmet_reason ?? null,
    correctedQuery: response.corrected_query ?? null,
    preferencesNotice: response.preferences_notice ?? null,
  }
}

/**
 * Lo que el buscador muestra antes de escribir: `{ recent, top, population, requestId }`. `recent`: las búsquedas
 * recientes de la persona; `top`: "Lo más buscado" de la población que declara la API (`population`: `synthetic` o
 * `prototype`, nunca mezcladas).
 */
export async function searchSuggestions(userId) {
  const reply = await request(`/profile/${encodeURIComponent(userId)}/busquedas`, { timeout: 4000 })
  return {
    recent: reply.recientes ?? [],
    top: reply.mas_buscado ?? [],
    population: reply.poblacion ?? null,
    requestId: reply.request_id ?? null,
  }
}
