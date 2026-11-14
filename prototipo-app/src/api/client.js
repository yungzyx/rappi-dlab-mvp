// Cliente de la API de rappi-ia (el agente: búsqueda híbrida, ofertas y eventos).
// Sin la API la app muestra "Sin conexión" con el agente (ver ConnectionGate).

import { VERTICAL_NAMES, routeForScreen, screenForBackend } from '../data/verticals'
import { PLACEHOLDER_IMG } from '../components/Img'
import { placeList } from './attribution'
import { setAgentEnabled } from '../state/agentEnabled'
import { saveSession, storedUserId, userToken } from './user'

const DEFAULT_PORT = 8000
const HEALTH_TTL_MS = 30_000
const HEALTH_TIMEOUT_MS = 1500
const DEFAULT_TIMEOUT_MS = 8_000 // más que esto, el público ya nota la espera: la pregunta al agente muestra "Sin conexión"
const CONNECTION_TIMEOUT_MS = 5_000

/**
 * Dónde está la API. `VITE_API_URL` manda (sin la barra final). Sin ella: en el build de producción, el mismo origen
 * bajo `/api` (un proxy inverso la sirve); en desarrollo, el host desde donde se abrió la página en el puerto 8000
 * (así el iPhone con `LAN=1` llega a la API del Mac).
 */
export function apiUrl(env, location) {
  const configured = env.VITE_API_URL?.trim().replace(/\/+$/, '')
  if (configured) return configured
  if (env.PROD || !devApiUrl) return '/api'
  return devApiUrl(location)
}

// Solo existe en desarrollo: el build de producción la descarta, y `dist/` no lleva rastros de "localhost" ni del puerto.
const devApiUrl = import.meta.env.DEV
  ? (location) => `http://${location?.hostname || 'localhost'}:${DEFAULT_PORT}`
  : undefined

export const API_URL = apiUrl(import.meta.env, typeof window !== 'undefined' ? window.location : undefined)

let healthCache = { at: 0, value: null }

/**
 * Por qué falló una petición a la API: `offline` (no hay quien responda, o lo que responde no es la API),
 * `timeout` (no contestó a tiempo), `cancelled` (la cortó quien la pidió) o `http` (contestó con un error; `status` es
 * su código). Un 409 trae el `detail` de la API (el motivo por el que no tomó un pedido que Mochi hizo solo).
 */
export class ApiError extends Error {
  constructor(kind, { status, cause, detail } = {}) {
    super(kind === 'http' ? `API ${status}` : `API ${kind}`, { cause })
    this.name = 'ApiError'
    this.kind = kind
    this.status = status
    this.detail = detail
  }
}

const SESSION_PATH = '/session'
const TOKEN_HEADER = 'X-User-Token'

/**
 * Una petición a la API, con el token de la sesión en X-User-Token. Un 401 (el token no es de esta API, o se perdió)
 * pide una sesión nueva y repite la petición una sola vez, como la persona de esa sesión: el id con que salió, en la
 * ruta o en el `user_id` del cuerpo, pasa a ser el de la sesión. Si la sesión ya cambió mientras esta iba en camino
 * (otra petición la renovó), no se pide otra: se repite con la actual.
 */
export async function request(path, options = {}) {
  const sent = { id: storedUserId(), token: userToken() }
  try {
    return await send(path, options)
  } catch (error) {
    if (error.status !== 401 || path === SESSION_PATH) throw error
    if (userToken() === sent.token) await renewSession()
    const after = storedUserId()
    if (!sent.id || sent.id === after) return send(path, options)
    const body = options.body?.user_id === sent.id ? { ...options.body, user_id: after } : options.body
    return send(path.split(encodeURIComponent(sent.id)).join(encodeURIComponent(after)), { ...options, body })
  }
}

let renewing = null

/**
 * Pide a la API la sesión de este navegador (`POST /session`) con el id que ya tenía, que la API reclama una sola vez
 * para no perder lo suyo; si no, la API da uno nuevo. Varias llamadas a la vez comparten la misma petición.
 */
export function renewSession() {
  renewing ??= send(SESSION_PATH, { method: 'POST', body: { legacy_user_id: storedUserId() } })
    .then(saveSession)
    .finally(() => {
      renewing = null
    })
  return renewing
}

/**
 * La sesión de este navegador al abrir (la pide ConnectionGate): la primera vez, una nueva (`POST /session`). Si ya
 * tiene una, la confirma con `GET /session`, que dice si la persona tiene a Mochi (`agent_enabled`: falso en el grupo de
 * control, "Mochi apagado"); así lo sabe también al recargar, y quien ya tenía sesión recibe su variante si el grupo de
 * control se encendió después. Un 401 (el token no es de esta API) pide una sesión nueva. Si la confirmación falla por
 * otra razón, sigue con lo que ya sabía; una API sin `GET /session` (404 o 405) no tiene grupo de control.
 */
