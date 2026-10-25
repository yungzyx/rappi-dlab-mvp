// Cliente de la API de rappi-ia (el agente: búsqueda híbrida, ofertas y eventos).
// Sin la API la app muestra «Sin conexión» con el agente (ver ConnectionGate).

import { VERTICAL_NAMES, routeForScreen, screenForBackend } from '../data/verticals'
import { PLACEHOLDER_IMG } from '../components/Img'
import { saveSession, storedUserId, userToken } from './user'

const DEFAULT_PORT = 8000
const HEALTH_TTL_MS = 30_000
const HEALTH_TIMEOUT_MS = 1500
const DEFAULT_TIMEOUT_MS = 8_000 // más que esto, el público ya nota la espera: la pregunta al agente muestra «Sin conexión»
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

// Solo existe en desarrollo: el build de producción la descarta, y `dist/` no lleva rastros de «localhost» ni del puerto.
const devApiUrl = import.meta.env.DEV
  ? (location) => `http://${location?.hostname || 'localhost'}:${DEFAULT_PORT}`
  : undefined

export const API_URL = apiUrl(import.meta.env, typeof window !== 'undefined' ? window.location : undefined)

let healthCache = { at: 0, value: null }

/**
 * Por qué falló una petición a la API: `offline` (no hay quien responda, o lo que responde no es la API),
 * `timeout` (no contestó a tiempo) o `http` (contestó con un error; `status` es su código).
 */
export class ApiError extends Error {
  constructor(kind, { status, cause } = {}) {
    super(kind === 'http' ? `API ${status}` : `API ${kind}`, { cause })
    this.name = 'ApiError'
    this.kind = kind
    this.status = status
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

/** La sesión de este navegador: la que ya tiene o, la primera vez, una nueva (la pide ConnectionGate al abrir). */
export const ensureSession = () => (userToken() ? Promise.resolve() : renewSession())

async function send(path, { method = 'GET', body, timeout = DEFAULT_TIMEOUT_MS, keepalive } = {}) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeout)
  const token = userToken()
  try {
    const response = await fetch(`${API_URL}${path}`, {
      method,
      body: body ? JSON.stringify(body) : undefined,
      headers: { ...(body ? { 'content-type': 'application/json' } : {}), ...(token ? { [TOKEN_HEADER]: token } : {}) },
      signal: controller.signal,
      ...(keepalive ? { keepalive: true } : {}),
    })
    if (!response.ok) throw new ApiError('http', { status: response.status })
    if (response.status === 204) return null
    return await response.json()
  } catch (error) {
    if (error instanceof ApiError) throw error
    // Solo el temporizador aborta; cualquier otro fallo (sin red, cuerpo que no es JSON) es una API que no está.
    throw new ApiError(controller.signal.aborted ? 'timeout' : 'offline', { cause: error })
  } finally {
    clearTimeout(timer)
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

/** Si falla, la próxima pregunta vuelve a revisar /health en vez de fiarse del caché de 30 s. */
export async function ask(payload) {
  try {
    return await request('/agent/ask', { method: 'POST', body: payload })
  } catch (error) {
    resetHealthCache()
    throw error
  }
}

export const profile = (userId) => request(`/profile/${encodeURIComponent(userId)}`, { timeout: 4000 })
/** El orden de los accesos de la Home: `{ fixed, order: [{ id, score, reason }], personalized }` (ids del backend). */
export const homeVerticals = (userId) => request(`/profile/${encodeURIComponent(userId)}/verticales`, { timeout: 4000 })
export const forget = (userId) => request(`/profile/${encodeURIComponent(userId)}`, { method: 'DELETE', timeout: 4000 })
/** "Para ti" de rappi-ia: `{ user_id, interests, rows }`, con los productos de cada fila ya en el formato del prototipo. */
export async function recommendations(userId, vertical) {
  const response = await request(
    `/recommendations?user_id=${encodeURIComponent(userId)}${vertical ? `&vertical=${vertical}` : ''}`,
    { timeout: 8000 },
  )
  return {
    ...response,
    rows: (response.rows ?? []).map((row) => ({ ...row, products: row.products.map(toPrototypeProduct) })),
  }
}
export const sendEvents = (userId, events) =>
  request('/events', { method: 'POST', body: { user_id: userId, events }, timeout: 5000 })
export const sendOrder = (order) => request('/orders', { method: 'POST', body: order, timeout: 5000 })

/**
 * Al cerrar la pestaña: envío que el navegador completa aunque la página se descargue. Va como text/plain a
 * /events/beacon (mismo JSON que /events): con application/json el navegador pediría un preflight CORS
 * que el beacon no puede hacer, y el envío se bloquearía. sendBeacon no manda cabeceras: el token va en el cuerpo.
 */
export function beaconEvents(userId, events) {
  if (typeof navigator === 'undefined' || !navigator.sendBeacon || events.length === 0) return false
  const blob = new Blob([JSON.stringify({ user_id: userId, events, token: userToken() })], { type: 'text/plain' })
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
  }
}

/** Nombre visible y ruta de una vertical de la API (null si el prototipo no la conoce). */
function verticalView(vertical) {
  const screen = screenForBackend(vertical)
  return screen ? { label: VERTICAL_NAMES[screen], route: routeForScreen(screen) } : { label: null, route: null }
}

/** Respuesta de /agent/ask → mensaje del agente en el prototipo ({ text, products, reason, actions, suggestion… }). */
export function toMessage(response) {
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
        origin: response.service ?? 'agent-ask',
        products: response.suggestion.products.map((p) => ({
          ...toPrototypeProduct(p),
          fromSuggestion: true,
          suggestionOrigin: response.service ?? 'agent-ask',
        })),
      }
    : null
  const alsoIn = response.also_in
    ? {
        label: response.also_in.label,
        verticals: response.also_in.verticals.map((v) => ({
          label: verticalView(v.vertical).label ?? v.vertical,
          route: verticalView(v.vertical).route,
          items: v.items,
          stores: v.stores,
        })),
      }
    : null
  return {
    text: response.text,
    service: response.service ?? null,
    products: (response.products ?? []).map(toPrototypeProduct),
    alsoIn,
    // La razón visible va con la sugerencia cruzada; aquí no se repite.
    reason: suggestion ? null : response.reason,
    suggestion,
    // Acciones de aclaración ("¿para pedir ya o para el súper?"): vuelven a preguntar con ese vertical. Una vertical
    // sola («Ir a Farmacia», tras una pregunta de salud) lleva a su pantalla.
    actions: (response.actions ?? []).map((a) => {
      if (a.query) return { label: a.label, ask: { text: a.query, vertical: a.vertical } }
      if (a.vertical && !a.route) return { label: a.label, route: verticalView(a.vertical).route }
      return a
    }),
    tags: response.tags ?? [],
    concepts: response.intent?.concepts ?? [],
    unmet: Boolean(response.unmet),
    ageNotice: Boolean(response.age_notice),
    health: Boolean(response.intent?.symptom), // síntomas o consejo médico: el panel no ofrece sus ideas debajo
    source: 'api',
  }
}
