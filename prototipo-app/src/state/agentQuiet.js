// Cuándo el agente no habla por iniciativa propia: si la persona lo silenció por hoy (se guarda en el navegador) o si
// cerró dos globos seguidos (dura lo que la pestaña). Una mascota que insiste molesta.

export const QUIET_KEY = 'rappi-proto-mochi-silencio'
const HUSH_AFTER_DISMISSALS = 2

let dismissedInARow = 0

/** Silenciado hoy (`today` en AAAA-MM-DD): el agente queda como una pestañita en el borde. */
export function isQuiet(today) {
  try {
    return localStorage.getItem(QUIET_KEY) === today
  } catch {
    return false
  }
}

export function quietToday(today) {
  try {
    localStorage.setItem(QUIET_KEY, today)
  } catch {
    // Sin almacenamiento: el silencio no se guarda, el agente vuelve al recargar.
  }
}

export function wake() {
  dismissedInARow = 0
  try {
    localStorage.removeItem(QUIET_KEY)
  } catch {
    // Nada guardado que borrar.
  }
}

/** Cerró un globo sin usarlo. */
export function noteDismissed() {
  dismissedInARow += 1
}

/** Usó algo del agente (un botón del globo o del menú): la racha de cierres vuelve a cero. */
export function noteEngaged() {
  dismissedInARow = 0
}

/** Lo ignoraron dos veces seguidas: sigue a la vista, pero no habla por su cuenta el resto de la sesión. */
export function isHushed() {
  return dismissedInARow >= HUSH_AFTER_DISMISSALS
}

/** «Repetir escena»: como una persona que llega por primera vez. */
export function resetQuiet() {
  wake()
}
