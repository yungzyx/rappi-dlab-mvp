// Id seudónimo de este navegador, compartido por quienes hablan con la API (eventos, preguntas, pedidos, "Para ti"), y
// el token que lo firma.
import { localStore } from '../state/storage'

const USER_KEY = 'rappi-proto-user'

// randomUUID solo existe en contexto seguro (https o localhost): abierta por la IP de la red (iPhone) no está, y el
// respaldo con la hora daba ids adivinables. getRandomValues sí funciona por http.
export function randomId(prefix) {
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(8))
  return `${prefix}-${Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')}`
}

/** Un uuid v4 (el id de cada evento), también fuera de un contexto seguro, donde `crypto.randomUUID` no existe. */
export function randomUuid() {
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

// La sesión de este navegador: el id que dio la API (`POST /session`) y su token firmado, que va en X-User-Token. Sin
// almacenamiento (el navegador lo bloquea), vive en memoria mientras la pestaña siga abierta (`localStore`).
const TOKEN_KEY = 'rappi-proto-token'
const load = (key) => localStore.get(key)
const save = (key, value) => localStore.set(key, value)
const drop = (key) => localStore.remove(key)

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

/** El id guardado, sin crear uno (null si no hay): el "id viejo" que la primera sesión reclama. */
export const storedUserId = () => load(USER_KEY)

/** El token de la sesión (null sin sesión). */
export const userToken = () => load(TOKEN_KEY)

/** Guarda la sesión que dio la API: desde aquí, `userId()` es ese id. */
export function saveSession({ user_id: id, token }) {
  save(USER_KEY, id)
  save(TOKEN_KEY, token)
}

/** Olvida el id y el token (tras "Borrar mis datos"): la próxima sesión es de una persona nueva. */
export function clearSession() {
  drop(USER_KEY)
  drop(TOKEN_KEY)
}
