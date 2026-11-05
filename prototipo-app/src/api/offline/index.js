// API SIMULADA EN EL NAVEGADOR, SOLO PARA LA DEMO SIN CONEXIÓN ("Prototipo MVP.html", `npm run demo:html`).
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
// - rappi-ia/src/rappi_ia/motor/model.py, data.py .. la afinidad propia, sin "Rappi hoy" (motor.js)
// - rappi-ia/src/rappi_ia/offers/engine.py ......... vertical por probar, recompra, volver, complementos (offers.js) y
//   las tiendas de un kit recortado por la dieta (offers.js: kitStores; el kit mismo es el grabado). Sin oferta grabada
//   para el paso, la vertical por probar cae a la de siempre como el backend (_usual_to_try), pero solo a la grabada
//   (`toTry.usual`, el súper, con "Aún no pides en…"): si la persona ya pide ahí, no ofrece nada, y no elige otra
//   vertical por afinidad ni dice "Por tu interés en…" (offers.js: usualToTry)
// - rappi-ia/src/rappi_ia/offers/winback.py y motor/model.py (replenishment) ... recompra y volver (winback.js), con la
//   pausa por una calificación mala (winback.js: paused, de los eventos `order_rated`); un pedido cancelado
//   (`order_cancelled`, state.js: cancelOrders e isConfirmed) no cuenta para la recompra, el motor ni los perfiles
// - rappi-ia/src/rappi_ia/offers/engine.py (ontop_offer) ... el OnTop de Turbo en el seguimiento (offers.js: onTopOffer)
// - rappi-ia/src/rappi_ia/catalog/stores.py (line_prices) y api/catalog.py (availability) ... "Pídelo de nuevo"
//   (index.js: availability, con los precios de la muestra)
// - rappi-ia/src/rappi_ia/offers/guards.py ......... lo que el agente nunca ofrece (offers.js: offerableProduct); las
//   palabras de alcohol y bebé llegan en meta.guards (guards.js; sin ellas, su copia a mano, que guards.test.js compara
//   con guards.py). Las tiendas que Rappi rotula Farmacia, Sex shop o Smoking shop no se distinguen en la muestra
//   (engine.py: _offerable_products las lee de store_verticals, que la API no da): solo cuenta la vertical
// - rappi-ia/src/rappi_ia/offers/featured.py ....... lo que se puede destacar (offers.js: featuredProduct; sus reglas,
//   offers/destacado.toml, llegan en meta.featured) y, con engine.py (_typical_first), lo que piden las personas del
//   panel (personas.js: sampleOf)
// - rappi-ia/src/rappi_ia/agent/tools.py ........... el foco de la búsqueda (_focus, en search.js) y el complemento
//   alternado (_takes_second, en offers.js: complementOf)
// - rappi-ia/src/rappi_ia/agent/rappi_agent.py ..... "qué me recomiendas" (search.js: recommend) y el texto del consejo
//   médico (ADVICE_*, en search.js: unrecorded)
// - rappi-ia/src/rappi_ia/agent/understand.py ...... síntomas y consejo médico (SYMPTOMS, MEDICINE_WORDS, ADVICE, en
//   search.js) para las preguntas que la muestra no grabó; las grabadas (eval/frases_usuarios/preguntas-libres.txt) salen
//   tal cual de la API real
// - rappi-ia/src/rappi_ia/agent/understand.py (_follow_up) y rappi_agent.py (_conversation, _without, _keeps, DIETS) ...
//   seguir la conversación (conversation.js); los seguimientos de eval/frases_usuarios/conversaciones.txt salen grabados
// - rappi-ia/src/rappi_ia/agent/rappi_agent.py (DAILY_CROSS_CAP) y events/store.py (cross_suggestions_today) ... el tope
//   diario de sugerencias cruzadas en las respuestas de Mochi (index.js: crossCapped)
// No se replica la corrección de errores de tipeo (retrieval/spelling.py, también en rappi_agent.py: _misspelled): sin
// conexión, lo mal escrito se responde como lo escrito, salvo lo grabado (las de eval/typos.json y las de la
// presentación, en scripts/demo-snapshot.mjs: TYPOS), que sale con la corrección de la API.
// - rappi-ia/src/rappi_ia/events/store.py .......... el perfil de intereses (index.js: interests) y el sobre de cada
//   evento (index.js: storedEvent; el origen, en `origin` o, en los eventos de antes, `payload.origen`); las impresiones
//   (`list_view`) no se guardan, y sin conexión no hay grupo de control de las ofertas (OFFERS_CONTROL_PCT)
// - rappi-ia/src/rappi_ia/api/app.py (_search_concept y _log_ask) ... el concepto de una búsqueda lo deduce el servidor
//   del texto, corregido si lo hay (index.js: searchConcept), y cada pregunta a Mochi guarda un `ask` con el suyo
//   (index.js: askEvent). Los pesos, el tope diario, los límites de "Pedir por mí", la recompra y "volver" se comparan
//   con el backend en parity.test.js
// - rappi-ia/src/rappi_ia/offers/profiles.py ....... los perfiles de gusto activos (tastes.js)
// - rappi-ia/src/rappi_ia/catalog/hours.py y catalog/restaurants.py (filtros, "Destacados", with_hours) ... abierto o
//   cerrado según el horario publicado y los filtros de restaurantes (catalog.js); las búsquedas recientes de
//   events/searches.py (index.js: searchesReply). Sin conexión no hay "Lo más buscado", "Lo que sea", comparar entre
//   tiendas ni "Para ti" en la tienda: esas rutas responden 404 o vacío y la app no las muestra. Las tiendas de la
//   búsqueda solo llegan en las respuestas grabadas (`places`), y solo las de la muestra (scripts/demo-snapshot.mjs).
// - rappi-ia/src/rappi_ia/offers/preferences.py y preferencias.toml, api/preferences.py y rappi_agent.py
//   (_preference) ... las preferencias explícitas: en la hoja del panel (con las tiendas de sus pedidos), lo que llega
//   escrito por el buscador, el filtro y el orden de lo que Mochi muestra y ofrece, y el filtro del buscador con
//   `user_id` (preferences.js; index.js: preferenceAnswer, withPreferences, searchedWithPreferences)
// - rappi-ia/src/rappi_ia/agent/rappi_agent.py (_small_talk, HELP_ACTIONS, IDEA_KINDS), understand.py (APP_QUESTIONS,
//   GREETING_WORDS, THANKS_WORDS, LAUGHTER) y compose.py ... el saludo, el "gracias", el fuera de tema y lo vacío, la
//   ayuda con los atajos de lo que Mochi sabe hacer, el resumen antes de pagar y el último pedido (search.js:
//   smallTalk, appQuestion, helpReply). Los textos del resumen y del pedido son los de la app (useAgentAnswers.js)
// - rappi-ia/src/rappi_ia/catalog/terms.py ........ las condiciones de compra de las tiendas (catalog.js: storeTerms;
//   la muestra solo sabe el envío de los restaurantes)
// - rappi-ia/src/rappi_ia/offers/autonomy.py, api/autonomy.py, agent/understand.py (USUAL_ORDER), rappi_agent.py
//   (_usual_order), api/agent.py (_with_auto_order) y api/app.py (_auto_order, post_order) ... "Pedir por mí": el
//   permiso, "pide lo de siempre en…", el botón de la recompra, la revisión del pedido que Mochi hace solo
//   (autonomy.js) y los 400 de un autopedido programado o una franja que no es de hoy ni de mañana. Las tiendas que
//   Rappi rotula Farmacia, Sex shop o Smoking shop no se distinguen en la muestra (solo la vertical)
// - rappi-ia/src/rappi_ia/api/app.py y api/catalog.py ... las rutas (index.js, catalog.js, search.js), con el
//   `request_id` de las respuestas que ordenan cosas (index.js: served)
// No hay población que aprenda (transiciones, popularidad, retención aprendida) ni búsqueda semántica, y lo pedido en
// la demo se repite sin esperar su ritmo (offers.js: repeatOffer): es una demo, no evidencia.
import {
  autonomyReply,
  checkAutoOrder,
  orderedStores,
  saveAutonomy,
  turnOffAutonomy,
  usualAnswer,
  withAutoOrder,
} from './autonomy'
import { catalogRoute } from './catalog'
import { contractArticles, homeVerticals } from './motor'
import { kitStores, makeOffer } from './offers'
import { applied, cleaned, CUISINES, describe, findStore, options, readCommand, withoutOf } from './preferences'
import { ask, backendVertical, detectConcepts, search } from './search'
import { loadSnapshot } from './snapshot'
import { addEvents, addOrder, cancelOrders, clearState, readState, updateState } from './state'
import { profileOffer, tastesReply } from './tastes'

