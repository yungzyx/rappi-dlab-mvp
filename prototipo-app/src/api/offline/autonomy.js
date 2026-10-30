// "Pedir por mí" sin conexión, en corto (rappi-ia offers/autonomy.py, api/autonomy.py, rappi_agent.py: _usual_order y
// api/app.py: _auto_order). El permiso vive en el estado de la API simulada (state.js). Lo de siempre es el último
// pedido de este navegador en esa tienda, con los precios de la muestra grabada (no los de hoy). Los límites son los
// mismos: solo en las tiendas elegidas, nunca alcohol, +18, farmacia, bebé ni salud (autoOrderBlocked), nunca sobre el
// tope ni en una tienda que la muestra trae cerrada. La compra mínima no está en la muestra: la de ejemplo la revisa
// la app. "Olvidar" la borra con todo el estado.
import { restaurantHours } from './catalog'
import { OFFER_BLOCKED_VERTICALS } from './motor'
import { autoOrderBlocked } from './offers'
import { isConfirmed, updateState } from './state'
import { normalize } from './text'
import { paused } from './winback'

export const LIMITS = { min: 1000, max: 200_000, suggested: 20_000, stores: 10 } // offers/autonomy.py
const ORIGIN = 'agent-autopedido'
// offers/autonomy.py: ASK_LABEL y ASK_TEXT.
const ASK_LABEL = 'Pide lo de siempre por mí'
const ASK_TEXT = (store) => `Pide lo de siempre en ${store}`
// agent/understand.py: USUAL_ORDER.
const USUAL = new RegExp(
  '\\b(?:lo de siempre|lo mismo de siempre|mi pedido de siempre|el pedido de siempre|lo que pido siempre' +
    '|repite(?:me)? mi (?:ultimo )?pedido|repetir mi (?:ultimo )?pedido)' +
    '(?:\\s+(?:en|de|del|a)\\s+([a-z0-9 ]+?))?\\s*$',
)
// offers/autonomy.py: REASONS.
const REASONS = {
  sin_permiso: () => 'no me diste permiso para pedir por ti',
  tienda_no_elegida: ({ store }) => `no elegiste ${store} para que pida por ti`,
  no_disponible: ({ name, store }) => `${name} ya no está a la venta en ${store}`,
  guardia: () => 'lleva algo que no pido solo (alcohol, +18, farmacia, bebé o salud)',
  cerrada: ({ store }) => `${store} está cerrada ahora, según el horario que publicó`,
  tope: ({ cap }) => `pasa tu tope de ${clp(cap)} por pedido`,
  distinto: () => 'ya no es lo de siempre',
  calificacion: ({ store }) => `calificaste mal un pedido de ${store} hace poco`,
}
const SKIP = new Set(['el', 'la', 'los', 'las', 'de', 'del', 'en'])

const clp = (value) => `$${Math.round(value).toLocaleString('es-CL')}`
const productOf = (snapshot, line) =>
  snapshot.pool.find(
    (p) =>
      p.entity_type === line.entity_type &&
      String(p.entity_id) === String(line.entity_id) &&
      p.store_id === line.store_id,
  )

/** Las tiendas de sus pedidos (modo propuesta), de la más reciente a la más antigua: `[{ id, name, vertical }]`. */
function storesOf(snapshot, state) {
  const seen = new Map()
  for (const order of [...state.orders].reverse()) {
    if (order.mode === 'actual' || !isConfirmed(order)) continue
    for (const line of order.lines) {
      if (line.store_id == null || seen.has(line.store_id)) continue
      const name = productOf(snapshot, line)?.store ?? `Tienda ${line.store_id}`
      seen.set(line.store_id, { id: line.store_id, name, vertical: order.vertical })
    }
  }
  return [...seen.values()]
}

/** Las tiendas de sus pedidos que la hoja "Mis preferencias" ofrece marcar (offers/preferences.py: ordered_stores). */
export const orderedStores = (snapshot, state) => [...new Set(storesOf(snapshot, state).map((s) => s.name))].slice(0, 8)

/** Las que puede elegir: ninguna de Farmacia ni Licores. */
const choosable = (snapshot, state) =>
  storesOf(snapshot, state)
    .filter((store) => !OFFER_BLOCKED_VERTICALS.includes(store.vertical))
    .slice(0, LIMITS.stores)

/**
 * La recompra de una tienda donde la persona deja que Mochi pida solo suma "Pide lo de siempre por mí" (api/agent.py:
 * _with_auto_order): le pide a Mochi lo de siempre ahí, que vuelve a revisar cada límite antes de pedir.
 */
