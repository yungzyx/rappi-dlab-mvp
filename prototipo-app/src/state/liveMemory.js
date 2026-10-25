// Memoria del agente en la Home del prototipo final mientras dura la sesión: lo que ya mostró y lo último que la persona
// agregó al carro (el agente lo comenta al volver).
import { resetQuiet } from './agentQuiet'

// `repeatLater`: tocaron «Después» en «¿Repetimos?» o en «¿Volvemos a…?»; no vuelven en lo que dura la pestaña.
// `winback`: la respuesta de «¿Volvemos a…?» (`{ generation, offer }`, offer null si no hubo), pedida una vez.
export const session = {
  played: false,
  lastAdded: null,
  plan: null,
  planPrompted: false,
  repeatLater: false,
  winback: null,
}

/** Lo último agregado al carro en el prototipo final (fuera de la Home): el agente lo comenta al volver. */
export function rememberAdded(product) {
  session.lastAdded = product
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

/** Evento de ventana con que el botón «Repetir escena» (fuera del teléfono) avisa a la Home. */
export const REPLAY_EVENT = 'agent-vivo-repetir'

/** «Repetir la escena»: vuelve al estado de una persona que abre la Home por primera vez (el silencio también se reinicia). */
export function resetLive() {
  Object.assign(session, {
    played: false,
    lastAdded: null,
    plan: null,
    planPrompted: false,
    repeatLater: false,
    winback: null,
  })
  resetQuiet()
  try {
    localStorage.removeItem(TOUR_KEY)
  } catch {
    // Nada guardado que borrar.
  }
  window.dispatchEvent(new Event(REPLAY_EVENT))
}
