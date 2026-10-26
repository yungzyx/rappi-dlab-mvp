// Línea de tiempo simulada del pedido (segundos desde que se hizo) y ruta del repartidor en el mapa. Los pasos son los
// de la app de Rappi para cada vertical (docs/investigacion/app-rappi-2026-10-25.md): un restaurante prepara y después
// se busca un Rappi; en el súper, la farmacia y las demás tiendas un shopper elige los productos; Turbo arma el pedido
// y llega en minutos. En todos el viaje parte a los 9 s y la entrega es a los 20 s: la demo dura lo mismo.
const CONFIRMED = { id: 'confirmed', label: 'Pedido confirmado', short: 'Confirmado', at: 0 }
const ON_THE_WAY = { id: 'on-the-way', label: 'En camino', short: 'En camino', at: 9 }
const ARRIVED = { id: 'arrived', label: 'Tu Rappi llegó a tu dirección', short: 'En destino', at: 18 }
const DELIVERED = { id: 'delivered', label: 'Entregado', short: 'Entregado', at: 20 }

export const FLOWS = {
  restaurants: {
    id: 'restaurants',
    rideMinutes: 12,
    waitMinutes: 10, // antes del viaje: lo que falta de preparación
    steps: [
      CONFIRMED,
      { id: 'preparing', label: 'El restaurante prepara tu pedido', short: 'Preparando', at: 3 },
      { id: 'searching', label: 'Buscando un Rappi', short: 'Buscando un Rappi', at: 6 },
      ON_THE_WAY,
      ARRIVED,
      DELIVERED,
    ],
  },
  shopper: {
    id: 'shopper',
    rideMinutes: 15,
    waitMinutes: 15,
    steps: [
      CONFIRMED,
      { id: 'in-store', label: 'En tienda: tu shopper elige tus productos', short: 'En tienda', at: 3 },
      ON_THE_WAY,
      ARRIVED,
      DELIVERED,
    ],
  },
  turbo: {
    id: 'turbo',
    // La promesa de Turbo en la app de Rappi: «10 minutos». Aquí es lo que se muestra, no una garantía.
    promise: 'Turbo: tu pedido llega en minutos',
    rideMinutes: 8,
    waitMinutes: 2,
    steps: [
      CONFIRMED,
      { id: 'packing', label: 'Armando tu pedido', short: 'Armando', at: 3 },
      ON_THE_WAY,
      ARRIVED,
      DELIVERED,
    ],
  },
}

// Las verticales de tienda con shopper (Market en la app de Rappi): todas las que no son restaurantes ni Turbo.
const flowId = (vertical) => (vertical === 'restaurants' || vertical === 'turbo' ? vertical : 'shopper')

/**
 * Los pasos de un pedido según lo que lleva: con un plato es de restaurante; si todo es de Turbo, de Turbo; si no, de
 * una tienda con shopper. Un pedido guardado sin verticales (de antes) sigue los pasos de un restaurante.
 */
export function flowFor(order) {
  const verticals = new Set((order?.items ?? []).map((item) => item.vertical).filter(Boolean))
  if (verticals.size === 0 || verticals.has('restaurants')) return FLOWS.restaurants
  if ([...verticals].every((vertical) => vertical === 'turbo')) return FLOWS.turbo
  return FLOWS[flowId([...verticals].find((vertical) => vertical !== 'turbo'))]
}

const RIDE_START = ON_THE_WAY.at
const RIDE_END = ARRIVED.at

// Ruta por calles (coordenadas del SVG del mapa, 400 × 300).
export const ROUTE = [
  [62, 236],
  [62, 168],
  [178, 168],
  [178, 100],
  [322, 100],
  [322, 66],
]

/** Paso actual (índice en los pasos del flujo) según los segundos transcurridos. */
export function stepAt(seconds, flow = FLOWS.restaurants) {
  return flow.steps.reduce((current, step, i) => (seconds >= step.at ? i : current), 0)
}

/** ¿Ya se entregó? */
export const isDelivered = (seconds) => seconds >= DELIVERED.at

/** ¿Va en camino o ya llegó a la dirección (cuando se usa el código de entrega)? */
export const isRiding = (seconds) => seconds >= RIDE_START && !isDelivered(seconds)

/** Avance del viaje entre 0 y 1. */
export function rideProgress(seconds) {
  return Math.min(1, Math.max(0, (seconds - RIDE_START) / (RIDE_END - RIDE_START)))
}

/** Minutos que faltan (escala simulada: el viaje de 9 s "dura" los minutos de viaje del flujo). */
export function minutesLeft(seconds, flow = FLOWS.restaurants) {
  if (seconds >= RIDE_END) return 0
  if (seconds < RIDE_START) return flow.rideMinutes + flow.waitMinutes
  return Math.max(1, Math.ceil((1 - rideProgress(seconds)) * flow.rideMinutes))
}

