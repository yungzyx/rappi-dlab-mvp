import { useSyncExternalStore } from 'react'
import { localStore } from './storage'

// El grupo de control "Mochi apagado" (`ofertas_control`, docs/plan-piloto.md): lo decide la API al azar y lo dice con
// la sesión (`agent_enabled` de `POST /session` y de `GET /session`, que la app pide cada vez que abre). Apagado, la app
// no muestra a Mochi en ninguna parte (ni la mascota, ni sus ofertas, ni su buscador: el de siempre) y "Cuenta" no
// ofrece traerlo; conserva "Para ti" y el orden de la Home. Las ofertas que la app pide sola las sigue pidiendo (la API
// las retiene y las anota igual que en tratamiento: api/agent.js). No es "Ocultar a Mochi" (agentHidden.js), que lo
// decide la persona y se mide aparte. Se guarda con la sesión (`rappi-proto-*`: "Borrar mis datos" lo borra); sin
// sesión, o con una API que no lo dice, Mochi está.

export const ENABLED_KEY = 'rappi-proto-mochi-activo'
const CHANGE_EVENT = 'agent-activo'

/** `false` solo si la API dijo que la persona está en el grupo de control. */
export const isAgentEnabled = () => localStore.get(ENABLED_KEY) !== '0'

/** Guarda lo que dijo la API (`agent_enabled`; si no lo trae, Mochi está) y avisa a quien lo esté mostrando. */
export function setAgentEnabled(enabled) {
  const before = isAgentEnabled()
  if (enabled === false) localStore.set(ENABLED_KEY, '0')
  else localStore.remove(ENABLED_KEY)
  if (before !== isAgentEnabled()) globalThis.window?.dispatchEvent(new Event(CHANGE_EVENT))
}

function subscribe(onChange) {
  window.addEventListener(CHANGE_EVENT, onChange)
  return () => window.removeEventListener(CHANGE_EVENT, onChange)
}

/** `true` si la persona tiene a Mochi (no está en el grupo de control). */
export function useAgentEnabled() {
  return useSyncExternalStore(subscribe, isAgentEnabled, () => true)
}