export function withAutoOrder(snapshot, state, offer) {
  const storeId = offer?.products?.[0]?.store_id
  if (!offer || !state.autonomy?.stores.includes(storeId)) return offer
  const store = storesOf(snapshot, state).find((s) => s.id === storeId)
  if (!store) return offer
  return { ...offer, actions: [...(offer.actions ?? []), { label: ASK_LABEL, ask: ASK_TEXT(store.name) }] }
}

/** `GET /profile/{id}/autonomia`. */
export function autonomyReply(snapshot, state) {
  const mine = state.autonomy
  return {
    modo: mine ? 'pedir' : 'revisar',
    tiendas: mine?.stores ?? [],
    tope: mine?.cap ?? null,
    opciones: {
      tiendas: choosable(snapshot, state),
      tope_min: LIMITS.min,
      tope_max: LIMITS.max,
      tope_sugerido: LIMITS.suggested,
    },
  }
}

/** `PUT /profile/{id}/autonomia`: `{ status, body }` (422 si una tienda no se puede elegir o el tope no vale). */
export function saveAutonomy(snapshot, state, body) {
  const stores = [...new Set(body?.tiendas ?? [])]
  const cap = body?.tope
  const allowed = new Set(choosable(snapshot, state).map((store) => store.id))
  if (!stores.length || stores.length > LIMITS.stores || !stores.every((id) => allowed.has(id)))
    return { status: 422, body: { detail: 'Solo puedes elegir tiendas donde ya pediste' } }
  if (!Number.isInteger(cap) || cap < LIMITS.min || cap > LIMITS.max)
    return { status: 422, body: { detail: 'Tope fuera de rango' } }
  const next = updateState((s) => ({ ...s, autonomy: { stores, cap } }))
  return { body: autonomyReply(snapshot, next) }
}

/** `DELETE /profile/{id}/autonomia`: vuelve a "Revisar antes de pedir". */
export function turnOffAutonomy(snapshot) {
  const next = updateState(({ autonomy: _autonomy, ...s }) => s)
  return { body: autonomyReply(snapshot, next) }
}

/** La tienda nombrada de las que ya pidió (todas sus palabras en el nombre); sin nombre, la del último pedido. */
function findStore(snapshot, state, said) {
  const words = normalize(said)
    .split(' ')
    .filter((w) => w && !SKIP.has(w))
  return storesOf(snapshot, state).find((store) => {
    const name = new Set(normalize(store.name).split(' '))
    return words.every((word) => name.has(word))
  })
}

/** Lo de siempre en la tienda: las líneas de su último pedido ahí, con los productos de la muestra. */
function usual(snapshot, state, store) {
  const order = [...state.orders]
    .reverse()
    .find((o) => o.mode !== 'actual' && isConfirmed(o) && o.lines.some((line) => line.store_id === store.id))
  if (!order) return null
  const lines = []
  const missing = []
  for (const line of order.lines.filter((l) => l.store_id === store.id)) {
    const product = productOf(snapshot, line)
    if (product?.price_value == null) missing.push(product?.name ?? 'un producto')
    else lines.push({ product, qty: line.qty ?? 1 })
  }
  return { store, lines, missing, subtotal: lines.reduce((sum, l) => sum + l.product.price_value * l.qty, 0) }
}

function closed(snapshot, store, now) {
  const restaurant = snapshot.catalog.menus?.[store.id]?.restaurant
  if (restaurant?.schedule) return restaurantHours(restaurant.schedule, now).open === false
  return snapshot.catalog.stores?.[store.id]?.store?.hours?.open === false
}

const shape = (lines) =>
  lines
    .map((l) => `${l.entity_type}:${l.entity_id}:${l.qty ?? 1}`)
    .sort()
    .join('|')

/** offers/autonomy.py: decide (el primer límite que falla, o ninguno). */
function decide(snapshot, state, mine, found, now, lines = null) {
  const { store } = found
  const review = (code, values = {}) => ({ code, reason: REASONS[code](values) })
  if (!mine) return review('sin_permiso')
  if (!mine.stores.includes(store.id)) return review('tienda_no_elegida', { store: store.name })
  if (found.missing.length) return review('no_disponible', { name: found.missing[0], store: store.name })
  const usualLines = found.lines.map(({ product, qty }) => ({ ...product, qty }))
  if (lines && shape(lines) !== shape(usualLines)) return review('distinto')
  if (paused(state, now).stores.has(Number(store.id))) return review('calificacion', { store: store.name })
  const concepts = snapshot.meta.concepts
  if (
    OFFER_BLOCKED_VERTICALS.includes(store.vertical) ||
    found.lines.some(({ product }) => autoOrderBlocked(product, concepts))
  )
    return review('guardia')
  if (closed(snapshot, store, now)) return review('cerrada', { store: store.name })
  if (found.subtotal > mine.cap) return review('tope', { cap: mine.cap })
  return null
}

