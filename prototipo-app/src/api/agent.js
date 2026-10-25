// Ofertas del agente de rappi-ia: `POST /agent/offer` (un momento de la app) y `GET /agent/plans` (ocasiones).
import { routeForScreen, screenForBackend } from '../data/verticals'
import { request, toPrototypeProduct } from './client'
import { userId } from './user'

const OFFER_TIMEOUT_MS = 5_000

/** La acción del servidor trae la vertical de la app (`route: ['express']`); aquí pasa a la ruta de su pantalla. */
function toAction({ route, ...action }) {
  return route?.[0] ? { ...action, route: routeForScreen(route[0]) } : action
}

/**
 * La oferta del agente para un momento (`carrito`, `checkout`, `sin_resultado`, `proximo_pedido`, `plan`,
 * `vertical_por_probar`, `recompra`, `volver`) con su contexto, o `null` si no tiene nada que ofrecer (204): entonces el agente no dice nada.
 * Devuelve `{ moment, text, products, vertical, backendVertical, reason, actions }`; la `vertical` es la de la app y
 * cada producto lleva `fromSuggestion` y `suggestionOrigin: 'agent-<momento>'` para los eventos y el pedido, y cada
 * acción la `route` de la app (`push(...route)`).
 * Si falla, lanza el `ApiError`: quien llama decide callar.
 */
export async function offer(moment, context = {}, { userId } = {}) {
  const response = await request('/agent/offer', {
    method: 'POST',
    body: { moment, ...(userId ? { user_id: userId } : {}), context },
    timeout: OFFER_TIMEOUT_MS,
  })
  if (!response) return null
  return {
    moment: response.moment,
    text: response.text,
    products: response.products.map((p) => ({
      ...toPrototypeProduct(p),
      fromSuggestion: true,
      suggestionOrigin: `agent-${moment}`,
    })),
    vertical: response.prototype_vertical ?? null,
    backendVertical: response.vertical,
    reason: response.reason,
    actions: (response.actions ?? []).map(toAction),
  }
}

/**
 * Las ocasiones que el agente sabe armar para esta persona: `[{ id, name, emoji, reason? }]`. Las que su historia
 * pone primero traen `reason: { text, basis }` («Para ti»); sin historia, la lista de siempre y sin `reason`.
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
 * `{ text, profile, reason, steps: [{ vertical, backendVertical, text, products }], trip }`. Cada peldaño es una
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
  return {
    text: response.text,
    profile: response.perfil,
    reason: response.reason,
    steps: (response.escalera ?? []).map((step) => ({
      vertical: screenForBackend(step.vertical) ?? step.prototype_vertical,
      backendVertical: step.vertical,
      text: step.texto,
      products: step.products.map((p) => ({
        ...toPrototypeProduct(p),
        fromSuggestion: true,
        suggestionOrigin: 'agent-perfil',
      })),
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
