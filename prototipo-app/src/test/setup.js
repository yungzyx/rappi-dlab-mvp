// Se corre antes de cada archivo de pruebas.
import { vi } from 'vitest'

// «Borrar mis datos» recarga la página: en las pruebas es un doble que se puede revisar (`reloadToHome` importado de la app).
vi.mock('../state/reloadApp.js', () => ({ reloadToHome: vi.fn() }))