const DAY_MS = 86_400_000
// events/store.py: WEIGHTS y HALF_LIFE_DAYS del perfil de intereses.
export const INTEREST_WEIGHTS = {
  order_placed: 5,
  cart_add: 3,
  suggestion_accepted: 3,
  recommendation_click: 2,
  view_item: 1.5,
  view_store: 1,
  search: 1,
  ask: 1,
}
export const INTEREST_HALF_LIFE_DAYS = 14
const TOP_REASON = 'Lo más pedido estas semanas en {vertical}'

const json = (status, body) =>
  new Response(body === null ? null : JSON.stringify(body), {
    status,
    headers: body === null ? {} : { 'content-type': 'application/json' },
  })

const randomHex = () =>
  Array.from(crypto.getRandomValues(new Uint8Array(8)), (b) => b.toString(16).padStart(2, '0')).join('')

/** El concepto de una búsqueda (api/app.py: _search_concept): no se le cree a la app, se deduce del texto corregido si
 * lo hay. En "Rappi hoy" no se aprende. */
const searchConcept = (snapshot, event) => {
  if (event.payload?.mode === 'actual') return null
  const corrected = event.payload?.corregida
  const text = typeof corrected === 'string' && corrected ? corrected : event.query
  return (text && detectConcepts(snapshot.meta, text)[0]) || null
}

