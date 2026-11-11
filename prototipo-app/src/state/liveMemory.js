// Memoria del agente en la Home del prototipo final mientras dura la sesión: lo que ya mostró y lo último que la persona
// agregó al carro (el agente lo comenta al volver).
import { isAgentHidden as isAgentHiddenNow, setAgentHidden } from './agentHidden'
import { resetQuiet } from './agentQuiet'
import { clearRefused } from './EventsContext'

// `repeatLater`: tocaron "Después" en "¿Repetimos?" o en "¿Volvemos a…?"; no vuelven en lo que dura la pestaña.
// `winback`: la respuesta de "¿Volvemos a…?" (`{ generation, offer }`, offer null si no hubo), pedida una vez.
// `pendingMove`: el cambio de orden de los accesos que Mochi aún no explica (sobrevive a cambiar de pestaña: el orden
// nuevo ya quedó como visto).
// `lastAdded` y `pendingMove` también sobreviven a recargar la página (en el celular, tirar la pantalla hacia abajo
// recarga): se guardan en la pestaña (sessionStorage). "Olvidar" los borra con todo lo `rappi-proto-*` y "Repetir
// escena" (resetLive) también.
const PENDING_KEY = 'rappi-proto-mochi-pendiente'

function readPending() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(PENDING_KEY))
    return { lastAdded: saved?.lastAdded ?? null, pendingMove: saved?.pendingMove ?? null }
  } catch {
    return { lastAdded: null, pendingMove: null }
  }
}

function savePending() {
  try {
    const { lastAdded, pendingMove } = session
    if (lastAdded || pendingMove) sessionStorage.setItem(PENDING_KEY, JSON.stringify({ lastAdded, pendingMove }))
    else sessionStorage.removeItem(PENDING_KEY)
  } catch {
    // Sin almacenamiento: lo pendiente dura lo que la página.
  }
}

export const session = {
  played: false,
  ...readPending(),
  plan: null,
  planPrompted: false,
  repeatLater: false,
  winback: null,
}

/** Lo último agregado al carro en el prototipo final (fuera de la Home): el agente lo comenta al volver. */
export function rememberAdded(product) {
  session.lastAdded = product
  savePending()
}

/** Lo agregado ya se comentó (o no hay qué decir): se olvida. */
export function forgetAdded() {
  session.lastAdded = null
  savePending()
}

/** El cambio de orden de los accesos que Mochi tiene que explicar (`null`: ya lo explicó o no corresponde). */
export function rememberMove(move) {
  session.pendingMove = move
  savePending()
}

/** La guía de la primera vez (2 pasos tras el saludo) ya se vio o se saltó: se recuerda en el navegador. */
export const TOUR_KEY = 'rappi-proto-guia-vista'

export function tourSeen() {
  try {
    return localStorage.getItem(TOUR_KEY) !== null
  } catch {
    return true // sin almacenamiento, mejor no repetirla en cada visita
  }
}

export function markTourSeen() {
  try {
    localStorage.setItem(TOUR_KEY, '1')
  } catch {
    // Sin almacenamiento: vale lo que dura la pestaña (la guía ya terminó).
  }
}

/** Evento de ventana con que se avisa al agente flotante que algo se agregó al carro (detalle: `{ product }`). */
export const AGENT_CART_EVENT = 'agent-carrito'

/** Evento de ventana con que el botón "Repetir escena" (fuera del teléfono) avisa a la Home. */
export const REPLAY_EVENT = 'agent-vivo-repetir'

/**
 * "Repetir la escena": vuelve al estado de una persona que abre la Home por primera vez (el silencio también se reinicia,
 * y si estaba oculto, Mochi vuelve). Devuelve `true` si Mochi estaba oculto: quien la llama anota que volvió
 * (`agent_visibility`), para que el panel no lo siga contando como oculto.
 */
export function resetLive() {
  Object.assign(session, {
    played: false,
    lastAdded: null,
    pendingMove: null,
    plan: null,
    planPrompted: false,
    repeatLater: false,
    winback: null,
  })
  savePending()
  clearRefused()
  resetQuiet()
  const wasHidden = isAgentHiddenNow()
  if (wasHidden) setAgentHidden(false)
  try {
    localStorage.removeItem(TOUR_KEY)
  } catch {
    // Nada guardado que borrar.
  }
  window.dispatchEvent(new Event(REPLAY_EVENT))
  return wasHidden
}
