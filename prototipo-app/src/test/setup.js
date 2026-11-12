// Se corre antes de cada archivo de pruebas.
import { afterEach, vi } from 'vitest'
import { tabStore } from '../state/storage'

// "Borrar mis datos" recarga la página: en las pruebas es un doble que se puede revisar (`reloadToHome` importado de la app).
vi.mock('../state/reloadApp.js', () => ({ reloadToHome: vi.fn() }))

// Lo que la app guarda en la pestaña (la sesión, lo pendiente de Mochi, lo rechazado) no pasa de una prueba a otra:
// cada una empieza como en una pestaña nueva, también lo que quedó en memoria porque el almacenamiento faltaba (las
// pruebas en entorno node, sin jsdom, no tienen sessionStorage en Node 24, el del CI) o estaba bloqueado.
afterEach(() => tabStore.clear())
