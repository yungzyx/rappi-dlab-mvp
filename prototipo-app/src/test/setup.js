// Se corre antes de cada archivo de pruebas.
import { afterEach, vi } from 'vitest'

// "Borrar mis datos" recarga la página: en las pruebas es un doble que se puede revisar (`reloadToHome` importado de la app).
vi.mock('../state/reloadApp.js', () => ({ reloadToHome: vi.fn() }))

// Lo que la app guarda en la pestaña (la sesión, lo pendiente de Mochi, lo rechazado) no pasa de una prueba a otra:
// cada una empieza como en una pestaña nueva.
afterEach(() => sessionStorage.clear())
