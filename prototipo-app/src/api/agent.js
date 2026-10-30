// Ofertas del agente de rappi-ia: `POST /agent/offer` (un momento de la app) y `GET /agent/plans` (ocasiones).
import { routeForScreen, screenForBackend } from '../data/verticals'
import { placeList } from './attribution'
import { request, toPrototypeProduct } from './client'
import { userId } from './user'
import { sessionId } from '../state/EventsContext'

const OFFER_TIMEOUT_MS = 5_000

/**
 * La acción del servidor trae la vertical de la app (`route: ['express']`); aquí pasa a la ruta de su pantalla. Una que
 * le pide algo a Mochi (`ask`, como "Pide lo de siempre por mí" en la recompra) queda `{ ask: { text } }`, como las de
 * /agent/ask.
 */
function toAction({ route, ask, ...action }) {
  if (typeof ask === 'string') return { ...action, ask: { text: ask } }
  return route?.[0] ? { ...action, route: routeForScreen(route[0]) } : action
}

/**
 * La oferta del agente para un momento (`carrito`, `checkout`, `sin_resultado`, `proximo_pedido`, `plan`,
 * `vertical_por_probar`, `recompra`, `volver`, `ontop`) con su contexto, o `null` si no tiene nada que ofrecer (204): entonces el agente no dice nada.
 * Devuelve `{ moment, text, products, vertical, backendVertical, reason, actions, windowMin, stores, requestId }`; la `vertical` es la de
 * la app y cada producto lleva `fromSuggestion` y `suggestionOrigin: 'agent-<momento>'` para los eventos y el pedido,
 * y su lugar (`placement`: `surface`, la pantalla donde se muestra la oferta; su posición y la respuesta), y cada
 * acción la `route` de la app (`push(...route)`).
 * Si falla, lanza el `ApiError`: quien llama decide callar.
 */
export async function offer(moment, context = {}, { userId, surface } = {}) {
  const response = await request('/agent/offer', {
    method: 'POST',
    // La sesión: si la persona está en el grupo de control de las ofertas, la retenida queda en esta sesión (204).
    body: { moment, ...(userId ? { user_id: userId, session_id: sessionId() } : {}), context },
    timeout: OFFER_TIMEOUT_MS,
  })
  if (!response) return null
  const origin = `agent-${moment}`
  const requestId = response.request_id ?? null
  return {
    moment: response.moment,
    text: response.text,
    products: placeList(
      response.products.map((p) => ({ ...toPrototypeProduct(p), fromSuggestion: true, suggestionOrigin: origin })),
      { surface, origin, requestId },
    ),
    vertical: response.prototype_vertical ?? null,
    backendVertical: response.vertical,
    reason: response.reason,
    actions: (response.actions ?? []).map(toAction),
    // El plazo del OnTop de Turbo (momento `ontop`, un supuesto): minutos desde el pedido para sumar sus productos.
    windowMin: response.plazo_min ?? null,
    // Las tiendas de un kit (momento `plan`), un pedido cada una: lo que suma ahí y su compra mínima del catálogo
    // (`minOrder` null si no la sabe), con la marca de la que no llega (`belowMin`, `missing`).
    stores: (response.stores ?? []).map((store) => ({
      storeId: store.store_id,
      store: store.store,
      subtotal: store.subtotal,
      minOrder: store.min_order ?? null,
      missing: store.missing ?? null,
      belowMin: Boolean(store.below_min),
    })),
    requestId,
  }
}

/**
 * Las ocasiones que el agente sabe armar para esta persona: `[{ id, name, emoji, reason? }]`. Las que su historia
 * pone primero traen `reason: { text, basis }` ("Para ti"); sin historia, la lista de siempre y sin `reason`.
 */
export const plans = () =>
  request(`/agent/plans?user_id=${encodeURIComponent(userId())}`, { timeout: OFFER_TIMEOUT_MS })

/**
 * Los perfiles de gusto de la persona (`GET /profile/{id}/gustos`): `[{ id, nombre, emoji, nivel, principal, por_que,
 * basis }]`, el principal primero; vacío sin perfiles.
 */
export const tasteProfiles = () =>
  request(`/profile/${encodeURIComponent(userId())}/gustos`, { timeout: OFFER_TIMEOUT_MS }).then(
    (reply) => reply?.perfiles ?? [],
  )

/**
 * La escalera de un perfil de gusto (el momento `perfil` de /agent/offer), o null (204):
 * `{ text, profile, reason, steps: [{ vertical, backendVertical, text, products }], trip, requestId }`. Cada peldaño es una
 * vertical (id de la app) con sus productos, que ya pasaron las guardias de las ofertas y cuentan como sugerencia de
 * Mochi (`suggestionOrigin: 'agent-perfil'`); `trip` es la idea para RappiTravel (`{ name, text, label, facts, route }`).
 */
export async function profileLadder(profileId) {
  const response = await request('/agent/offer', {
    method: 'POST',
    body: { moment: 'perfil', user_id: userId(), context: { perfil: profileId } },
    timeout: OFFER_TIMEOUT_MS,
  })
  if (!response) return null
  const trip = response.viaje
  const requestId = response.request_id ?? null
  // Las posiciones siguen de corrido entre peldaños (como searchAll): los peldaños comparten origen y respuesta, y
  // dos productos distintos no pueden quedar en el mismo lugar (las filas de "Algo para ti" los juntan).
  let start = 0
  return {
    requestId,
    text: response.text,
    profile: response.perfil,
    reason: response.reason,
    steps: (response.escalera ?? []).map((step) => ({
      vertical: screenForBackend(step.vertical) ?? step.prototype_vertical,
      backendVertical: step.vertical,
      text: step.texto,
      products: (() => {
        const placed = placeList(
          step.products.map((p) => ({
            ...toPrototypeProduct(p),
            fromSuggestion: true,
            suggestionOrigin: 'agent-perfil',
          })),
          { surface: 'agent', origin: 'agent-perfil', requestId, start },
        )
        start += placed.length
        return placed
      })(),
    })),
    trip: trip
      ? {
          id: trip.id,
          name: trip.nombre,
          text: trip.texto,
          label: trip.etiqueta,
          facts: trip.hechos.map((fact) => ({ text: fact.texto, source: fact.fuente, url: fact.url })),
          route: trip.route,
        }
      : null,
  }
}

/**
 * Las preferencias de la persona con el agente (`GET /profile/{id}/preferencias`): `{ preferencias, opciones }`, cada
 * una `{ tipo, valor, nombre }` (`tipo`: dieta, alergia, cocina o tienda). La dieta y las alergias solo filtran lo que
 * muestra Mochi; las cocinas y tiendas favoritas solo ordenan.
 */
export const preferences = () =>
  request(`/profile/${encodeURIComponent(userId())}/preferencias`, { timeout: OFFER_TIMEOUT_MS })

/** Reemplaza sus preferencias por `list` (`[{ tipo, valor }]`); responde como `preferences()`. */
export const savePreferences = (list) =>
  request(`/profile/${encodeURIComponent(userId())}/preferencias`, {
    method: 'PUT',
    body: { preferencias: list.map(({ tipo, valor }) => ({ tipo, valor })) },
    timeout: OFFER_TIMEOUT_MS,
  })
