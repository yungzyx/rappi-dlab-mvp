// La recompra con ritmo y «¿Volvemos a…?» sin conexión: la tabla `replenishment` del motor (motor/model.py), armada
// aquí con los pedidos de este navegador, y a quién le toca una invitación a volver (offers/winback.py: lapses y
// available). El panel de la demo siembra personas con semanas de historial para verla. Los productos y el texto de
// las ofertas están en offers.js.
import { OFFER_BLOCKED_VERTICALS } from './motor'

const DAY_MS = 86_400_000
// motor/model.py
export const REPLENISH_MIN_ORDERS = 3
const REPLENISH_MAX_CV = 0.6
// offers/winback.py
const REPEAT_AHEAD_DAYS = 2
export const LAPSE_MIN_DAYS = 14
const LAPSE_MAX_DAYS = 90
const VERTICAL_LAPSE_DAYS = 30
const VERTICAL_MIN_DAYS = 3
const COOLDOWN_DAYS = 7
const MAX_DISMISSALS = 2
const ORIGIN = 'agent-volver'
export const BASIS_KINDS = { concepto: 'volver', vertical: 'vuelta' }

const SANTIAGO = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'America/Santiago',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})

/** El día de Santiago de una hora (ms), en días desde 1970: restados, son días de calendario. */
export const localDay = (ts) => Date.parse(`${SANTIAGO.format(ts)}T00:00:00Z`) / DAY_MS

/** `round` de Python: la mitad va al par (17,5 → 18, 14,5 → 14). */
export const roundHalfEven = (x) => {
  const r = Math.round(x)
  return Math.abs(x % 1) === 0.5 && r % 2 ? r - 1 : r
}

const median = (values) => {
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}

/** Los días de Santiago distintos de unos pedidos, en orden. */
export const orderDays = (orders) => [...new Set(orders.map((o) => localDay(o.ts)))].sort((a, b) => a - b)

const proposals = (state) => state.orders.filter((o) => o.mode === 'propuesta').sort((a, b) => a.ts - b.ts)

/**
 * Por concepto, con al menos 3 días de compra distintos en pedidos `propuesta` y un ritmo regular (coeficiente de
 * variación ≤ 0,6): `{ concept, vertical, orders, interval, lastTs, dueOn }` (motor/model.py: replenishment, de una
 * persona). `interval` es la mediana de días entre compras, `dueOn` el día en que le toca y la vertical, donde más lo
 * pide (empate: la más reciente).
 */
export function replenishment(state) {
  const bought = new Map()
  for (const order of proposals(state))
    for (const concept of new Set(order.lines.map((l) => l.concept_id).filter(Boolean)))
      bought.set(concept, [...(bought.get(concept) ?? []), order])
  const rows = []
  for (const [concept, orders] of bought) {
    const days = orderDays(orders)
    if (days.length < REPLENISH_MIN_ORDERS) continue
    const intervals = days.slice(1).map((day, i) => day - days[i])
    const mean = intervals.reduce((a, b) => a + b, 0) / intervals.length
    const spread = Math.sqrt(intervals.reduce((a, b) => a + (b - mean) ** 2, 0) / intervals.length)
    if (new Set(intervals).size > 1 && spread / mean > REPLENISH_MAX_CV) continue
    const count = {}
    const lastSeen = {}
    orders.forEach((o, i) => {
      count[o.vertical] = (count[o.vertical] ?? 0) + 1
      lastSeen[o.vertical] = i
    })
    const vertical = Object.keys(count).sort((a, b) => count[b] - count[a] || lastSeen[b] - lastSeen[a])[0]
    const interval = median(intervals)
    rows.push({
      concept,
      vertical,
      orders: days.length,
      interval,
      lastTs: orders.at(-1).ts,
      dueOn: days.at(-1) + roundHalfEven(interval),
    })
  }
  return rows
}

/** Si a una fila de `replenishment` le toca la recompra: desde 2 días antes del día en que le toca hasta un intervalo
 * después (winback.py: repeat_due). */
export const repeatDue = (row, today) =>
  today - roundHalfEven(row.interval) <= row.dueOn && row.dueOn <= today + REPEAT_AHEAD_DAYS

/** Una vertical que el agente ofrece por su cuenta y tiene pantalla en la app. */
export const offerableVertical = (vertical, screens) =>
  !OFFER_BLOCKED_VERTICALS.includes(vertical) && !!screens[vertical]

