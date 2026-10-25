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

  test('sin sessionStorage tampoco entra en bucle', () => {
    const reload = vi.fn()
    const broken = {
      getItem: () => {
        throw new Error('bloqueado')
      },
      setItem: () => {
        throw new Error('bloqueado')
      },
    }
    const stop = reloadOnPreloadError({ reload, storage: broken })
    window.dispatchEvent(new Event('vite:preloadError', { cancelable: true }))
    window.dispatchEvent(new Event('vite:preloadError', { cancelable: true }))
    expect(reload).toHaveBeenCalledTimes(1)
    stop()
  })
})
