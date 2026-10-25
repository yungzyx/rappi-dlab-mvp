const KEY = 'rappi-proto-recargado'

/**
 * Tras un despliegue nuevo, una pestaña abierta pide un archivo con el nombre viejo y recibe 404 (Vite avisa con
 * `vite:preloadError`). Recarga la página una sola vez por sesión (la bandera vive en sessionStorage; sin él, en
 * memoria) para no entrar en un bucle si el archivo de verdad falta. Devuelve la función que quita el aviso.
 */
export function reloadOnPreloadError({ reload = () => window.location.reload(), storage = sessionStorage } = {}) {
  let reloaded = false
  const wasReloaded = () => {
    try {
      return storage.getItem(KEY) !== null
    } catch {
      return reloaded
    }
  }
  const onError = (event) => {
    if (wasReloaded()) return // la segunda vez el error llega a la pantalla, que ofrece «Volver al inicio»
    reloaded = true
    try {
      storage.setItem(KEY, '1')
    } catch {
      // Sin sessionStorage la bandera queda en memoria.
    }
    event.preventDefault() // ya se recarga: no hace falta mostrar el error
    reload()
  }
  window.addEventListener('vite:preloadError', onError)
  return () => window.removeEventListener('vite:preloadError', onError)
}
