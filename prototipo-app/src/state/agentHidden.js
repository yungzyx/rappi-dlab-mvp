import { useSyncExternalStore } from 'react'

// "Ocultar a Mochi" (prototipo final): a diferencia de "Silenciar por hoy" (agentQuiet.js), dura hasta que la persona lo
// trae de vuelta en Cuenta ("Mostrar a Mochi"). Oculto, no hay mascota en ninguna parte ni nada que Mochi proponga por
// su cuenta, y el buscador es el de siempre (el de "Rappi hoy"). Se guarda en este navegador: sobrevive a recargar;
// cambiar de persona en la demo, "Repetir escena" y "Borrar mis datos" (que borra todo lo `rappi-proto-*`) lo
// devuelven, porque son otra persona o una que llega por primera vez.

export const HIDDEN_KEY = 'rappi-proto-mochi-oculto'
const CHANGE_EVENT = 'agent-oculto'
// Sin almacenamiento (ventana privada): dura lo que la pestaña.
let memory = false

export function isAgentHidden() {
  try {
    return localStorage.getItem(HIDDEN_KEY) === '1'
  } catch {
    return memory
  }
}

/** Oculta a Mochi (`true`) o lo trae de vuelta (`false`), y avisa a quien lo esté mostrando. */
export function setAgentHidden(hidden) {
  memory = hidden
  try {
    if (hidden) localStorage.setItem(HIDDEN_KEY, '1')
    else localStorage.removeItem(HIDDEN_KEY)
  } catch {
    // Queda en memoria.
  }
  window.dispatchEvent(new Event(CHANGE_EVENT))
}

function subscribe(onChange) {
  window.addEventListener(CHANGE_EVENT, onChange)
  window.addEventListener('storage', onChange) // otra pestaña lo cambió
  return () => {
    window.removeEventListener(CHANGE_EVENT, onChange)
    window.removeEventListener('storage', onChange)
  }
}

/** `true` si la persona ocultó a Mochi; se actualiza al cambiarlo desde el menú o desde Cuenta. */
export function useAgentHidden() {
  return useSyncExternalStore(subscribe, isAgentHidden, () => false)
}
