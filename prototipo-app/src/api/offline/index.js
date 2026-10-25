// API SIMULADA EN EL NAVEGADOR, SOLO PARA LA DEMO SIN CONEXIÓN («Prototipo MVP.html», `npm run demo:html`).
//
// Es una copia simplificada del backend de rappi-ia para que la app abra sin la API: solo entra en el build de la demo
// (`vite build --mode demo`, con VITE_OFFLINE_DEMO=1; ver main.jsx) y nunca en el de desarrollo ni el de producción.
// Responde con los mismos formatos que la API (src/api/fixtures/ y client.js), a partir de:
// - una muestra del catálogo grabada de la API real (snapshot.json, `npm run demo:snapshot`): listas, tiendas, menús,
//   búsquedas, preguntas a Mochi, kits de ocasiones, complementos y la oferta real de cada paso de la escalera;
// - lo que la persona hace en este navegador (eventos y pedidos, en localStorage: state.js).
// Lo que calcula aquí replica, en corto, estos archivos del backend (si cambian allá, revisar acá):
// - rappi-ia/src/rappi_ia/motor/home.py ............ el orden de los accesos de la Home (motor.js: homeVerticals)
// - rappi-ia/src/rappi_ia/motor/combos.py, combos.toml y predict.py ... la escalera fina (motor.js: targetStep)
// - rappi-ia/src/rappi_ia/motor/model.py, data.py .. la afinidad propia, sin «Rappi hoy» (motor.js)
// - rappi-ia/src/rappi_ia/offers/engine.py ......... vertical por probar, recompra, volver, complementos (offers.js)
// - rappi-ia/src/rappi_ia/offers/winback.py y motor/model.py (replenishment) ... recompra y volver (winback.js)
// - rappi-ia/src/rappi_ia/offers/guards.py ......... lo que el agente nunca ofrece (offers.js: offerableProduct)
// - rappi-ia/src/rappi_ia/offers/featured.py ....... lo que se puede destacar (offers.js: featuredProduct; sus reglas,
//   offers/destacado.toml, llegan en meta.featured) y, con engine.py (_typical_first), lo que piden las personas del
//   panel (personas.js: sampleOf)
// - rappi-ia/src/rappi_ia/agent/tools.py ........... el foco de la búsqueda (_focus, en search.js) y el complemento
//   alternado (_takes_second, en offers.js: complementOf)
// - rappi-ia/src/rappi_ia/agent/rappi_agent.py ..... «qué me recomiendas» (search.js: recommend) y el texto del consejo
//   médico (ADVICE_*, en search.js: unrecorded)
// - rappi-ia/src/rappi_ia/agent/understand.py ...... síntomas y consejo médico (SYMPTOMS, MEDICINE_WORDS, ADVICE, en
//   search.js) para las preguntas que la muestra no grabó; las grabadas (eval/frases_usuarios/preguntas-libres.txt) salen
//   tal cual de la API real
// - rappi-ia/src/rappi_ia/events/store.py .......... el perfil de intereses (index.js: interests)
// - rappi-ia/src/rappi_ia/offers/profiles.py ....... los perfiles de gusto activos (tastes.js)
// - rappi-ia/src/rappi_ia/api/app.py y api/catalog.py ... las rutas (index.js, catalog.js, search.js)
// No hay población que aprenda (transiciones, popularidad, retención aprendida) ni búsqueda semántica, y lo pedido en
// la demo se repite sin esperar su ritmo (offers.js: repeatOffer): es una demo, no evidencia.
import { catalogRoute } from './catalog'
import { contractArticles, homeVerticals } from './motor'
import { makeOffer } from './offers'
import { ask, backendVertical, search } from './search'
import { loadSnapshot } from './snapshot'
import { addEvents, addOrder, clearState, readState, updateState } from './state'
import { profileOffer, tastesReply } from './tastes'

const DAY_MS = 86_400_000
// events/store.py: WEIGHTS y HALF_LIFE_DAYS del perfil de intereses.
const INTEREST_WEIGHTS = {
  order_placed: 5,
  cart_add: 3,
  suggestion_accepted: 3,
  view_item: 1.5,
  view_store: 1,
  search: 1,
}
const INTEREST_HALF_LIFE_DAYS = 14
const TOP_REASON = 'Lo más pedido estas semanas en {vertical}'

