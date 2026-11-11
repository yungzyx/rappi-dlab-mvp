import { screenForBackend } from '../data/verticals'
import { noteRefused, refusedConcepts } from '../state/EventsContext'
import { envelope } from './attribution'
import { conceptOf } from './orders'

// Lo que dura la pestaña: las pantallas se desmontan y vuelven a montarse, y lo ya mostrado no se cuenta otra vez.
const shown = new Set()

/**
 * true la primera vez que se muestra esta sugerencia en la pestaña (concepto, vertical, origen y generación del
 * perfil): la misma clave con que AddButton cuenta su aceptación, para que las aceptadas nunca superen a las mostradas.
 * La vertical cuenta igual como código del backend ('licores', el de la sugerencia del agente) que como id del prototipo
 * ('liquor', el de sus productos).
 */
export function firstShowing(row) {
  const vertical = screenForBackend(row.vertical) ?? row.vertical
  const key = `${row.concept}|${vertical}|${row.origin}|${row.generation}`
  if (shown.has(key)) return false
  shown.add(key)
  return true
}

/**
 * Registra la sugerencia del agente mostrada (`suggestion_shown`): una vez por pestaña, concepto, vertical, origen y
 * generación del perfil (`generation` = `profile.resets`). `track` es `useEvents().track`; `origin` es
 * `agent-<momento>`, `agent-ask`, etc. (la columna `origin` del evento). Si no se dan `concept` o `vertical`, salen del
 * primer producto, y `surface` y `requestId` (la pantalla y la respuesta de la API), de su lugar (`placement`). Con
 * `kind` (la fila "Lo más pedido" de "Para ti": `lo_mas_pedido`), va en el payload, y con `reason` (la razón de la
 * oferta), los tipos de su `basis` (`payload.basis`: ver `basisKinds`). Devuelve si la registró (false si ya estaba
 * contada o no hay concepto).
 */
export function noteShown(
  track,
  products,
  { origin, concept, vertical, generation = 0, kind, reason, surface, requestId },
) {
  const [first] = products ?? []
  const shownConcept = concept ?? (first && conceptOf(first))
  const shownVertical = vertical ?? first?.vertical
  if (!shownConcept || !firstShowing({ concept: shownConcept, vertical: shownVertical, origin, generation }))
    return false
  // El origen va en la columna `origin` (antes, `payload.origen`); la pantalla y la respuesta, las del primer producto.
  const placed = first?.placement ?? {}
  track('suggestion_shown', {
    concept_id: shownConcept,
    vertical: shownVertical,
    ...envelope({ surface: surface ?? placed.surface, origin, requestId: requestId ?? placed.requestId }),
    ...withPayload({ kind: kind || undefined, basis: basisKinds(reason) }),
  })
  return true
}

/**
 * Registra como mostrada una oferta del agente (`made`, la que devuelve `offer` de api/agent.js) con `noteShown`: su
 * origen es `agent-<momento>` (el de la respuesta), su concepto el de su razón (sin él, el del primer producto) y su
 * `basis` la de su razón. `products`: los que se muestran, si no son todos los de la oferta (el complemento del checkout
 * muestra uno). `generation` y `kind` como en `noteShown`. Devuelve si la registró.
 */
export function noteOfferShown(track, made, { generation, kind, products = made.products } = {}) {
  return noteShown(track, products, {
    origin: `agent-${made.moment}`,
    concept: made.reason?.concept,
    reason: made.reason,
    generation,
    kind,
  })
}

// Sugerencias ya rechazadas (generación|concepto|vertical|origen|tipo): una vez por pestaña, como la mostrada, así las
// rechazadas tampoco superan a las mostradas (el comentario del carrito vuelve con cada producto agregado).
const dismissed = new Set()

// El `payload.kind` de una oferta del globo de la Home que se fue sola, sin que la persona tocara nada: no es un
// rechazo (el panel, el "volver" y los rechazos de la API no la cuentan), solo la distingue de "sin respuesta".
export const EXPIRED = 'expirada'

/**
 * Registra la sugerencia del agente rechazada (`suggestion_dismissed`, "Ahora no" o "Después"): con el concepto, la
 * vertical, el origen y el lugar con que `noteShown` registró la mostrada, una vez por pestaña. Sin concepto no
 * registra nada, como la mostrada. Con `kind: EXPIRED`, la oferta que se fue sola (en el payload, y contada aparte del
 * rechazo). El "Después" de "¿Volvemos a…?" no pasa por aquí: lleva su `payload.kind` y cada uno cuenta para la API
 * (LiveHomeFeed: repeatLater). Devuelve si la registró.
 */
