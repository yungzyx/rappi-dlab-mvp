import { tabStore } from './state/storage.js'

const KEY = 'rappi-proto-recargado'

/**
 * Tras un despliegue nuevo, una pestaña abierta pide un archivo con el nombre viejo y recibe 404 (Vite avisa con
 * `vite:preloadError`). Recarga la página una sola vez por sesión (la bandera vive en sessionStorage; si el navegador lo
 * bloquea, en memoria) para no entrar en un bucle si el archivo de verdad falta. Devuelve la función que quita el aviso.
 */
export function reloadOnPreloadError({ reload = () => window.location.reload() } = {}) {
  const onError = (event) => {
    if (tabStore.get(KEY) !== null) return // la segunda vez el error llega a la pantalla, que ofrece "Volver al inicio"
    tabStore.set(KEY, '1')
    event.preventDefault() // ya se recarga: no hace falta mostrar el error
    reload()
  }
  window.addEventListener('vite:preloadError', onError)
  return () => window.removeEventListener('vite:preloadError', onError)
}
