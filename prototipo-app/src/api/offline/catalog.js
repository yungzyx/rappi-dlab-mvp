// `/catalog/*` sin conexión (api/catalog.py): las listas y páginas grabadas en la muestra. Lo que la muestra no tiene
// responde 404, como un producto o una tienda que no está en el catálogo.
import { entityKey } from './snapshot'
import { backendVertical } from './search'

const NOT_FOUND = { status: 404, body: { detail: 'No está en la muestra de la demo sin conexión' } }
const minutes = (eta) => Number.parseInt(eta, 10) || Number.POSITIVE_INFINITY
const pesos = (fee) => Number(String(fee ?? '').replace(/\D/g, '')) || 0
const SORTS = {
  eta: (a, b) => minutes(a.eta) - minutes(b.eta),
  fee: (a, b) => pesos(a.fee) - pesos(b.fee),
  recommended: (a, b) => (b.reviews ?? -1) - (a.reviews ?? -1),
}
const limitOf = (query, fallback) => Number(query.get('limit')) || fallback
// catalog/restaurants.py: TOP_MIN_RATING y TOP_MIN_REVIEWS («Destacados», regla propia de la demo).
const TOP_MIN_RATING = 4.5
const TOP_MIN_REVIEWS = 100
const DAYS = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'] // en el orden de Date.getDay
const SANTIAGO = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/Santiago',
  weekday: 'short',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})

/** El día ('thu') y la hora ('13:05') de Santiago en `now` (ms). */
function santiago(now) {
  const parts = Object.fromEntries(SANTIAGO.formatToParts(new Date(now)).map((part) => [part.type, part.value]))
  return { day: parts.weekday.toLowerCase().slice(0, 3), time: `${parts.hour}:${parts.minute}` }
}

/** Los tramos de `day` del horario publicado, o los del único día publicado (catalog/hours.py: _spans_of). */
function spansOf(schedule, day) {
  const days = new Set(schedule.map((span) => span.day))
  const chosen = days.has(day) ? day : days.size === 1 ? [...days][0] : null
  return schedule.filter((span) => span.day === chosen)
}

/** catalog/hours.py: restaurant_hours, con la hora de Santiago del navegador. */
export function restaurantHours(schedule, now) {
  const base = { source: 'horario', open: null, closes_at: null, opens_at: null, opens_tomorrow: false, today: null }
  if (!schedule?.length) return base
  const { day, time } = santiago(now)
  const index = DAYS.indexOf(day)
  const spans = spansOf(schedule, day)
  const inside = (s) => (s.open < s.close ? s.open <= time && time < s.close : time >= s.open)
  const late = spansOf(schedule, DAYS[(index + 6) % 7]).find((s) => s.close < s.open && time < s.close)
  const current = spans.find(inside) ?? late
  const later = spans
    .map((s) => s.open)
    .filter((open) => open > time)
    .sort()
  const nextDay = spansOf(schedule, DAYS[(index + 1) % 7])
  const tomorrow = !current && !later.length && nextDay.length
  return {
    ...base,
    open: Boolean(current),
    closes_at: current?.close ?? null,
    opens_at: current ? null : (later[0] ?? (tomorrow ? nextDay.map((s) => s.open).sort()[0] : null)),
    opens_tomorrow: Boolean(tomorrow),
    today: spans.map((s) => `${s.open}–${s.close}`).join(', ') || null,
  }
}

/** Las tarjetas con su estado a la hora `now` y los cerrados al final (catalog/restaurants.py: with_hours). */
export function withHours(cards, now) {
  const timed = cards.map((card) =>
    'schedule' in card ? { ...card, hours: restaurantHours(card.schedule, now) } : card,
  )
  return [...timed.filter((card) => card.hours?.open !== false), ...timed.filter((card) => card.hours?.open === false)]
}

/** Los filtros de la lista de restaurantes (api/catalog.py: restaurant_list). */
function filtered(list, query) {
  const maxEta = Number(query.get('max_eta')) || null
  const minRating = Number(query.get('min_rating')) || null
  const top = query.get('top') === 'true'
  const promo = query.get('promo') === 'true'
  return list.filter(
    (r) =>
      (!maxEta || minutes(r.eta) <= maxEta) &&
      (!minRating || (r.rating ?? 0) >= minRating) &&
      (!top || ((r.rating ?? 0) >= TOP_MIN_RATING && (r.reviews ?? 0) >= TOP_MIN_REVIEWS)) &&
      (!promo || r.promo),
  )
}