/** Punto de la ruta para un avance entre 0 y 1, interpolando por largo de cada tramo. */
export function pointOnRoute(progress, route = ROUTE) {
  const segments = route.slice(1).map((point, i) => {
    const [x0, y0] = route[i]
    return { from: route[i], to: point, length: Math.hypot(point[0] - x0, point[1] - y0) }
  })
  const total = segments.reduce((sum, segment) => sum + segment.length, 0)
  let remaining = Math.min(1, Math.max(0, progress)) * total
  for (const { from, to, length } of segments) {
    if (remaining <= length) {
      const t = length === 0 ? 0 : remaining / length
      return [from[0] + (to[0] - from[0]) * t, from[1] + (to[1] - from[1]) * t]
    }
    remaining -= length
  }
  return route[route.length - 1]
}

/** Cuándo empieza su línea de tiempo: la franja si se programó; si no, cuando se hizo. */
export const startOf = (order) => order?.scheduledFor ?? order?.placedAt ?? 0

/** ¿Es un pedido programado que todavía no empieza? */
export const isAhead = (order, now) => Boolean(order?.scheduledFor) && now < order.scheduledFor

/**
 * Segundos del pedido en su línea de tiempo (negativos si está programado y no empieza). El reloj de la demo se
 * detiene mientras la persona decide algo que el pedido espera (`heldAt`: cancelar o un producto agotado; lo esperado
 * suma en `pausedMs`), y un atraso (`delay`, desde el «Panel de la demo») deja el pedido en su paso `delay.seconds`
 * segundos a partir de `delay.from`.
 */
export function secondsSince(order, now) {
  if (!order) return 0
  const raw = ((order.heldAt ?? now) - startOf(order) - (order.pausedMs ?? 0)) / 1000
  const delay = order.delay
  if (!delay || raw <= delay.from) return raw
  return Math.max(delay.from, raw - delay.seconds)
}

/** Cuándo se entregó (o se entregará) el pedido, con lo que esperó y su atraso (ms). */
export const deliveredAt = (order) =>
  startOf(order) + (order?.pausedMs ?? 0) + ((order?.delay?.seconds ?? 0) + DELIVERED.at) * 1000

/**
 * Los minutos que muestra el seguimiento: los del flujo más lo que suma el tipo de entrega (`etaShift`: «Sin prisa»
 * más, «Prioritaria» menos) y un atraso (`delay.minutes`), que se van gastando con el viaje.
 */
export function etaMinutes(order, seconds, flow = flowFor(order)) {
  const base = minutesLeft(seconds, flow)
  if (base === 0) return 0
  const left = 1 - rideProgress(seconds)
  const extra = ((order?.etaShift ?? 0) + (order?.delay?.minutes ?? 0)) * left
  return Math.max(1, Math.round(base + extra))
}

/**
 * El estado de un pedido para las listas y la barra «Pedido en curso»: `{ kind, label, short, done }`. `kind` es
 * `cancelled`, `scheduled` (programado y sin empezar), `active` o `delivered`.
 */
export function statusOf(order, now) {
  if (order?.cancelled) return { kind: 'cancelled', label: 'Pedido cancelado', short: 'Cancelado', done: true }
  if (isAhead(order, now))
    return {
      kind: 'scheduled',
      label: `Programado para ${slotLabel(order.scheduledFor, now)}`,
      short: `Programado · ${slotLabel(order.scheduledFor, now)}`,
      done: false,
    }
  const seconds = secondsSince(order, now)
  if (isDelivered(seconds)) return { kind: 'delivered', label: DELIVERED.label, short: DELIVERED.short, done: true }
  const flow = flowFor(order)
  const step = flow.steps[stepAt(seconds, flow)]
  return {
    kind: 'active',
    label: step.label,
    short: order?.delay ? `${step.short} · atrasado` : step.short,
    done: false,
  }
}

const SLOT_MS = 3_600_000
const hourOf = (ts) =>
  new Date(ts).toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
const dayStart = (ts) => new Date(ts).setHours(0, 0, 0, 0)

/** «hoy 15:00–16:00» o «mañana 10:00–11:00»: la franja de una hora que empieza en `from`. */
export function slotLabel(from, now = Date.now()) {
  const day = dayStart(from) === dayStart(now) ? 'hoy' : 'mañana'
  return `${day} ${hourOf(from)}–${hourOf(from + SLOT_MS)}`
}

/**
 * Código de entrega de 4 dígitos (el «handshake» de la app de Rappi): sale del id del pedido, así es siempre el mismo
 * para ese pedido. Es de la demo: no lo valida nadie.
 */
export function deliveryCode(orderId) {
  let hash = 0x811c9dc5
  for (const char of String(orderId)) hash = Math.imul(hash ^ char.codePointAt(0), 0x01000193) >>> 0
  return String(hash % 10_000).padStart(4, '0')
}
