// Lo que la API simulada recuerda de la persona: sus eventos, pedidos y preferencias, en localStorage de este navegador. La clave
// lleva el prefijo `rappi-proto-`, así "Borrar mis datos" la borra junto con lo demás del prototipo.

const KEY = 'rappi-proto-offline-api'
const MAX_EVENTS = 500

const empty = () => ({ userId: null, events: [], orders: [], preferences: [] })
let memory = empty() // sin localStorage (modo privado), vive mientras la pestaña siga abierta

export function readState() {
  try {
    const stored = JSON.parse(localStorage.getItem(KEY))
    if (!stored || !Array.isArray(stored.events) || !Array.isArray(stored.orders)) return empty()
    // Lo guardado antes de las preferencias (migración 045) no las trae.
    return Array.isArray(stored.preferences) ? stored : { ...stored, preferences: [] }
  } catch {
    return memory
  }
}

/** Se avisa cada vez que cambia lo guardado (un pedido, un lote de eventos, "Olvidar"): lo escucha el panel de la demo. */
export const OFFLINE_STATE_EVENT = 'rappi-demo-state'

export function writeState(state) {
  memory = state
  if (typeof window !== 'undefined') queueMicrotask(() => window.dispatchEvent(new Event(OFFLINE_STATE_EVENT)))
  try {
    localStorage.setItem(KEY, JSON.stringify(state))
  } catch {
    // Sin almacenamiento: queda en memoria.
  }
}

/** Aplica `change` al estado guardado y lo guarda. */
export function updateState(change) {
  const next = change(readState())
  writeState(next)
  return next
}

export function addEvents(events) {
  return updateState((state) => ({ ...state, events: [...state.events, ...events].slice(-MAX_EVENTS) }))
}

/** ¿Cuenta como compra? Un pedido cancelado (`order_cancelled`, migración 050) no: ni recompra, ni motor, ni perfiles. */
export const isConfirmed = (order) => order.status !== 'cancelado'

/**
 * Los pedidos que cancela un `order_cancelled` (events/store.py: _record_cancellations, en los dos modos): los de su
 * carro y su tienda (`payload.store_id`) o, sin tienda, su vertical.
 */
export function cancelOrders(events) {
  const cancels = events.filter((e) => e.type === 'order_cancelled' && e.cart_id)
  if (!cancels.length) return readState()
  const hits = (order, e) =>
    order.cart_id === e.cart_id &&
    (e.payload?.store_id != null
      ? order.lines.some((line) => Number(line.store_id) === Number(e.payload.store_id))
      : !e.vertical || order.vertical === e.vertical)
  return updateState((state) => ({
    ...state,
    orders: state.orders.map((order) =>
      isConfirmed(order) && cancels.some((e) => hits(order, e)) ? { ...order, status: 'cancelado' } : order,
    ),
  }))
}

export function addOrder(order) {
  return updateState((state) => ({ ...state, orders: [...state.orders, order] }))
}

/** "Olvidar": lo que la API simulada sabe de la persona. */
export function clearState() {
  const before = readState()
  writeState(empty())
  return before.events.length + before.orders.length
}