const json = (status, body) =>
  new Response(body === null ? null : JSON.stringify(body), {
    status,
    headers: body === null ? {} : { 'content-type': 'application/json' },
  })

const randomHex = () =>
  Array.from(crypto.getRandomValues(new Uint8Array(8)), (b) => b.toString(16).padStart(2, '0')).join('')

/** Un evento como lo guarda el backend: la vertical como código del catálogo y la hora en ms. */
const storedEvent = (event, now) => ({
  type: event.type,
  ts: now,
  vertical: backendVertical(event.vertical),
  concept_id: event.concept_id ?? null,
  entity_type: event.entity_type ?? null,
  entity_id: event.entity_id ?? null,
  payload: event.payload ?? {},
})

/** Interés por concepto con decaimiento de 14 días (events/store.py: profile), de sus eventos y pedidos. */
export function interests(snapshot, state, now) {
  const scores = {}
  const add = (concept, type, ts) => {
    if (!concept || !(type in INTEREST_WEIGHTS) || !snapshot.meta.concepts[concept]) return
    scores[concept] =
      (scores[concept] ?? 0) +
      INTEREST_WEIGHTS[type] * 0.5 ** (Math.max(now - ts, 0) / DAY_MS / INTEREST_HALF_LIFE_DAYS)
  }
  for (const e of state.events) if (e.payload?.mode !== 'actual') add(e.concept_id, e.type, e.ts)
  for (const o of state.orders) for (const line of o.lines) add(line.concept_id, 'order_placed', o.ts)
  return Object.entries(scores)
    .filter(([, s]) => s >= 0.05)
    .sort((a, b) => b[1] - a[1])
    .map(([concept, score]) => ({ concept, score: Math.round(score * 1000) / 1000 }))
}

/** «Para ti» (api/app.py: recommendations): el complemento de cada interés y, si falta, lo más pedido grabado. */
function recommendations(snapshot, state, now, query) {
  const { concepts, vertical_labels: labels } = snapshot.meta
  const current = backendVertical(query.get('vertical'))
  const limit = Number(query.get('limit')) || 3
  const mine = interests(snapshot, state, now).map((i) => i.concept)
  const rows = []
  const shown = new Set()
  for (const concept of mine.filter((c) => concepts[c].offerable).slice(0, 4)) {
    // api/app.py busca el complemento sin la persona: aquí no se alterna.
    const recorded = snapshot.complements[concept]
    const target = recorded?.reason?.concept
    if (!recorded || shown.has(target)) continue
    shown.add(target)
    const interest = concepts[concept]
    rows.push({
      reason: `Por tu interés en ${interest.emoji} ${interest.name.toLowerCase()}`,
      concept: target,
      vertical: recorded.vertical,
      prototype_vertical: recorded.prototype_vertical,
      products: recorded.products,
    })
    if (rows.length >= limit) break
  }
  const taken = new Set(rows.map((r) => r.vertical))
  const top = snapshot.recommendations.rows.find((r) => r.kind === 'lo_mas_pedido')
  if (rows.length < limit && top && top.vertical !== current && !taken.has(top.vertical))
    rows.push({ ...top, reason: contractArticles(TOP_REASON.replace('{vertical}', labels[top.vertical])) })
  return { user_id: query.get('user_id'), interests: mine.slice(0, 5), rows }
}

const ORDER_VERTICALS = [
  'restaurantes',
  'turbo',
  'supermercado',
  'farmacia',
  'mall',
  'licores',
  'conveniencia',
  'chocolateria',
]

