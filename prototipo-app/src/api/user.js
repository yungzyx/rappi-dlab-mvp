// Id seudónimo de este navegador, compartido por quienes hablan con la API (eventos, preguntas, pedidos, «Para ti»), y
// el token que lo firma. Los ayudantes de almacenamiento también los usa la sesión de EventsContext.

const USER_KEY = 'rappi-proto-user'

// randomUUID solo existe en contexto seguro (https o localhost): abierta por la IP de la red (iPhone) no está, y el
// respaldo con la hora daba ids adivinables. getRandomValues sí funciona por http.
export function randomId(prefix) {
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(8))
  return `${prefix}-${Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')}`
}

export function readStore(storage, key) {
  try {
    return storage.getItem(key)
  } catch {
    return null
  }
}

export function writeStore(storage, key, value) {
  try {
    storage.setItem(key, value)
  } catch {
    // Modo privado: el id vive solo en memoria.
  }
}

// La sesión de este navegador: el id que dio la API (`POST /session`) y su token firmado, que va en X-User-Token. Sin
// almacenamiento (el navegador lo bloquea), vive en memoria mientras la pestaña siga abierta.
const TOKEN_KEY = 'rappi-proto-token'
const memory = new Map()

function load(key) {
  try {
    return localStorage.getItem(key)
  } catch {
    return memory.get(key) ?? null
  }
}

function save(key, value) {
  try {
    localStorage.setItem(key, value)
  } catch {
    memory.set(key, value)
  }
}

function drop(key) {
  memory.delete(key)
  try {
    localStorage.removeItem(key)
  } catch {
    // Sin almacenamiento no hay nada que borrar.
  }
}

/**
 * Id seudónimo de este navegador (no es una cuenta ni un dato personal). Lo da la API con la sesión. Si se perdió, se
 * inventa uno sin token (un token que quedó es de otro id: con él todo daría 403); el primer 401 pide la sesión.
 */
export function userId() {
  let id = load(USER_KEY)
  if (!id) {
    drop(TOKEN_KEY)
    id = randomId('proto')
    save(USER_KEY, id)
  }
  return id
}

/** El id guardado, sin crear uno (null si no hay): el «id viejo» que la primera sesión reclama. */
export const storedUserId = () => load(USER_KEY)

/** El token de la sesión (null sin sesión). */
export const userToken = () => load(TOKEN_KEY)

/** Guarda la sesión que dio la API: desde aquí, `userId()` es ese id. */
export function saveSession({ user_id: id, token }) {
  save(USER_KEY, id)
  save(TOKEN_KEY, token)
}

/** Olvida el id y el token (tras «Borrar mis datos»): la próxima sesión es de una persona nueva. */
export function clearSession() {
  drop(USER_KEY)
  drop(TOKEN_KEY)
}
