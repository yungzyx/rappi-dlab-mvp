// Cliente de la API de rappi-ia para el panel. Si una consulta de datos simulados falla o tarda demasiado, usa la
// respuesta guardada en src/fixtures/sin-conexion (npm run fixtures: todas de una misma foto de la API) y la anota, con
// el origen y la fecha que trae el archivo, para avisar que el panel está en modo sin conexión. El uso del MVP (fuente
// prototipo) no tiene respaldo: sin la base viva no hay nada honesto que mostrar. En el panel en un solo HTML (npm run panel:html) no hay API: las
// respuestas vienen grabadas en el archivo (`virtual:panel-snapshot`, ver vite.config.js), cada una con su fuente.
import snapshot from 'virtual:panel-snapshot'

/**
 * Dónde está la API (la misma regla que la app): `VITE_API_URL` manda, sin la barra final. Sin ella: en el build de
 * producción, el mismo origen bajo `/api`; en desarrollo, el host desde donde se abrió la página en el puerto 8000.
 */
export function apiUrl(env, location) {
  const configured = env.VITE_API_URL?.trim().replace(/\/+$/, '')
  if (configured) return configured
  if (env.PROD || !devApiUrl) return '/api'
  return devApiUrl(location)
}

// Solo existe en desarrollo: el build de producción la descarta, y `dist/` no lleva rastros de «localhost» ni del puerto.
const devApiUrl = import.meta.env.DEV ? (location) => `http://${location?.hostname || 'localhost'}:8000` : undefined

export const API_URL = apiUrl(import.meta.env, typeof window !== 'undefined' ? window.location : undefined)
// El mismo tope que la API le da al panel (API_TIMEOUT_ANALYTICS_MS, 30 s, y su fila de 2 métricas a la vez). Hoy
// cada métrica responde en menos de 0,4 s (/analytics/weekly, unos 133 ms; el panel completo, unos 0,3 s: medido en
// una copia de la base el 17-10-2026): el margen es para una máquina cargada o una base fría.
const TIMEOUT_MS = 30_000

export const SOURCES = ['synthetic', 'prototype']

// Una por métrica, solo simuladas (el prototipo no tiene respaldo): cada una se carga recién si su consulta falla. El
// HTML suelto no las necesita (no tiene API que pueda fallar) y no las lleva.
const savedResponses =
  import.meta.env.MODE === 'panel-html'
    ? {}
    : import.meta.glob('../fixtures/sin-conexion/*.json', { import: 'default' })

/** De cuándo y de qué base son las respuestas grabadas (`{ fecha, base }`), o null con la API en vivo. */
export const SNAPSHOT_INFO = snapshot?.grabado ?? null

// «Ver cómo funciona» (src/demo/): respuestas de ejemplo que pisan a las grabadas mientras dura la demostración.
let demoResponses = {}

/** Solo en el HTML suelto: pone las respuestas de la demostración (`{}` vuelve a la foto) y olvida lo cargado. */
export function setDemoResponses(responses) {
  demoResponses = responses
  cache.clear()
}

/** Si lo que se ve trae eventos de ejemplo de la demostración (para rotularlo en cada sección del prototipo). */
export const isDemoActive = () => Object.keys(demoResponses).length > 0

const cache = new Map()
const listeners = new Set()
let fallbacks = [] // [{ key, name, reason }]; se reemplaza (nunca se muta) para useSyncExternalStore

function describeRequest(name, source) {
  if (!SOURCES.includes(source)) throw new Error(`Fuente desconocida: ${source}`)
  return { key: `${name}.${source}`, name, path: `/analytics/${name}?source=${source}`, expected: source }
}

class HttpError extends Error {}

// Métricas cuyo `data: null` es una respuesta válida: el motor todavía sin corrida.
const NULLABLE = ['motor']

/** Nunca mezclar fuentes: una respuesta que no trae la fuente pedida (o sus datos) se descarta. */
function dataFrom(body, expected, name) {
  const missing = NULLABLE.includes(name) ? body?.data === undefined : body?.data == null
  if (body?.source !== expected || missing) {
    throw new Error(`Se esperaba la fuente ${expected} y llegó ${body?.source ?? 'otra cosa'}`)
  }
  return body.data
}

