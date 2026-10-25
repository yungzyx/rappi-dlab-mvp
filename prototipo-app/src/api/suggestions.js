import { screenForBackend } from '../data/verticals'
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
 * `agent-<momento>`, `agent-ask`, etc. Si no se dan `concept` o `vertical`, salen del primer producto. Con `kind` (la
 * fila «Lo más pedido» de «Para ti»: `lo_mas_pedido`), va también en el payload. Devuelve si la registró (false si ya
 * estaba contada o no hay concepto).
 */
export function noteShown(track, products, { origin, concept, vertical, generation = 0, kind }) {
  const [first] = products ?? []
  const shownConcept = concept ?? (first && conceptOf(first))
  const shownVertical = vertical ?? first?.vertical
  if (!shownConcept || !firstShowing({ concept: shownConcept, vertical: shownVertical, origin, generation }))
    return false
  const payload = kind ? { origen: origin, kind } : { origen: origin }
  track('suggestion_shown', { concept_id: shownConcept, vertical: shownVertical, payload })
  return true
}

// Sugerencias ya aceptadas (generación|concepto|vertical|origen): una vez por pestaña, como se cuenta la mostrada, así
// las aceptadas nunca superan a las mostradas, ni con un carro nuevo tras un pedido. «Olvidar» sube la generación, y lo
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
    if (concept) noteShown(track, null, { origin, concept, vertical, generation })
    track('suggestion_accepted', { concept_id: concept, vertical, payload: { origen: origin } })
    count += 1
  }
  return count
}
