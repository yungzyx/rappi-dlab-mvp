// Estado del prototipo guardado en el navegador (mismo patrón que OrdersContext): en modo privado o sin
// almacenamiento, todo sigue funcionando en memoria.

/** Lee y valida lo guardado; si falta, está corrupto o no pasa `isValid`, devuelve `fallback`. */
export function loadStored(key, isValid, fallback) {
  try {
    const raw = localStorage.getItem(key)
    if (raw == null) return fallback
    const parsed = JSON.parse(raw)
    return isValid(parsed) ? parsed : fallback
  } catch {
    return fallback
  }
}

export function saveStored(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // Sin almacenamiento: el estado vive solo en memoria.
  }
}

/**
 * sessionStorage o localStorage con respaldo en memoria. Tocarlos puede lanzar (SecurityError: Safari en modo estricto,
 * cookies de terceros bloqueadas, un iframe sin almacenamiento) o pueden faltar (pruebas sin jsdom): lo que el navegador
 * no acepta vive en memoria mientras dure la página, y se lee igual. Así nadie necesita su propio try/catch.
 */
function browserStore(name) {
  const memory = new Map()
  const storage = () => globalThis[name] // en un navegador que lo bloquea, solo leerlo ya lanza
  return {
    get(key) {
      try {
        const value = storage().getItem(key)
        if (value !== null) return value
      } catch {
        // Bloqueado: queda lo de la memoria.
      }
      return memory.get(key) ?? null
    },
    set(key, value) {
      try {
        storage().setItem(key, value)
        memory.delete(key)
      } catch {
        memory.set(key, value)
      }
    },
    remove(key) {
      memory.delete(key)
      try {
        storage().removeItem(key)
      } catch {
        // Sin almacenamiento no hay más que borrar.
      }
    },
    /** Borra las claves que empiezan con `prefix`, salvo las de `keep`. */
    clear(prefix = '', keep = []) {
      const drop = (key) => key?.startsWith(prefix) && !keep.includes(key)
      for (const key of [...memory.keys()]) if (drop(key)) memory.delete(key)
      try {
        const store = storage()
        const keys = Array.from({ length: store.length }, (_, i) => store.key(i)).filter(drop)
        for (const key of keys) store.removeItem(key)
      } catch {
        // Sin almacenamiento no hay más que borrar.
      }
    },
  }
}

/** Lo de la pestaña (sessionStorage): la sesión de los eventos, la bandera de recarga. */
export const tabStore = browserStore('sessionStorage')
/** Lo del navegador (localStorage): el id seudónimo y su token. */
export const localStore = browserStore('localStorage')
