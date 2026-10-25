// Ayudantes para los tests que hablan con la API (no se importan desde la app).
// Las respuestas de ejemplo de src/api/fixtures/ las escriben los tests del backend (`make contract` en rappi-ia).

import { vi } from 'vitest'

const FIXTURES = import.meta.glob('../api/fixtures/*.json', { eager: true })

/** JSON de `src/api/fixtures/<name>.json` (una copia: cada test puede modificar la suya). */
export function fixture(name) {
  const module = FIXTURES[`../api/fixtures/${name}.json`]
  if (!module) throw new Error(`No existe la respuesta de ejemplo «${name}» en src/api/fixtures/`)
  return structuredClone(module.default)
}

// La sesión del navegador (`POST /session`): la que escribe el backend (`make contract`).
const SESSION_ROUTES = { 'POST /session': () => fixture('session') }

const json = (status, body) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })

/** Un `slow:<ms>` responde la fixture con el nombre del primer tramo de la ruta (`/health` → `health`), o `{}` si no hay. */
function slowBody(pathname) {
  try {
    return fixture(pathname.split('/')[1])
  } catch {
    return {}
  }
}

/** Espera `delay` ms; se rinde (como un fetch abortado) si la petición se aborta antes. */
function wait(delay, signal) {
  return new Promise((resolve, reject) => {
    const abort = () => {
      clearTimeout(timer)
      reject(new DOMException('The operation was aborted.', 'AbortError'))
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', abort)
      resolve()
    }, delay)
    if (signal?.aborted) abort()
    else signal?.addEventListener('abort', abort, { once: true })
  })
}

const isSlow = (value) => typeof value === 'object' && value !== null && typeof value.slow === 'number'

async function respond(route, req, signal) {
  const value = typeof route === 'function' ? route(req) : route
  if (value === undefined) return json(404, { detail: 'Not Found' })
  if (value === 'offline') throw new TypeError('Failed to fetch')
  if (typeof value === 'number')
    return value === 204 ? new Response(null, { status: 204 }) : json(value, { detail: `HTTP ${value}` })
  if (typeof value === 'string' && value.startsWith('slow:')) {
    await wait(Number(value.slice('slow:'.length)), signal)
    return json(200, slowBody(req.path))
  }
  if (isSlow(value)) {
    await wait(value.slow, signal)
    return respond(value.body, req, signal)
  }
  return json(200, value)
}

const KEY = /^(?:(GET|POST|PUT|DELETE) )?(\/[^?#\s]*)$/

/** 'GET /ruta' o '/ruta' → 'GET /ruta'. Una clave que no calza falla aquí: si no, la ruta se vería como un 404. */
function normalizeKey(key) {
  const match = KEY.exec(key)
  if (!match)
    throw new Error(`stubApi: clave inválida «${key}» (usa 'GET /ruta', 'POST /ruta' o '/ruta', sin query string)`)
  const [, method = 'GET', path] = match
  return `${method} ${path}`
}

/** La ruta de la petición: la clave exacta o, si no hay, un comodín `…/*` que calce con el inicio (el más largo gana). */
function findRoute(table, verb, pathname) {
  const exact = `${verb} ${pathname}`
  if (table.has(exact)) return table.get(exact)
  let best
  for (const key of table.keys()) {
    if (key.endsWith('/*') && exact.startsWith(key.slice(0, -1)) && (!best || key.length > best.length)) best = key
  }
  return best ? table.get(best) : undefined
}

/** El cuerpo de la petición como lo vería la API: JSON ya leído (o el texto, si no lo es); otros tipos, tal cual. */
function parseBody(body) {
  if (typeof body !== 'string') return body
  try {
    return JSON.parse(body)
  } catch {
    return body
  }
}

/**
 * Reemplaza `fetch` por respuestas de ejemplo. Las claves son 'GET /health', 'POST /agent/ask' (también PUT y DELETE) o
 * '/health' (sin método es GET) y se comparan con la ruta sin la query; cualquier otra clave lanza un error. El valor puede ser:
 * - un objeto: se responde 200 con ese JSON;
 * - un número: se responde ese estado (204, sin cuerpo: el cliente lo lee como null);
 * - 'offline': el fetch falla, como sin red;
 * - 'slow:<ms>': responde la fixture de la ruta pasados esos ms (se rinde si la petición se aborta);
 * - { slow: ms, body }: responde `body` (cualquiera de estos valores) pasados esos ms;
 * - (req) => valor: decide según `req = { method, path, query: URLSearchParams, body }` (el cuerpo, ya leído como JSON).
 * Una clave puede terminar en `/*` para calzar cualquier ruta que empiece así (`'GET /orders/*'`). `POST /session`
 * responde la sesión de ejemplo; las de `routes` la reemplazan.
 * Lo que no está en `routes` responde 404. Devuelve el mock de `fetch` para revisar las llamadas.
 */
export function stubApi(routes) {
  const table = new Map(
    Object.entries({ ...SESSION_ROUTES, ...routes }).map(([key, route]) => [normalizeKey(key), route]),
  )
  const fetchMock = vi.fn(async (url, { method = 'GET', body, signal } = {}) => {
    const { pathname, searchParams } = new URL(url)
    const verb = method.toUpperCase()
    const req = { method: verb, path: pathname, query: searchParams, body: parseBody(body) }
    return respond(findRoute(table, verb, pathname), req, signal)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}
