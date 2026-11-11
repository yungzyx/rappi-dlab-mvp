import { afterEach, describe, expect, test, vi } from 'vitest'
import { reloadOnPreloadError } from './preloadError.js'

afterEach(() => sessionStorage.clear())

describe('chunk que no carga tras un despliegue', () => {
  test('preloadError recarga una sola vez por sesión, para no entrar en bucle', () => {
    const reload = vi.fn()
    const stop = reloadOnPreloadError({ reload })
    const first = new Event('vite:preloadError', { cancelable: true })
    window.dispatchEvent(first)
    expect(reload).toHaveBeenCalledTimes(1)
    expect(first.defaultPrevented).toBe(true) // la recarga ya va: no hace falta mostrar el error

    const second = new Event('vite:preloadError', { cancelable: true })
    window.dispatchEvent(second)
    expect(reload).toHaveBeenCalledTimes(1)
    expect(second.defaultPrevented).toBe(false) // la segunda vez el error llega a la pantalla
    stop()
  })

  test('con sessionStorage bloqueado no recarga: la bandera se perdería y la recarga se repetiría sin fin', () => {
    const original = Object.getOwnPropertyDescriptor(globalThis, 'sessionStorage')
    Object.defineProperty(globalThis, 'sessionStorage', {
      configurable: true,
      get: () => {
        throw new DOMException('bloqueado', 'SecurityError')
      },
    })
    try {
      const reload = vi.fn()
      const stop = reloadOnPreloadError({ reload })
      const event = new Event('vite:preloadError', { cancelable: true })
      window.dispatchEvent(event)
      expect(reload).not.toHaveBeenCalled()
      expect(event.defaultPrevented).toBe(false) // el error llega a la pantalla, que ofrece "Volver al inicio"
      stop()
    } finally {
      Object.defineProperty(globalThis, 'sessionStorage', original)
    }
  })
})
