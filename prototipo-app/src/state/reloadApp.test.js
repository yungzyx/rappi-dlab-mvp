import { afterEach, describe, expect, test, vi } from 'vitest'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('reloadToHome', () => {
  test('lleva la dirección a #/home y recarga, en ese orden', async () => {
    const { reloadToHome } = await vi.importActual('./reloadApp.js')
    const calls = []
    vi.stubGlobal('location', {
      pathname: '/app/',
      search: '?x=1',
      reload: () => calls.push(['reload']),
    })
    vi.spyOn(window.history, 'replaceState').mockImplementation((state, _title, url) =>
      calls.push(['replace', state, url]),
    )
    reloadToHome()
    expect(calls).toEqual([['replace', null, '/app/?x=1#/home'], ['reload']])
  })
})

describe('reloadToHome con el historial real', () => {
  test('descarta el estado de la pantalla guardado en el historial antes de recargar', async () => {
    const { reloadToHome } = await vi.importActual('./reloadApp.js')
    const real = window.location
    const reload = vi.fn(() => {
      // Lo que lee useNavigation al arrancar tras la recarga: sin estado nuestro, la ruta sale del hash.
      expect(window.history.state?.nav).toBeUndefined()
      expect(real.hash).toBe('#/home')
    })
    vi.stubGlobal('location', {
      get pathname() {
        return real.pathname
      },
      get search() {
        return real.search
      },
      get hash() {
        return real.hash
      },
      reload,
    })
    const nav = { stack: [{ name: 'home', params: {} }], homeTab: 'home' }
    window.history.replaceState({ nav, assistant: true }, '', '#/home')
    reloadToHome()
    expect(reload).toHaveBeenCalledTimes(1)
  })
})