export async function ensureSession() {
  if (!userToken()) return renewSession()
  try {
    setAgentEnabled((await send(SESSION_PATH, { timeout: CONNECTION_TIMEOUT_MS }))?.agent_enabled)
  } catch (error) {
    if (error.status === 401) return renewSession()
    if (error.status === 404 || error.status === 405) setAgentEnabled(true)
  }
}

async function send(path, { method = 'GET', body, timeout = DEFAULT_TIMEOUT_MS, keepalive, signal, onEmpty } = {}) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeout)
  // `signal`: quien llama puede cortar la petición (cancelar la respuesta de Mochi en curso).
  const cancel = () => controller.abort()
  signal?.addEventListener('abort', cancel, { once: true })
  const token = userToken()
  try {
    const response = await fetch(`${API_URL}${path}`, {
      method,
      body: body ? JSON.stringify(body) : undefined,
      headers: { ...(body ? { 'content-type': 'application/json' } : {}), ...(token ? { [TOKEN_HEADER]: token } : {}) },
      signal: controller.signal,
      ...(keepalive ? { keepalive: true } : {}),
    })
    if (!response.ok) {
      const detail = response.status === 409 ? (await response.json().catch(() => null))?.detail : undefined
      throw new ApiError('http', { status: response.status, detail })
    }
    if (response.status === 204) {
      onEmpty?.(response) // quien quiere leer las cabeceras de un 204 (una oferta retenida: api/agent.js)
      return null
    }
    return await response.json()
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (signal?.aborted) throw new ApiError('cancelled', { cause: error })
    // Si no lo cortó quien llama, solo el temporizador aborta; cualquier otro fallo (sin red, cuerpo que no es JSON)
    // es una API que no está.
    throw new ApiError(controller.signal.aborted ? 'timeout' : 'offline', { cause: error })
  } finally {
    clearTimeout(timer)
    signal?.removeEventListener('abort', cancel)
  }
}

/**
 * ¿Responde la API? Con sus capacidades y los documentos del catálogo, o el motivo (`offline`, `timeout`, `http`).
 * Lo que aprende lo comparte con `health()`: si no, el primer `health()` de la app (con su límite de 1,5 s) podría
 * guardar `null` 30 s aunque la API acabe de contestar.
 */
export async function checkConnection({ timeout = CONNECTION_TIMEOUT_MS } = {}) {
  try {
    const response = await request('/health', { timeout })
    // Lo que contesta JSON en /health pero no dice ok: true no es la API (otro servidor en el mismo puerto).
    if (response?.ok !== true) return { ok: false, kind: 'offline' }
    healthCache = { at: Date.now(), value: response.capacidades ?? null }
    return { ok: true, capabilities: response.capacidades, documents: response.documentos }
  } catch (error) {
    return { ok: false, kind: error.kind }
  }
}

/** Capacidades de la API ({ busqueda_semantica, redaccion, … }) o null si no está disponible. Se cachea 30 s. */
export async function health({ force = false } = {}) {
  if (!force && Date.now() - healthCache.at < HEALTH_TTL_MS) return healthCache.value
  let value
  try {
    value = (await request('/health', { timeout: HEALTH_TIMEOUT_MS })).capacidades
  } catch {
    value = null
  }
  healthCache = { at: Date.now(), value }
  return value
}

export function resetHealthCache() {
  healthCache = { at: 0, value: null }
}

/**
 * Si falla, la próxima pregunta vuelve a revisar /health en vez de fiarse del caché de 30 s. Con `signal`, se puede
 * cancelar la respuesta en curso (lanza un `ApiError` `cancelled`, que no cuenta como API caída).
 */
export async function ask(payload, { signal } = {}) {
  try {
    return await request('/agent/ask', { method: 'POST', body: payload, signal })
  } catch (error) {
    if (error.kind !== 'cancelled') resetHealthCache()
    throw error
  }
}

export const profile = (userId) => request(`/profile/${encodeURIComponent(userId)}`, { timeout: 4000 })
/**
 * El orden de los accesos de la Home: `{ fixed, order: [{ id, score, reason }], personalized, request_id }` (ids del
 * backend; `request_id`, el de esta respuesta, va en los toques a los accesos).
 */