/** Un evento como lo guarda el backend: la vertical como código del catálogo, la hora en ms y su origen (`origin`, o
 * `payload.origen` de un cliente de antes: events/store.py, _origin). */
const storedEvent = (snapshot, event, now) => ({
  type: event.type,
  ts: now,
  vertical: backendVertical(event.vertical),
  concept_id: event.type === 'search' ? searchConcept(snapshot, event) : (event.concept_id ?? null),
  entity_type: event.entity_type ?? null,
  entity_id: event.entity_id ?? null,
  cart_id: event.cart_id ?? null,
  query: event.query ?? null,
  origin: event.origin ?? event.payload?.origen ?? null,
  payload: event.payload ?? {},
})

// agent/rappi_agent.py: DAILY_CROSS_CAP. Cuenta las sugerencias de las respuestas (`agent-ask`) que vio hoy, en Santiago.
export const DAILY_CROSS_CAP = 5
const santiagoDay = (ms) => new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Santiago' }).format(ms)
const crossCapped = (state, now) =>
  state.events.filter(
    (e) => e.type === 'suggestion_shown' && e.origin === 'agent-ask' && santiagoDay(e.ts) === santiagoDay(now),
  ).length >= DAILY_CROSS_CAP
// Las respuestas grabadas traen su sugerencia: con el tope cumplido se responde sin ella (su texto no la nombra).
const withoutSuggestion = ({ suggestion: _suggestion, ...reply }) => ({ ...reply, reason: null })

/** Una respuesta que ordena cosas, con su `request_id` (api/logs.py: served_request_id), como la de la API. */
const served = (body) => body && { ...body, request_id: `offline-${randomHex()}` }

// api/app.py: SCHEDULE_AHEAD y _schedulable (una franja futura, con una hora de margen, de hoy o mañana).
const SCHEDULE_AHEAD_MS = 2 * DAY_MS
const schedulable = (when, now) => {
  const moment = typeof when === 'number' ? when : Date.parse(when)
  return Number.isFinite(moment) && now - 3_600_000 <= moment && moment <= now + SCHEDULE_AHEAD_MS
}

// Las rutas cuyas respuestas llevan `request_id` en la API.
const SERVED = new Set([
  'GET /search',
  'POST /agent/ask',
  'POST /agent/offer',
  'GET /recommendations',
  'GET /catalog/home',
])

/**
 * Interés por concepto con decaimiento de 14 días (events/store.py: profile), de sus eventos. Los pedidos no suman
 * aparte: en la API el `order_placed` de un pedido no lleva concepto (events/store.py: record_order).
 */
