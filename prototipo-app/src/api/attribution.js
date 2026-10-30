// El sobre de los eventos: desde dónde se tocó, se vio o se agregó algo (`surface`, `origin`, `position`) y de qué
// respuesta de la API salió (`request_id`). Es el único lugar que lo arma: las pantallas marcan sus listas con
// `placeList` (o `place`, un solo elemento) y los eventos lo leen con `placementFields`. Equivale a CONTEXT, SOURCE,
// COMPONENT_INDEX y REQUEST_ID de la app de Rappi (docs/investigacion/app-rappi-2026-10-25.md).

/** Las pantallas que acepta rappi-ia (`app_events.surface`, migración 043; events/store.py: SURFACES). */
export const SURFACES = new Set([
  'home',
  'search',
  'store',
  'vertical',
  'restaurants',
  'turbo',
  'deals',
  'favorites',
  'list',
  'agent',
  'cart',
  'checkout',
  'tracking',
  'orders',
])

// La forma que acepta rappi-ia (EventIn): un origen o un id que no la cumple haría rechazar (422) el lote entero.
const ORIGIN = /^[a-z0-9_-]{1,40}$/
const REQUEST_ID = /^[A-Za-z0-9._-]{1,64}$/
const MAX_POSITION = 999

/**
 * Los campos del sobre para un evento, solo los que valen: `{ surface, origin, position, request_id }`. `position` es el
 * lugar en la lista (0 = el primero). Lo que no tiene la forma que acepta la API se omite, nunca se manda.
 */
export function envelope({ surface, origin, position, requestId } = {}) {
  return {
    ...(SURFACES.has(surface) ? { surface } : {}),
    ...(typeof origin === 'string' && ORIGIN.test(origin) ? { origin } : {}),
    ...(Number.isInteger(position) && position >= 0 && position <= MAX_POSITION ? { position } : {}),
    ...(typeof requestId === 'string' && REQUEST_ID.test(requestId) ? { request_id: requestId } : {}),
  }
}

/** El elemento con su lugar: `{ ...item, placement: { surface, origin, position, requestId } }`. */
export const place = (item, placement) => ({ ...item, placement })

/**
 * Marca cada elemento de una lista con su lugar (desde `start`, 0 por defecto): los eventos que nazcan de él (abrirlo,
 * agregarlo al carro) dicen de qué lista y posición salió. Un elemento que ya traía lugar lo cambia por este.
 */
export function placeList(items, { surface, origin, requestId, start = 0 }) {
  return (items ?? []).map((item, index) => place(item, { surface, origin, position: start + index, requestId }))
}

/** Los campos del sobre de un elemento marcado (vacío si no tiene lugar). */
export const placementFields = (item) => envelope(item?.placement)

/** ¿Salió de una recomendación del agente o de "Para ti"? Abrirla es un `recommendation_click`. */
export const isRecommendation = (placement) =>
  typeof placement?.origin === 'string' && (placement.origin === 'para-ti' || placement.origin.startsWith('agent-'))

// Lo que dura la pestaña: abrir la misma recomendación otra vez (desde la hoja y después su tienda) no cuenta de nuevo.
const clicked = new Set()

/**
 * Registra `recommendation_click` la primera vez que se abre un producto (o una tienda, `entity_type: 'store'`) que vino
 * de una recomendación. `fields` son los del evento (concepto, vertical, entidad); el sobre sale de `item.placement`.
 * Devuelve si lo registró.
 */
export function noteRecommendationClick(track, item, fields) {
  if (!isRecommendation(item?.placement)) return false
  const key = `${item.placement.requestId ?? ''}|${item.placement.origin}|${fields.entity_type}:${fields.entity_id}`
  if (clicked.has(key)) return false
  clicked.add(key)
  track('recommendation_click', { ...fields, ...placementFields(item) })
  return true
}

// Abrir un producto en la hoja y tocar "Ver tienda" es una sola vista: la tienda no repite su `view_item`.
let sheetView = null
const viewKey = (item, fields) =>
  `${item?.placement?.requestId ?? ''}|${item?.placement?.origin ?? ''}|${item?.placement?.position ?? ''}|${fields.entity_type}:${fields.entity_id}`

/**
 * Registra `view_item` (ver un producto) con `fields` (los del carro: entidad, concepto, vertical y el sobre de su lugar).
 * `fromSheet`: se abrió en la hoja del producto; si después se llega a su tienda con el mismo producto y el mismo lugar,
 * la tienda no lo cuenta otra vez. Sin entidad no registra nada. Devuelve si lo registró.
 */
export function noteItemView(track, item, fields, { fromSheet = false } = {}) {
  if (!fields.entity_type || !fields.entity_id) return false
  const key = viewKey(item, fields)
  if (!fromSheet && sheetView === key) {
    sheetView = null
    return false
  }
  sheetView = fromSheet ? key : null
  track('view_item', fields)
  return true
}