async function fetchLive({ path, expected, name }) {
  const response = await fetch(`${API_URL}${path}`, { signal: AbortSignal.timeout(TIMEOUT_MS) })
  if (!response.ok) throw new HttpError(`respondió ${response.status}`)
  return dataFrom(await response.json(), expected, name)
}

async function fetchSaved({ key, expected, name }) {
  const load = savedResponses[`../fixtures/sin-conexion/${name}.json`]
  if (!load) throw new Error(`Sin conexión y sin datos guardados para "${key}"`)
  const body = await load()
  return { data: dataFrom(body, expected, name), saved: body.guardado ?? null }
}

/** Motivo legible de por qué no se usó la respuesta en vivo. */
function reasonFor(error) {
  if (error.name === 'TimeoutError') return `no respondió en ${TIMEOUT_MS / 1000} s`
  if (error instanceof HttpError) return error.message
  if (error instanceof TypeError) return 'no responde'
  return 'respuesta no válida'
}

const PROTOTYPE_OFFLINE_MESSAGE = 'La API no responde: el uso del MVP solo se ve con la base viva.'

/** Del panel en un solo HTML: la respuesta grabada, validada contra la fuente pedida igual que una en vivo. */
async function loadFromSnapshot({ key, name, expected }) {
  const body = demoResponses[key] ?? snapshot.respuestas[key]
  if (!body) throw new Error(`Este archivo no trae «${name}»: se grabó sin esa consulta.`)
  return { data: dataFrom(body, expected, name), offline: false, saved: null }
}

/** `isCurrent` dice si esta petición sigue siendo la de la caché: una vieja que falla tarde no ensucia el aviso. */
async function loadWithFallback(request, isCurrent) {
  try {
    return { data: await fetchLive(request), offline: false, saved: null }
  } catch (error) {
    if (request.expected === 'prototype') throw new Error(PROTOTYPE_OFFLINE_MESSAGE, { cause: error })
    console.warn(`rappi-ia: ${request.path} falló (${error.message}); se usan los datos guardados.`)
    const { data, saved } = await fetchSaved(request)
    if (isCurrent()) addFallback({ key: request.key, name: request.name, reason: reasonFor(error), guardado: saved })
    return { data, offline: true, saved }
  }
}

/**
 * Promesa (en caché por métrica y fuente) con `{ data, offline, saved }`; `saved` es el `guardado` del archivo
 * (`{ origen, fecha }`) cuando se usó una respuesta guardada. `name` es una métrica de /analytics.
 * Con la fuente prototipo, si la API falla la promesa se rechaza.
 */
export function loadAnalytics(name, source) {
  const request = describeRequest(name, source)
  if (!cache.has(request.key)) {
    const promise = snapshot
      ? loadFromSnapshot(request)
      : loadWithFallback(request, () => cache.get(request.key) === promise)
    promise.catch(() => {}) // quien la lea la ve rechazada; las que nadie alcanza a leer no son un error sin atender
    cache.set(request.key, promise)
  }
  return cache.get(request.key)
}

function notify() {
  listeners.forEach((listener) => listener())
}

function addFallback(fallback) {
  if (fallbacks.some((item) => item.key === fallback.key)) return
  fallbacks = [...fallbacks, fallback]
  notify()
}

export function subscribeConnection(listener) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** Consultas que se mostraron con datos guardados (vacío = todo en vivo). */
export function getFallbacks() {
  return fallbacks
}

/** Olvida lo cargado para volver a intentar con la API. */
export function retryConnection() {
  cache.clear()
  fallbacks = []
  notify()
}

/**
 * Olvida lo cargado de una fuente, para ver lo nuevo (p. ej. lo que se hizo en el prototipo durante la demo).
 * La caché no expira sola: /analytics/weekly tarda segundos y no se vuelve a pedir sin que alguien lo pida.
 */
export function refreshSource(source) {
  const suffix = `.${source}`
  for (const key of cache.keys()) if (key.endsWith(suffix)) cache.delete(key)
  fallbacks = fallbacks.filter((fallback) => !fallback.key.endsWith(suffix))
  notify()
}