/** `{ status, body }` de una ruta del catálogo, o undefined si la ruta no es del catálogo. */
export function catalogRoute(snapshot, method, path, query, now = Date.now()) {
  const catalog = snapshot.catalog
  if (method !== 'GET') return undefined
  if (path === '/catalog/home')
    return {
      body: {
        ...catalog.home,
        fast_restaurants: withHours(catalog.home.fast_restaurants ?? [], now),
        low_fee_restaurants: withHours(catalog.home.low_fee_restaurants ?? [], now),
      },
    }
  if (path === '/catalog/restaurants') {
    const sort = query.get('sort') || 'rating'
    const cuisine = query.get('cuisine')
    const key = cuisine ? `rating|${cuisine}` : sort
    let list = catalog.restaurants[key]
    if (!list && cuisine)
      list = catalog.restaurants.rating.filter((r) =>
        r.cuisines?.some((c) => c.toLowerCase() === cuisine.toLowerCase()),
      )
    if (!list) list = [...catalog.restaurants.rating].sort(SORTS[sort] ?? (() => 0))
    return { body: withHours(filtered(list, query), now).slice(0, limitOf(query, 30)) }
  }
  if (path === '/catalog/deals') {
    const vertical = query.get('vertical')
    const code = backendVertical(vertical)
    if (vertical && !code) return NOT_FOUND
    return { body: (catalog.deals[code ?? ''] ?? []).slice(0, limitOf(query, 24)) }
  }
  if (path === '/catalog/terms') return { body: { stores: storeTerms(catalog, query.get('stores')) } }
  let match = /^\/catalog\/verticals\/([^/]+)\/stores$/.exec(path)
  if (match) {
    const reply = catalog.verticalStores[backendVertical(decodeURIComponent(match[1]))]
    if (!reply) return NOT_FOUND
    return { body: { ...reply, stores: reply.stores.slice(0, limitOf(query, 30)) } }
  }
  match = /^\/catalog\/stores\/(\d+)$/.exec(path)
  if (match) {
    const shop = catalog.stores[match[1]]
    if (!shop) return NOT_FOUND
    const page = Number(query.get('page')) || 1
    const chosen = shop.pages[query.get('aisle')] ?? shop.pages[shop.aisles[0]?.id]
    // Solo la primera página de cada pasillo está en la muestra: «Ver más» no aparece.
    return {
      body: {
        store: shop.store,
        aisles: shop.aisles,
        aisle: chosen?.aisle ?? null,
        products: page === 1 ? (chosen?.products ?? []) : [],
        page,
        has_more: false,
      },
    }
  }
  match = /^\/catalog\/restaurants\/(\d+)\/menu$/.exec(path)
  if (match) {
    const found = catalog.menus[match[1]]
    return found ? { body: { ...found, restaurant: withHours([found.restaurant], now)[0] } } : NOT_FOUND
  }
  match = /^\/catalog\/products\/([^/]+)\/([^/]+)$/.exec(path)
  if (match) {
    const product = snapshot.byEntity.get(entityKey(decodeURIComponent(match[1]), decodeURIComponent(match[2])))
    return product ? { body: product } : NOT_FOUND
  }
  return undefined
}

/**
 * `/catalog/terms` sin conexión (catalog/terms.py), en corto: la muestra guarda las tarjetas, no el `raw` de las
 * tiendas, así que solo sabe el envío de los restaurantes grabados (`fee` de su tarjeta); lo demás va en null y la app
 * pone su supuesto rotulado, como con la API real cuando el catálogo no lo trae.
 */
function storeTerms(catalog, ids) {
  return String(ids ?? '')
    .split(',')
    .map(Number)
    .filter((id) => Number.isInteger(id) && (catalog.menus[id] || catalog.stores[id]))
    .map((id) => ({
      store_id: id,
      delivery_fee: pesos(catalog.menus[id]?.restaurant?.fee) || null,
      min_order: null,
      service_pct: null,
    }))
}