export function interests(snapshot, state, now) {
  const scores = {}
  const add = (concept, type, ts) => {
    if (!concept || !(type in INTEREST_WEIGHTS) || !snapshot.meta.concepts[concept]) return
    scores[concept] =
      (scores[concept] ?? 0) +
      INTEREST_WEIGHTS[type] * 0.5 ** (Math.max(now - ts, 0) / DAY_MS / INTEREST_HALF_LIFE_DAYS)
  }
  for (const e of state.events) if (e.payload?.mode !== 'actual') add(e.concept_id, e.type, e.ts)
  return Object.entries(scores)
    .filter(([, s]) => s >= 0.05)
    .sort((a, b) => b[1] - a[1])
    .map(([concept, score]) => ({ concept, score: Math.round(score * 1000) / 1000 }))
}

/** "Para ti" (api/app.py: recommendations): el complemento de cada interés y, si falta, lo más pedido grabado. */
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
      concept_label: concepts[target]?.name,
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

/**
 * "Pídelo de nuevo" (api/catalog.py: availability): cada línea con su precio en la misma tienda, si la muestra tiene ese
 * producto ahí (un plato, en su restaurante); si no, no disponible. Es la muestra grabada, no el precio de hoy.
 */
export function availability(snapshot, lines) {
  return {
    lines: lines.map((line) => {
      const found = snapshot.pool.find(
        (p) =>
          p.entity_type === line.entity_type &&
          String(p.entity_id) === String(line.entity_id) &&
          (line.store_id == null || p.store_id === line.store_id),
      )
      const price = found?.price_value ?? null
      return { ...line, store_id: line.store_id ?? null, available: price != null, price }
    }),
  }
}

/**
 * Antes de escribir (events/searches.py): las búsquedas recientes de este navegador, sin repetir. Sin conexión no hay
 * población de la que sacar "Lo más buscado": va vacío y sin población declarada.
 */
function searchesReply(state) {
  const seen = new Set()
  const recent = []
  for (const event of [...state.events].reverse()) {
    const text = event.type === 'search' ? event.query?.trim() : ''
    if (!text || seen.has(text.toLowerCase())) continue
    seen.add(text.toLowerCase())
    recent.push(text)
    if (recent.length === 6) break
  }
  return { recientes: recent, mas_buscado: [], poblacion: null }
}

/**
 * Una respuesta con productos (de /agent/ask o una fila de "Para ti") con la dieta y las alergias de la persona
 * aplicadas, y sus favoritas primero; con `notice`, lo que dice al mostrar comida (rappi_agent.py: reply).
 */
function withPreferences(snapshot, state, reply, { notice = false } = {}) {
  const mine = applied(snapshot.meta, state.preferences)
  if (!mine.any || !reply) return reply
  const products = mine.products(reply.products ?? [])
  const suggestion = reply.suggestion && { ...reply.suggestion, products: mine.products(reply.suggestion.products) }
  const said =
    notice && reply.intent?.kind !== 'preferencia' ? mine.notice([...products, ...(suggestion?.products ?? [])]) : null
  return {
    ...reply,
    products,
    ...(reply.suggestion ? { suggestion } : {}),
    ...(said ? { text: `${reply.text} ${said}` } : {}),
  }
}

/**
 * api/app.py (search): con `user_id`, la dieta y las alergias de la persona filtran lo buscado, sin ordenar por sus
 * favoritas, y `preferences_notice` lo dice. Si sacaron todo, no es "sin resultado": la muestra sí lo tenía.
 */
function searchedWithPreferences(snapshot, state, found, query) {
  const mine = applied(snapshot.meta, query.get('user_id') ? (state.preferences ?? []) : [])
  let dropped = 0
  const keep = (products) => {
    const kept = mine.keep(products)
    dropped += products.length - kept.length
    return kept
  }
  const reply = found.groups
    ? {
        ...found,
        groups: found.groups.map((g) => ({ ...g, products: keep(g.products) })).filter((g) => g.products.length),
      }
    : { ...found, products: keep(found.products) }
  const shown = reply.groups ? reply.groups.flatMap((g) => g.products) : reply.products
  const emptied = dropped > 0 && !shown.length
  return {
    ...reply,
    ...(emptied ? { unmet: false, unmet_reason: null } : {}),
    preferences_notice: mine.notice(shown, dropped),
  }
}