export const homeVerticals = (userId) => request(`/profile/${encodeURIComponent(userId)}/verticales`, { timeout: 4000 })
export const forget = (userId) => request(`/profile/${encodeURIComponent(userId)}`, { method: 'DELETE', timeout: 4000 })
/**
 * "Para ti" de rappi-ia: `{ user_id, interests, rows, requestId }`, con los productos de cada fila ya en el formato del
 * prototipo y marcados con su lugar (en el buscador con el agente, `para-ti`, su posición en la fila y la respuesta).
 */
export async function recommendations(userId, vertical) {
  const response = await request(
    `/recommendations?user_id=${encodeURIComponent(userId)}${vertical ? `&vertical=${vertical}` : ''}`,
    { timeout: 8000 },
  )
  const requestId = response.request_id ?? null
  return {
    ...response,
    requestId,
    rows: (response.rows ?? []).map((row) => ({
      ...row,
      products: placeList(row.products.map(toPrototypeProduct), { surface: 'agent', origin: 'para-ti', requestId }),
    })),
  }
}
/** Un lote de eventos, con lo que la app cuenta de su sesión (`session`: versión, plataforma, modo y entrada). */
export const sendEvents = (userId, events, session) =>
  request('/events', {
    method: 'POST',
    body: { user_id: userId, events, ...(session ? { session } : {}) },
    timeout: 5000,
  })
export const sendOrder = (order) => request('/orders', { method: 'POST', body: order, timeout: 5000 })

/**
 * Al cerrar la pestaña: envío que el navegador completa aunque la página se descargue. Va como text/plain a
 * /events/beacon (mismo JSON que /events): con application/json el navegador pediría un preflight CORS
 * que el beacon no puede hacer, y el envío se bloquearía. sendBeacon no manda cabeceras: el token va en el cuerpo.
 */
export function beaconEvents(userId, events, session) {
  if (typeof navigator === 'undefined' || !navigator.sendBeacon || events.length === 0) return false
  const body = { user_id: userId, events, ...(session ? { session } : {}), token: userToken() }
  const blob = new Blob([JSON.stringify(body)], { type: 'text/plain' })
  return navigator.sendBeacon(`${API_URL}/events/beacon`, blob)
}

// ── De la API al formato del prototipo ──────────────────────────────────────

/** Producto de la API → tarjeta del prototipo (el formato con que lo muestran las pantallas). */
export function toPrototypeProduct(p) {
  return {
    id: p.id,
    name: p.name,
    img: p.img || PLACEHOLDER_IMG,
    price: p.price,
    before: p.before ?? undefined,
    discount: p.discount ?? undefined,
    store: p.store ?? undefined,
    // Tienda a la que pertenece: en un plato es el restaurante (se abre por su menú), no una tienda.
    storeId: p.store_id ?? undefined,
    size: p.presentation ?? undefined,
    // La API no sabe el tiempo de entrega de un producto: no se inventa uno.
    eta: undefined,
    etaIcon: 'none',
    // Para registrar eventos y pedidos con los ids del catálogo real.
    entityType: p.entity_type,
    entityId: p.entity_id,
    concept: p.concept,
    // La vertical que usa la app es la del prototipo (la misma de la línea del carrito, sea cual sea la pantalla de
    // origen); la del backend se guarda para el pedido.
    vertical: screenForBackend(p.vertical) ?? p.vertical,
    backendVertical: p.vertical,
    ageRestricted: Boolean(p.age_restricted),
    // Agotado en su tienda, si la respuesta lo dice (`available: false` o `stock: 0`, como el listado de los pasillos;
    // lo que no lo trae, como "Para ti" de la tienda, lo revisa la fila al agregar: catalog.js, soldOutHere).
    ...(p.available === false || p.stock === 0 ? { soldOut: true } : {}),
  }
}

/** Nombre visible y ruta de una vertical de la API (null si el prototipo no la conoce). */
function verticalView(vertical) {
  const screen = screenForBackend(vertical)
  return screen ? { label: VERTICAL_NAMES[screen], route: routeForScreen(screen) } : { label: null, route: null }
}

// El origen de lo que Mochi pide solo ("Pedir por mí", api/autonomy.js): su `order_placed` lo lleva.
export const AUTO_ORDER_ORIGIN = 'agent-autopedido'

/**
 * El plan de "pide lo de siempre" que trae `/agent/ask` (`autopedido`) → `{ mode, store, lines: [{ product, qty }],
 * subtotal, cap, code, reason, basis, requestId }`. Los productos llevan su lugar (`agent-autopedido`).
 */
