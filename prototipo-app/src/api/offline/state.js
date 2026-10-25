// Lo que la API simulada recuerda de la persona: sus eventos y pedidos, en localStorage de este navegador. La clave
// lleva el prefijo `rappi-proto-`, así «Borrar mis datos» la borra junto con lo demás del prototipo.

const KEY = 'rappi-proto-offline-api'
const MAX_EVENTS = 500

const empty = () => ({ userId: null, events: [], orders: [] })
let memory = empty() // sin localStorage (modo privado), vive mientras la pestaña siga abierta

export function readState() {
  try {
    const stored = JSON.parse(localStorage.getItem(KEY))
    return stored && Array.isArray(stored.events) && Array.isArray(stored.orders) ? stored : empty()
  } catch {
    return memory
  }
}

/** Se avisa cada vez que cambia lo guardado (un pedido, un lote de eventos, «Olvidar»): lo escucha el panel de la demo. */
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

export function addOrder(order) {
  return updateState((state) => ({ ...state, orders: [...state.orders, order] }))
}

/** «Olvidar»: lo que la API simulada sabe de la persona. */
export function clearState() {
  const before = readState()
  writeState(empty())
  return before.events.length + before.orders.length
}