/** api/agent.py (_with_preferences): una oferta que se queda sin lo que traía no se ofrece (204). */
function offeredWithPreferences(snapshot, state, offer) {
  const mine = applied(snapshot.meta, state.preferences)
  if (!mine.any) return offer
  if (offer.escalera) {
    const steps = offer.escalera
      .map((step) => ({ ...step, kept: mine.products(step.products), had: step.products.length }))
      .filter((step) => step.kept.length || !step.had)
      .map(({ kept, had: _had, ...step }) => ({ ...step, products: kept }))
    return steps.length ? { ...offer, escalera: steps } : null
  }
  const products = mine.products(offer.products ?? [])
  if (offer.products?.length && !products.length) return null
  // Lo que la dieta sacó de un kit ya no suma en su tienda (api/agent.py: offer).
  return offer.stores ? { ...offer, products, stores: kitStores(products, offer.stores) } : { ...offer, products }
}

/**
 * El `ask` que deja cada pregunta a Mochi (api/app.py: _log_ask), con el primer concepto de lo que entendió: suma al
 * perfil de intereses. En "Rappi hoy" o si habla de sus preferencias (una alergia es un dato de salud), sin concepto.
 */
function askEvent(snapshot, body, reply, now) {
  const mode = body?.mode ?? 'propuesta'
  const learns = mode !== 'actual' && reply?.intent?.kind !== 'preferencia'
  const concept = learns ? (reply?.intent?.concepts?.[0] ?? null) : null
  return storedEvent(snapshot, { type: 'ask', concept_id: concept, payload: { mode } }, now)
}

// rappi_agent.py: los textos de `_preference`.
const PREFERENCES_TODAY =
  'En "Rappi hoy" no guardo preferencias. En la propuesta recuerdo tu dieta, tus alergias y tus favoritas, y las ' +
  'borras cuando quieras 🔒.'
const PREFERENCES_NONE =
  'Todavía no tengo preferencias tuyas. Márcalas en "Mis preferencias": tu dieta, tus alergias y tus cocinas y ' +
  'tiendas favoritas.'
const joinNames = (names) => (names.length === 1 ? names[0] : `${names.slice(0, -1).join(', ')} y ${names.at(-1)}`)

/**
 * "soy vegetariano", "no como maní", "mi tienda favorita es…", "muéstrame mis preferencias", "olvida mis preferencias"
 * (rappi_agent.py: _preference): las guarda en el estado de la API simulada y dice cuáles quedaron. null si el mensaje
 * no habla de sus preferencias.
 */