export function toAutoOrder(plan, requestId = null) {
  const products = placeList(
    plan.lineas.map((line) => toPrototypeProduct(line.product)),
    { surface: 'agent', origin: AUTO_ORDER_ORIGIN, requestId },
  )
  return {
    mode: plan.modo,
    store: plan.tienda,
    lines: products.map((product, i) => ({ product, qty: plan.lineas[i].qty })),
    subtotal: plan.subtotal,
    cap: plan.tope,
    code: plan.codigo,
    reason: plan.motivo,
    basis: plan.basis,
    requestId,
  }
}

/**
 * Respuesta de /agent/ask → mensaje del agente en el prototipo ({ text, products, reason, actions, suggestion… }). Los
 * productos quedan marcados con su lugar en la respuesta (`agent-ask`, o el servicio de la sugerencia) y su `request_id`.
 * Los de la sugerencia siguen la cuenta después de los de la respuesta: cada producto tiene su lugar en ella.
 */
export function toMessage(response) {
  const requestId = response.request_id ?? null
  const suggestionOrigin = response.service ?? 'agent-ask'
  const suggestion = response.suggestion
    ? {
        reason: response.suggestion.reason,
        question: response.suggestion.question,
        concept: response.suggestion.concept,
        // Código del backend para los eventos ('turbo' no es el 'express' del prototipo, que la API lee como conveniencia).
        vertical: response.suggestion.vertical,
        verticalLabel: verticalView(response.suggestion.vertical).label,
        route: verticalView(response.suggestion.vertical).route,
        // El gancho de un servicio (RappiTravel) se mide con su origen; las demás, como pregunta al agente.
        origin: suggestionOrigin,
        products: placeList(
          response.suggestion.products.map((p) => ({
            ...toPrototypeProduct(p),
            fromSuggestion: true,
            suggestionOrigin,
          })),
          { surface: 'agent', origin: suggestionOrigin, requestId, start: (response.products ?? []).length },
        ),
      }
    : null
  const alsoIn = response.also_in
    ? {
        label: response.also_in.label,
        verticals: response.also_in.verticals.map((v) => ({
          label: verticalView(v.vertical).label ?? v.vertical,
          route: verticalView(v.vertical).route,
          vertical: v.vertical, // el código del backend, para el `vertical_open` al abrirla
          items: v.items,
          stores: v.stores,
        })),
      }
    : null
  return {
    text: response.text,
    service: response.service ?? null,
    products: placeList((response.products ?? []).map(toPrototypeProduct), {
      surface: 'agent',
      origin: 'agent-ask',
      requestId,
    }),
    alsoIn,
    // La razón visible va con la sugerencia cruzada; aquí no se repite.
    reason: suggestion ? null : response.reason,
    suggestion,
    // Acciones de aclaración ("¿para pedir ya o para el súper?"): vuelven a preguntar con ese vertical. Una vertical
    // sola ("Ir a Farmacia", tras una pregunta de salud) lleva a su pantalla.
    actions: (response.actions ?? []).map((a) => {
      if (a.query) return { label: a.label, ask: { text: a.query, vertical: a.vertical } }
      // Lo que Mochi sabe hacer ("Repite lo de siempre": `recompra`, `plan`, `perfil`) y "Ver mis preferencias": los
      // resuelve el panel.
      if (a.capability) return { label: a.label, capability: a.capability }
      if (a.panel) return { label: a.label, panel: a.panel }
      if (a.vertical && !a.route) return { label: a.label, route: verticalView(a.vertical).route }
      return a
    }),
    // "Pide lo de siempre en…" (api/autonomy.js): el pedido que Mochi hace solo o deja para revisar antes.
    ...(response.autopedido ? { autoOrder: toAutoOrder(response.autopedido, requestId) } : {}),
    tags: response.tags ?? [],
    concepts: response.intent?.concepts ?? [],
    unmet: Boolean(response.unmet),
    ageNotice: Boolean(response.age_notice),
    health: Boolean(response.intent?.symptom), // síntomas o consejo médico: el panel no ofrece sus ideas debajo
    // El estado de la conversación que se devuelve como `previous` en el próximo mensaje (null: no se sigue) y si esta
    // respuesta siguió a la anterior ("más barato" tras "cerveza").
    conversation: response.conversation ?? null,
    followUp: Boolean(response.intent?.follow_up),
    // Qué entendió (`resumen`: el panel arma el resumen con el carro; `pedido`: muestra el último pedido) y, en una
    // preferencia dicha por chat, la lista que quedó.
    kind: response.intent?.kind ?? null,
    preferences: response.preferences ?? null,
    requestId,
    source: 'api',
  }
}