/** Las invitaciones a volver de la persona, en su orden (winback.py: lapses y _rank), sin mirar lo ya mostrado. */
export function lapses(snapshot, state, now) {
  const { concepts, screen_verticals: screens } = snapshot.meta
  const today = localDay(now)
  const found = []
  // Un concepto atrasado más de un intervalo (lo que la recompra ya no ofrece), pedido hace 14 a 90 días.
  for (const row of replenishment(state)) {
    const days = today - localDay(row.lastTs)
    const late = row.dueOn < today - roundHalfEven(row.interval)
    if (!late || days < LAPSE_MIN_DAYS || days > LAPSE_MAX_DAYS) continue
    if (!concepts[row.concept]?.offerable || !offerableVertical(row.vertical, screens)) continue
    const { concept: key, vertical, orders, lastTs } = row
    found.push({ kind: 'concepto', key, vertical, days, orders, interval: roundHalfEven(row.interval), lastTs })
  }
  // Una vertical con pedidos en 3 días o más, sin pedidos hace más de 30 (y no más de 90), mientras pide en otra.
  const byVertical = new Map()
  for (const order of proposals(state).filter((o) => localDay(o.ts) <= today))
    byVertical.set(order.vertical, [...(byVertical.get(order.vertical) ?? []), order])
  const verticals = [...byVertical].map(([vertical, orders]) => ({
    vertical,
    orders: orderDays(orders).length,
    lastTs: orders.at(-1).ts,
    days: today - localDay(orders.at(-1).ts),
  }))
  const active = verticals.filter((v) => v.days <= VERTICAL_LAPSE_DAYS).map((v) => v.vertical)
  for (const v of verticals)
    if (
      v.days > VERTICAL_LAPSE_DAYS &&
      v.days <= LAPSE_MAX_DAYS &&
      v.orders >= VERTICAL_MIN_DAYS &&
      active.some((other) => other !== v.vertical) &&
      offerableVertical(v.vertical, screens)
    )
      found.push({ kind: 'vertical', key: v.vertical, ...v })
  // Primero los conceptos (más días de compra, el menos atrasado respecto de su ritmo); después las verticales (más
  // días con pedido, la más reciente). El id desempata.
  const rank = (l) =>
    l.kind === 'concepto' ? [0, -l.orders, l.days / Math.max(l.interval, 1), l.key] : [1, -l.orders, l.days, l.key]
  const compare = (a, b) => {
    for (const [x, y] of rank(a).map((value, i) => [value, rank(b)[i]])) if (x !== y) return x < y ? -1 : 1
    return 0
  }
  return found.sort(compare)
}

/** Si un evento de la app es de esta invitación (winback.py: _same): la de un concepto lleva su concepto; la de una
 * vertical, `payload.kind` «vuelta» y su vertical. */
const same = (lapse, event) =>
  lapse.kind === 'concepto'
    ? event.payload?.kind !== BASIS_KINDS.vertical && event.concept_id === lapse.key
    : event.payload?.kind === BASIS_KINDS.vertical && event.vertical === lapse.key

/**
 * Las invitaciones que se pueden mostrar ahora (winback.py: available): sin las descartadas dos veces después de su
 * último pedido, y con pausa por persona: si en los últimos 7 días se le mostró una, solo esa (si sigue calificando).
 * Cuentan los eventos con origen `agent-volver`, salvo los de «Rappi hoy». Lo que volvió a pedir ya no está en
 * `candidates`: aquí la recompra se calcula con los mismos pedidos.
 */
export function available(state, candidates, now) {
  const events = state.events
    .filter(
      (e) =>
        (e.type === 'suggestion_shown' || e.type === 'suggestion_dismissed') &&
        e.payload?.origen === ORIGIN &&
        e.payload?.mode !== 'actual',
    )
    .sort((a, b) => b.ts - a.ts)
  const open = candidates.filter(
    (lapse) =>
      events.filter((e) => e.type === 'suggestion_dismissed' && e.ts > lapse.lastTs && same(lapse, e)).length <
      MAX_DISMISSALS,
  )
  const recent = events.find((e) => e.type === 'suggestion_shown' && e.ts > now - COOLDOWN_DAYS * DAY_MS)
  return recent ? open.filter((lapse) => same(lapse, recent)).slice(0, 1) : open
}