function preferenceAnswer(snapshot, state, body) {
  let command = readCommand(String(body.message ?? ''))
  if (command?.cuisineText !== undefined) {
    const said = command.cuisineText
    const found = [...detectConcepts(snapshot.meta, said), ...detectConcepts(snapshot.meta, `comida ${said}`)]
    const cuisines = [...new Set(found)].filter((c) => CUISINES.includes(c))
    command = cuisines.length ? { action: 'agregar', items: cuisines.map((c) => ({ tipo: 'cocina', valor: c })) } : null
  }
  if (!command) return null
  const reply = (text, extra = {}) => ({
    text,
    products: [],
    vertical: null,
    prototype_vertical: null,
    intent: { kind: 'preferencia', query: '', concepts: [], vertical: null, confidence: 1, follow_up: false },
    reason: null,
    suggestion: null,
    actions: [],
    tags: [],
    stores: [],
    unmet: false,
    unmet_reason: null,
    age_notice: false,
    conversation: null,
    ...extra,
  })
  if (body.mode === 'actual') return reply(PREFERENCES_TODAY)
  const { meta } = snapshot
  let items = command.items
  if (command.store) {
    const store = findStore(snapshot, command.store)
    if (!store)
      return reply(
        `No encontré "${command.store}" entre las tiendas de Rappi. Elige tus favoritas en "Mis preferencias".`,
        {
          actions: [{ label: 'Ver mis preferencias', panel: 'preferencias' }],
        },
      )
    items = [...items, { tipo: 'tienda', valor: store }]
  }
  const current = state.preferences ?? []
  const same = (a) => (b) => a.tipo === b.tipo && a.valor === b.valor
  const names = describe(meta, items).map((p) => p.nombre)
  let text = null
  let next = current
  if (command.action === 'agregar') {
    next = cleaned(snapshot, [...current, ...items], [...current, ...items])
    const filters = items.filter((p) => p.tipo === 'dieta' || p.tipo === 'alergia')
    const parts = [`Anotado: ${joinNames(names)} 🧡.`]
    if (filters.length) {
      parts.push(
        `Desde ahora saco de lo que te muestro lo que dice tener ${withoutOf(filters, { joined: true })}. ` +
          'Lo veo por el nombre del producto: revisa siempre los ingredientes en la tienda.',
      )
    }
    if (items.some((p) => p.tipo === 'cocina' || p.tipo === 'tienda'))
      parts.push('Cuando calce con lo que buscas, lo pongo primero.')
    parts.push('Lo cambias cuando quieras en "Mis preferencias".')
    text = parts.join(' ')
  } else if (command.action === 'quitar') {
    next = current.filter((p) => !items.some((item) => same(item)(p)))
    text = `Listo, ya no tengo en cuenta: ${joinNames(names)}.`
  } else if (command.action === 'olvidar') {
    next = []
    text = 'Listo, olvidé tus preferencias 🔒.'
  }
  if (next !== current) updateState((s) => ({ ...s, preferences: next }))
  const listed = describe(meta, next)
  if (!text) {
    const filters = listed.filter((p) => p.tipo === 'dieta' || p.tipo === 'alergia').map((p) => p.nombre)
    const favorites = listed.filter((p) => p.tipo === 'cocina' || p.tipo === 'tienda').map((p) => p.nombre)
    const parts = [
      ...(filters.length ? [`Dieta y alergias: ${filters.join(', ')}.`] : []),
      ...(favorites.length ? [`Tus favoritas: ${favorites.join(', ')}.`] : []),
    ]
    text = listed.length
      ? `Esto recuerdo de ti. ${parts.join(' ')} Las cambias o las olvidas en "Mis preferencias".`
      : PREFERENCES_NONE
  }
  return reply(text, {
    preferences: listed,
    actions: [{ label: 'Ver mis preferencias', panel: 'preferencias' }],
  })
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
export function route(snapshot, request, now = Date.now()) {
  const reply = answer(snapshot, request, now)
  const key = `${request.method} ${request.path}`
  const ranked =
    SERVED.has(key) || (request.method === 'GET' && /^\/profile\/[^/]+\/(verticales|busquedas)$/.test(request.path))
  return ranked && (reply.status ?? 200) === 200 ? { ...reply, body: served(reply.body) } : reply
}

function answer(snapshot, { method, path, query, body }, now) {
  const catalog = catalogRoute(snapshot, method, path, query, now)
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
  if (key === 'POST /catalog/availability') return { body: availability(snapshot, body?.lines ?? []) }
  if (key === 'GET /search') return { body: searchedWithPreferences(snapshot, state, search(snapshot, query), query) }
  if (key === 'POST /agent/ask') {
    const said = preferenceAnswer(snapshot, state, body ?? {}) ?? usualAnswer(snapshot, state, body ?? {}, now)
    if (said) {
      addEvents([askEvent(snapshot, body, said, now)])
      return { body: said }
    }
    const mine = interests(snapshot, state, now).map((i) => i.concept)
    const asked = ask(snapshot, body, { interests: mine, userId: state.userId })
    const reply = asked?.suggestion && crossCapped(state, now) ? withoutSuggestion(asked) : asked
    addEvents([askEvent(snapshot, body, reply, now)])
    return { body: body?.mode === 'actual' ? reply : withPreferences(snapshot, state, reply, { notice: true }) }
  }
  if (key === 'GET /agent/plans') return { body: snapshot.plans }
  if (key === 'POST /agent/offer') {
    const offer =
      body?.moment === 'perfil'
        ? profileOffer(snapshot, state, body.context?.perfil)
        : makeOffer(snapshot, state, now, body ?? {})
    const kept = offer && offeredWithPreferences(snapshot, state, offer)
    const made = body?.moment === 'recompra' ? withAutoOrder(snapshot, state, kept) : kept
    return made ? { body: made } : { status: 204, body: null }
  }
  if (key === 'GET /recommendations') {
    const reply = recommendations(snapshot, state, now, query)
    const rows = reply.rows.map((row) => withPreferences(snapshot, state, row)).filter((row) => row.products.length)
    return { body: { ...reply, rows } }
  }
  if (key === 'POST /events' || key === 'POST /events/beacon') {
    // Las impresiones (`list_view`, api/impressions.js) no se guardan: sin conexión nada las lee, y llenarían el
    // almacenamiento del navegador. Cuentan como recibidas, como en la API.
    const sent = body?.events ?? []
    const stored = sent.filter((e) => e.type !== 'list_view').map((e) => storedEvent(snapshot, e, now))
    addEvents(stored)
    cancelOrders(stored) // un pedido cancelado deja de contar (events/store.py: _record_cancellations)
    return key === 'POST /events' ? { body: { guardados: sent.length } } : { status: 204, body: null }
  }
  if (key === 'POST /orders') {
    const vertical = backendVertical(body?.vertical)
    if (!ORDER_VERTICALS.includes(vertical) || !body?.lines?.length)
      return { status: 400, body: { detail: `Vertical desconocido: ${body?.vertical}` } }
    // Un pedido es de una tienda (api/app.py: post_order).
    if (new Set(body.lines.map((line) => line.store_id).filter((id) => id != null)).size > 1)
      return { status: 400, body: { detail: 'Un pedido es de una sola tienda' } }
    // "Pedir por mí" pide para ahora, y una franja es de hoy o mañana (api/app.py: post_order y _schedulable).
    if (body.autopedido && body.scheduled_for != null)
      return { status: 400, body: { detail: 'Un pedido de Mochi no se programa' } }
    if (body.scheduled_for != null && !schedulable(body.scheduled_for, now))
      return { status: 400, body: { detail: 'Solo se programa para hoy o mañana' } }
    // Un pedido que Mochi hizo solo se vuelve a revisar con lo de siempre de ahora (api/app.py: _auto_order).
    const auto = body.autopedido ? checkAutoOrder(snapshot, state, body, now) : null
    if (auto?.status) return auto
    const order = {
      order_id: `o-${randomHex()}`,
      ts: now,
      vertical,
      mode: body.mode ?? 'propuesta',
      cart_id: body.cart_id ?? null,
      lines: body.lines,
      ...(auto ? { origin: auto.origin, basis: auto.basis } : {}),
    }
    addOrder(order)
    return { body: { order_id: order.order_id, lineas_omitidas: 0 } }
  }
  const profile = /^\/profile\/([^/]+)(\/verticales|\/gustos|\/busquedas|\/preferencias|\/autonomia)?$/.exec(path)
  if (profile) {
    const userId = decodeURIComponent(profile[1])
    if (profile[2] === '/preferencias' && (method === 'GET' || method === 'PUT')) {
      if (method === 'PUT') {
        const list = cleaned(snapshot, body?.preferencias ?? [], state.preferences ?? [])
        updateState((s) => ({ ...s, preferences: list }))
      }
      const saved = readState().preferences ?? []
      const stores = orderedStores(snapshot, readState())
      return { body: { preferencias: describe(snapshot.meta, saved), opciones: options(snapshot.meta, stores) } }
    }
    if (profile[2] === '/autonomia') {
      if (method === 'GET') return { body: autonomyReply(snapshot, state) }
      if (method === 'PUT') return saveAutonomy(snapshot, state, body)
      if (method === 'DELETE') return turnOffAutonomy(snapshot)
    }
    if (method === 'DELETE' && !profile[2])
      return { body: { user_id: userId, concept: null, eventos_borrados: clearState() } }
    if (method === 'GET' && profile[2] === '/verticales')
      return { body: homeVerticals(state, now, snapshot.meta.vertical_labels) }
    if (method === 'GET' && profile[2] === '/gustos') return { body: tastesReply(snapshot, state) }
    if (method === 'GET' && profile[2] === '/busquedas') return { body: searchesReply(state) }
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