/** La respuesta `{ status, body }` a una petición; `body: null` es un 204. */
export function route(snapshot, { method, path, query, body }, now = Date.now()) {
  const catalog = catalogRoute(snapshot, method, path, query)
  if (catalog) return { status: catalog.status ?? 200, body: catalog.body }
  const state = readState()
  const key = `${method} ${path}`
  if (key === 'GET /health')
    return {
      body: {
        ok: true,
        documentos: snapshot.documents,
        capacidades: { busqueda_semantica: 'demo sin conexión', redaccion: 'plantillas', faltantes: [] },
      },
    }
  if (key === 'GET /live') return { body: { ok: true } }
  if (key === 'POST /session') {
    const userId = body?.legacy_user_id || state.userId || `proto-${randomHex()}`
    updateState((s) => ({ ...s, userId }))
    return { body: { user_id: userId, token: `offline.${userId}` } }
  }
  if (key === 'GET /search') return { body: search(snapshot, query) }
  if (key === 'POST /agent/ask') {
    const mine = interests(snapshot, state, now).map((i) => i.concept)
    return { body: ask(snapshot, body, { interests: mine, userId: state.userId }) }
  }
  if (key === 'GET /agent/plans') return { body: snapshot.plans }
  if (key === 'POST /agent/offer') {
    const offer =
      body?.moment === 'perfil'
        ? profileOffer(snapshot, state, body.context?.perfil)
        : makeOffer(snapshot, state, now, body ?? {})
    return offer ? { body: offer } : { status: 204, body: null }
  }
  if (key === 'GET /recommendations') return { body: recommendations(snapshot, state, now, query) }
  if (key === 'POST /events' || key === 'POST /events/beacon') {
    const events = (body?.events ?? []).map((e) => storedEvent(e, now))
    addEvents(events)
    return key === 'POST /events' ? { body: { guardados: events.length } } : { status: 204, body: null }
  }
  if (key === 'POST /orders') {
    const vertical = backendVertical(body?.vertical)
    if (!ORDER_VERTICALS.includes(vertical) || !body?.lines?.length)
      return { status: 400, body: { detail: `Vertical desconocido: ${body?.vertical}` } }
    const order = { order_id: `o-${randomHex()}`, ts: now, vertical, mode: body.mode ?? 'propuesta', lines: body.lines }
    addOrder(order)
    return { body: { order_id: order.order_id, lineas_omitidas: 0 } }
  }
  const profile = /^\/profile\/([^/]+)(\/verticales|\/gustos)?$/.exec(path)
  if (profile) {
    const userId = decodeURIComponent(profile[1])
    if (method === 'DELETE' && !profile[2])
      return { body: { user_id: userId, concept: null, eventos_borrados: clearState() } }
    if (method === 'GET' && profile[2] === '/verticales')
      return { body: homeVerticals(state, now, snapshot.meta.vertical_labels) }
    if (method === 'GET' && profile[2] === '/gustos') return { body: tastesReply(snapshot, state) }
    if (method === 'GET' && !profile[2]) {
      const { concepts } = snapshot.meta
      const list = interests(snapshot, state, now).map((i) => ({
        ...i,
        label: `${concepts[i.concept].emoji} ${concepts[i.concept].name}`,
      }))
      return { body: { user_id: userId, interests: list } }
    }
  }
  return { status: 404, body: { detail: 'Not Found' } }
}

/** Espera `ms` (la API real tarda algo: sin pausa las animaciones de Mochi se ven raras); se rinde si se aborta. */
const pause = (ms, signal) =>
  new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms)
    signal?.addEventListener('abort', () => {
      clearTimeout(timer)
      reject(new DOMException('The operation was aborted.', 'AbortError'))
    })
  })

const parse = (text) => {
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}

/**
 * Reemplaza `fetch` (y `navigator.sendBeacon`) para las peticiones a `apiUrl`: las responde la API simulada. Las demás
 * (las fotos, por ejemplo) siguen yendo a la red.
 */
export function installOfflineApi(apiUrl) {
  const realFetch = window.fetch.bind(window)
  const ours = (url) => typeof url === 'string' && url.startsWith(apiUrl)
  window.fetch = async (input, init = {}) => {
    const url = typeof input === 'string' ? input : input?.url
    if (!ours(url)) return realFetch(input, init)
    const snapshot = await loadSnapshot()
    const { pathname, searchParams } = new URL(url.slice(apiUrl.length), 'http://demo.invalid')
    const request = {
      method: (init.method ?? 'GET').toUpperCase(),
      path: pathname,
      query: searchParams,
      body: typeof init.body === 'string' ? parse(init.body) : null,
    }
    await pause(request.path === '/agent/ask' ? 450 : 120, init.signal)
    const { status = 200, body } = route(snapshot, request)
    return json(status, body)
  }
  const realBeacon = navigator.sendBeacon?.bind(navigator)
  navigator.sendBeacon = (url, data) => {
    if (!ours(url)) return realBeacon ? realBeacon(url, data) : false
    Promise.all([loadSnapshot(), new Response(data).text()]).then(([snapshot, text]) =>
      route(snapshot, { method: 'POST', path: '/events/beacon', query: new URLSearchParams(), body: parse(text) }),
    )
    return true
  }
}