const basis = (mine, store) => [
  { kind: 'permiso', id: 'pedir-por-mi', source: 'persona' },
  { kind: 'tienda', id: String(store.id), source: 'persona' },
  { kind: 'tope', id: String(mine.cap), source: 'persona' },
  { kind: 'regla', id: 'lo-de-siempre', source: 'pedidos' },
]

/**
 * "Pide lo de siempre en…" (rappi_agent.py: _usual_order): la respuesta de `/agent/ask` con `autopedido`, o null si el
 * mensaje no lo pide.
 */
export function usualAnswer(snapshot, state, body, now) {
  const match = USUAL.exec(normalize(String(body?.message ?? '')))
  if (!match) return null
  const said = (match[1] ?? '').trim()
  const reply = (text, extra = {}) => ({
    text,
    products: [],
    stores: [],
    vertical: null,
    prototype_vertical: null,
    intent: { kind: 'autopedido', query: said, concepts: [], vertical: null, confidence: 1, follow_up: false },
    reason: null,
    suggestion: null,
    tags: [],
    unmet: false,
    unmet_reason: null,
    age_notice: false,
    conversation: null,
    actions: [{ label: 'Ver mis pedidos', route: ['orders'] }],
    ...extra,
  })
  if (body?.mode === 'actual') return reply('En "Rappi hoy" no pido por ti: en "Mis pedidos" tienes "Pídelo de nuevo".')
  const store = findStore(snapshot, state, said)
  const found = store && usual(snapshot, state, store)
  if (!found)
    return reply(
      said
        ? `No encuentro un pedido tuyo en "${said}". En "Mis pedidos" están las tiendas donde pediste.`
        : 'Todavía no tienes un pedido que repetir. Cuando pidas algo, te lo repito cuando quieras 🔁.',
    )
  if (!found.lines.length)
    return reply(`Lo de siempre en ${store.name} ya no está a la venta ahí. Mira en "Mis pedidos" otro que repetir.`)
  const mine = state.autonomy ?? null
  const failed = decide(snapshot, state, mine, found, now)
  const units = found.lines.reduce((sum, l) => sum + l.qty, 0)
  const items = `${units} ${units === 1 ? 'producto' : 'productos'}`
  const start = `lo de siempre en ${store.name}: ${items} por ${clp(found.subtotal)}`
  const text = !failed
    ? `Listo, pido ${start}, dentro de tu tope de ${clp(mine.cap)}. Tienes unos segundos para deshacerlo.`
    : failed.code === 'sin_permiso'
      ? `Te armé ${start}. Revísalo antes de pedir.`
      : `Te armé ${start}. Esta vez lo revisas tú: ${failed.reason}.`
  return reply(text, {
    actions: [{ label: 'Cómo pido por ti', panel: 'autonomia' }],
    autopedido: {
      modo: failed ? 'revisar' : 'pedir',
      tienda: store,
      lineas: found.lines.map(({ product, qty }) => ({ product, qty })),
      subtotal: Math.round(found.subtotal),
      tope: mine?.cap ?? null,
      codigo: failed?.code ?? null,
      motivo: failed?.reason ?? null,
      basis: failed ? [] : basis(mine, store),
    },
  })
}

/**
 * `POST /orders` con `autopedido` (api/app.py: _auto_order): lo vuelve a revisar contra lo de siempre de ahora. Devuelve
 * `{ status: 409, body }` si no pasa, o lo que se suma al pedido guardado (`origin` y `basis`).
 */
export function checkAutoOrder(snapshot, state, body, now) {
  const ids = new Set(body.lines.map((line) => line.store_id))
  const known = ids.size === 1 && storesOf(snapshot, state).find((store) => ids.has(store.id))
  const found = body.mode !== 'actual' && known ? usual(snapshot, state, known) : null
  const failed = found
    ? decide(snapshot, state, state.autonomy ?? null, found, now, body.lines)
    : { code: 'distinto', reason: REASONS.distinto() }
  if (failed) return { status: 409, body: { detail: { codigo: failed.code, motivo: failed.reason } } }
  return { origin: ORIGIN, basis: basis(state.autonomy, known) }
}
