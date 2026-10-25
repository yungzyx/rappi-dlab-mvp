// Impresiones de listas: lo que cada lista dejó a la vista, con su lugar (`list_view` y `app_event_items` en rappi-ia,
// migración 047). Equivale a VIEW_COMPONENT y VIEW_PRODUCT_IMPRESSIONS de la app de Rappi. Con esto se mide el CTR por
// posición (capa.v_ctr_posicion) y el sesgo de posición del orden de la Home y de la búsqueda.
//
// Cómo cuenta, sin inundar la API:
// - un elemento cuenta cuando queda visible al menos la mitad (THRESHOLD), una sola vez por pestaña, lista (pantalla,
//   lista y respuesta de la API), lugar y elemento: volver a la misma pantalla no lo cuenta de nuevo;
// - lo visto se junta y sale en un evento por lista cada FLUSH_MS (o antes, al ocultar la página), con hasta MAX_ITEMS
//   elementos; `position` del evento es la mayor posición vista de esa lista hasta ahí;
// - solo los elementos con lugar (`placement`, de api/attribution.js) y un id: el resto se ignora. Sin
//   IntersectionObserver (tests, navegadores viejos) no hace nada.
import { envelope } from './attribution'
import { conceptOf } from './orders'

export const THRESHOLD = 0.5
export const FLUSH_MS = 1000
export const MAX_ITEMS = 20 // el tope de rappi-ia (events/store.py: MAX_EVENT_ITEMS)
const ENTITY_TYPES = new Set(['catalog_item', 'menu_item', 'store', 'vertical'])

/** Los campos de un producto o plato en la lista. */
export const productItem = (product) => ({
  entity_type: product?.entityType,
  entity_id: product?.entityId,
  concept_id: product ? conceptOf(product) : undefined,
  vertical: product?.backendVertical ?? product?.vertical,
})

/** Los campos de una tienda o restaurante en la lista. */
export const storeItem = (store) => ({
  entity_type: 'store',
  entity_id: store?.id,
  vertical: store?.vertical,
})

/** Los campos de un acceso de la Home (su vertical, código del backend). */
export const verticalItem = (vertical) => ({ entity_type: 'vertical', entity_id: vertical, vertical })

let sink = null // useEvents().track
let observer = null
let listening = false
let timer = null
const watched = new Map() // nodo → elemento
const reported = new Set() // claves ya contadas en la pestaña
const highest = new Map() // lista → mayor posición vista
let pending = new Map() // lista → { placement, items: Map(clave → elemento) }

const listKey = ({ surface, origin, requestId }) => `${surface}|${origin}|${requestId ?? ''}`

/** El elemento listo para la API (`{ position, entity_type, entity_id, concept_id?, vertical? }`), o null. */
function describe(placement, fields) {
  const { surface, origin, position } = envelope(placement)
  const id = fields?.entity_id == null ? '' : String(fields.entity_id)
  if (!surface || !origin || position === undefined || !ENTITY_TYPES.has(fields?.entity_type)) return null
  if (id.length === 0 || id.length > 64) return null
  return {
    position,
    entity_type: fields.entity_type,
    entity_id: id,
    ...(typeof fields.concept_id === 'string' && fields.concept_id ? { concept_id: fields.concept_id } : {}),
    ...(typeof fields.vertical === 'string' && fields.vertical ? { vertical: fields.vertical } : {}),
  }
}

const itemKey = (placement, item) => `${listKey(placement)}|${item.position}|${item.entity_type}:${item.entity_id}`

/** Manda lo visto: un `list_view` por lista (de a MAX_ITEMS), en orden de posición. */
export function flushImpressions() {
  clearTimeout(timer)
  timer = null
  const lists = pending
  pending = new Map()
  if (!sink) return
  for (const [key, { placement, items }] of lists) {
    const sorted = [...items.values()].sort((a, b) => a.position - b.position)
    for (let start = 0; start < sorted.length; start += MAX_ITEMS) {
      const chunk = sorted.slice(start, start + MAX_ITEMS)
      const top = Math.max(highest.get(key) ?? -1, chunk.at(-1).position)
      highest.set(key, top)
      sink('list_view', { ...envelope({ ...placement, position: top }), items: chunk })
    }
  }
}

function seen(entries) {
  for (const entry of entries) {
    if (!entry.isIntersecting || entry.intersectionRatio < THRESHOLD) continue
    const node = entry.target
    const info = watched.get(node)
    observer?.unobserve?.(node)
    watched.delete(node)
    if (!info || reported.has(info.key)) continue
    reported.add(info.key)
    const list = listKey(info.placement)
    if (!pending.has(list)) pending.set(list, { placement: info.placement, items: new Map() })
    pending.get(list).items.set(info.key, info.item)
    timer ??= setTimeout(flushImpressions, FLUSH_MS)
  }
}

function ensureObserver() {
  if (observer || typeof IntersectionObserver === 'undefined') return observer
  observer = new IntersectionObserver(seen, { threshold: THRESHOLD })
  if (!listening && typeof document !== 'undefined') {
    listening = true
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') flushImpressions()
    })
  }
  return observer
}

/** Quién registra los eventos (`useEvents().track`). */
export function setImpressionSink(track) {
  sink = track
}

/**
 * Un ref de React para el nodo de un elemento de lista: cuenta su impresión cuando se ve. `item` trae su lugar
 * (`placement`); `fields` dice qué es (`productItem`, `storeItem`, `verticalItem`). Sin lugar o sin id no observa
 * nada (devuelve undefined: el nodo queda sin ref).
 */
export function impressionRef(item, fields) {
  const placement = item?.placement
  const described = placement ? describe(placement, fields) : null
  if (!described) return undefined
  const key = itemKey(placement, described)
  return (node) => {
    if (!node || reported.has(key) || !ensureObserver()) return undefined
    watched.set(node, { key, placement, item: described })
    observer.observe(node)
    return () => {
      watched.delete(node)
      observer?.unobserve?.(node)
    }
  }
}

/** Para los tests: olvida lo contado y lo pendiente. */
export function resetImpressions() {
  clearTimeout(timer)
  timer = null
  observer?.disconnect?.()
  observer = null
  watched.clear()
  reported.clear()
  highest.clear()
  pending = new Map()
  sink = null
}
