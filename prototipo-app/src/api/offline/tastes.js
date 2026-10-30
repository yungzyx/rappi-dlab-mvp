// Los perfiles de gusto sin conexión (offers/profiles.py y layers/segments.py, muy simplificados): un perfil está
// activo si la persona pidió en al menos tres pedidos `propuesta` algo de un concepto que activa sus segmentos
// (`meta.profiles[…].concepts`). Lo que se responde (sus gustos y su escalera) es lo grabado de la API real para una
// persona de prueba con ese perfil (`snapshot.tastes`).

import { isConfirmed } from './state'

export const MIN_ORDERS = 3

/** Los perfiles activos de la persona, el principal primero y después por pedidos: `[{ id, orders }]`. */
export function activeTastes(snapshot, state) {
  const found = []
  for (const [id, profile] of Object.entries(snapshot.meta.profiles ?? {})) {
    if (!snapshot.tastes?.[id]) continue
    const orders = state.orders.filter(
      (o) =>
        o.mode === 'propuesta' && isConfirmed(o) && o.lines.some((line) => profile.concepts.includes(line.concept_id)),
    ).length
    if (orders >= MIN_ORDERS) found.push({ id, orders, main: profile.main })
  }
  return found.sort((a, b) => b.main - a.main || b.orders - a.orders)
}

/**
 * `GET /profile/{id}/gustos`: `{ perfiles }`, los grabados de sus perfiles activos. Una muestra grabada antes de que la
 * API dijera `gusto` y `conceptos` los toma de `meta` (si tampoco está ahí, la app saluda como siempre).
 */
export const tastesReply = (snapshot, state) => ({
  perfiles: activeTastes(snapshot, state).map(({ id }, i) => {
    const recorded = snapshot.tastes[id].gustos
    const gusto = recorded.gusto ?? snapshot.meta.profiles[id].gusto
    return {
      ...recorded,
      ...(gusto ? { gusto } : {}),
      conceptos: recorded.conceptos ?? countedConcepts(snapshot.meta.concepts, recorded.basis),
      principal: i === 0,
    }
  }),
})

/** El nombre y el emoji de lo que cuenta el «por qué» (`pedidos` y `busquedas` en la `basis`), como `conceptos`. */
function countedConcepts(concepts, basis = []) {
  const found = {}
  for (const { id, source } of basis) {
    if ((source === 'pedidos' || source === 'busquedas') && concepts[id])
      found[id] = { nombre: concepts[id].name, emoji: concepts[id].emoji }
  }
  return found
}

/** El momento `perfil`: la escalera grabada del perfil pedido o, sin él, del primero de la persona; null si no hay. */
export function profileOffer(snapshot, state, profileId) {
  const id = profileId ?? activeTastes(snapshot, state)[0]?.id
  return (id && snapshot.tastes?.[id]?.ladder) || null
}