export function noteDismissal(track, products, { origin, concept, generation = 0, kind }) {
  const [first] = products ?? []
  const dismissedConcept = concept ?? (first && conceptOf(first))
  const dismissedVertical = first?.vertical
  if (!dismissedConcept) return false
  const key = `${generation}|${dismissedConcept}|${screenForBackend(dismissedVertical) ?? dismissedVertical}|${origin}|${kind ?? ''}`
  if (dismissed.has(key)) return false
  dismissed.add(key)
  const placed = first?.placement ?? {}
  track('suggestion_dismissed', {
    concept_id: dismissedConcept,
    vertical: dismissedVertical,
    ...envelope({ surface: placed.surface, origin, requestId: placed.requestId }),
    ...withPayload({ kind }),
  })
  return true
}

/** El concepto de una oferta del agente (`made`): el de su razón o, sin él, el de su primer producto. */
const offerConcept = (made) => made.reason?.concept ?? (made.products?.[0] && conceptOf(made.products[0]))

/**
 * `noteDismissal` de una oferta del agente (`made`), con el mismo concepto y origen que `noteOfferShown`. Si la
 * rechazaron (no se fue sola), su concepto queda rechazado en la sesión: ver `wasRefused`.
 */
export function noteOfferDismissal(track, made, { generation, kind } = {}) {
  if (kind !== EXPIRED) refuseConcept(offerConcept(made))
  return noteDismissal(track, made.products, {
    origin: `agent-${made.moment}`,
    concept: made.reason?.concept,
    generation,
    kind,
  })
}

/** Anota un concepto rechazado en la sesión (sin concepto, nada): "Ahora no", "Después" de una oferta de la Home. */
export function refuseConcept(concept) {
  if (concept) noteRefused(concept)
}

/**
 * Si la persona ya rechazó en esta sesión el concepto de esta oferta (`made`), o el de `product`: Mochi no se lo
 * vuelve a ofrecer (el comentario del carro en la Home, "¿Me falta algo?" del checkout).
 */
export function wasRefused(made, product) {
  const refused = refusedConcepts()
  const concepts = [offerConcept(made), product && conceptOf(product)].filter(Boolean)
  return concepts.some((concept) => refused.includes(concept))
}

/**
 * De qué fuente sale el "¿Por qué?" de una oferta: los tipos de su `reason.basis` (`recompra`, `busqueda`, `perfil`…),
 * sin repetir y como mucho 4. Solo los tipos: el texto y los ids pueden traer lo que la persona escribió (una búsqueda),
 * y el payload de un evento no pasa por la redacción ni la purga de las consultas. Sin razón, undefined.
 */
export function basisKinds(reason) {
  const kinds = [...new Set((reason?.basis ?? []).map((signal) => signal?.kind).filter(Boolean))].slice(0, 4)
  return kinds.length ? kinds : undefined
}

// El payload solo con lo que trae valor (sin payload si no queda nada).
function withPayload(fields) {
  const payload = Object.fromEntries(Object.entries(fields).filter(([, value]) => value !== undefined))
  return Object.keys(payload).length ? { payload } : {}
}

// Sugerencias ya aceptadas (generación|concepto|vertical|origen): una vez por pestaña, como se cuenta la mostrada, así
// las aceptadas nunca superan a las mostradas, ni con un carro nuevo tras un pedido. "Olvidar" sube la generación, y lo
// que se acepte después vuelve a contar.
const accepted = new Set()

/**
 * Registra `suggestion_accepted` por cada producto de `products` que aún no se contó (agregar un kit completo cuenta una
 * aceptación por producto; los "+" siguientes y quitar y volver a agregar no cuentan otra). Cada una lleva su concepto y
 * su vertical, y antes registra la mostrada que faltase: lo aceptado siempre tiene su mostrada (salvo si no tiene
 * concepto: entonces va sin `concept_id`). `origin` y `generation` como en `noteShown`. Devuelve cuántas registró.
 */
export function noteAccepted(track, products, { origin, generation = 0 }) {
  let count = 0
  for (const product of products ?? []) {
    const concept = conceptOf(product)
    const vertical = product.vertical
    // Sin concepto la aceptada se registra igual (sin concept_id), contada por producto.
    const key = `${generation}|${concept ?? `producto:${product.entityId ?? product.id}`}|${screenForBackend(vertical) ?? vertical}|${origin}`
    if (accepted.has(key)) continue
    accepted.add(key)
    const placed = product.placement ?? {}
    const where = { surface: placed.surface, requestId: placed.requestId }
    if (concept) noteShown(track, null, { origin, concept, vertical, generation, ...where })
    track('suggestion_accepted', { concept_id: concept, vertical, ...envelope({ ...where, origin }) })
    count += 1
  }
  return count
}
