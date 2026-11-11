import { tabStore } from './state/storage.js'

const KEY = 'rappi-proto-recargado'

/**
 * Tras un despliegue nuevo, una pestaña abierta pide un archivo con el nombre viejo y recibe 404 (Vite avisa con
 * `vite:preloadError`). Recarga la página una sola vez por sesión (la bandera vive en sessionStorage) para no entrar en
 * un bucle si el archivo de verdad falta. Si el navegador no guarda la bandera (sessionStorage bloqueado), no recarga:
 * la bandera se perdería con la recarga y podría repetirse sin fin. Devuelve la función que quita el aviso.
 */
export function reloadOnPreloadError({ reload = () => window.location.reload() } = {}) {
  const onError = (event) => {
    // La segunda vez (o sin dónde guardar la bandera) el error llega a la pantalla, que ofrece "Volver al inicio".
    if (tabStore.get(KEY) !== null || !tabStore.set(KEY, '1')) return
    event.preventDefault() // ya se recarga: no hace falta mostrar el error
    reload()
  }
  window.addEventListener('vite:preloadError', onError)
  return () => window.removeEventListener('vite:preloadError', onError)
}
