import { act, cleanup, render, renderHook, screen } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, test, vi } from 'vitest'
import { fixture, stubApi } from './test/api'
import App from './App'
import { resetHealthCache } from './api/client'
import { reloadOnPreloadError } from './preloadError.js'
import { DemoProvider } from './state/DemoContext'
import { EventsProvider, sessionId, useEvents } from './state/EventsContext'

// Un navegador que bloquea sessionStorage (Safari en modo estricto, cookies de terceros bloqueadas, un iframe sin
// almacenamiento): leer `sessionStorage` ya lanza un SecurityError, o existe pero cada uso lanza. La app arranca y la
// sesión vive en memoria durante la pestaña, con el mismo id y la misma expiración.
const original = Object.getOwnPropertyDescriptor(globalThis, 'sessionStorage')
const thrower = () => {
  throw new DOMException('El acceso al almacenamiento está bloqueado', 'SecurityError')
}
const BLOCKED = {
  'leerlo lanza': () => Object.defineProperty(globalThis, 'sessionStorage', { configurable: true, get: thrower }),
  'cada uso lanza': () =>
    Object.defineProperty(globalThis, 'sessionStorage', {
      configurable: true,
      value: { getItem: thrower, setItem: thrower, removeItem: thrower, key: thrower, clear: thrower, length: 0 },
    }),
}

let consoleError
beforeAll(() => {
  Element.prototype.scrollTo = () => {}
})
afterAll(() => {
  delete Element.prototype.scrollTo
})
beforeEach(() => {
  localStorage.setItem('rappi-proto-demo-mode', 'actual')
  localStorage.setItem('rappi-proto-privacy-seen', '1')
  consoleError = vi.spyOn(console, 'error')
})
afterEach(() => {
  cleanup()
  Object.defineProperty(globalThis, 'sessionStorage', original)
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  localStorage.clear()
})

const wrapper = ({ children }) => (
  <DemoProvider>
    <EventsProvider>{children}</EventsProvider>
  </DemoProvider>
)
const sentEvents = (fetchMock) =>
  fetchMock.mock.calls
    .filter(([url]) => String(url).endsWith('/events'))
    .flatMap(([, init]) => JSON.parse(init.body).events)

describe.each(Object.keys(BLOCKED))('sessionStorage bloqueado (%s)', (how) => {
  beforeEach(() => BLOCKED[how]())

  test('la app arranca sin errores', async () => {
    stubApi({ '/catalog/home': fixture('catalog-home') })
    window.history.replaceState(null, '', '/')
    expect(() => reloadOnPreloadError()()).not.toThrow() // lo primero que corre main.jsx
    render(<App />)
    expect(await screen.findByText(/Prototipo dLab con Rappi/)).toBeTruthy()
    expect(consoleError).not.toHaveBeenCalled()
  })

  test('los eventos de la pestaña llevan un mismo id de sesión y su orden sigue', async () => {
    resetHealthCache()
    const fetchMock = stubApi({ '/health': { capacidades: {} }, 'POST /events': { guardados: 1 } })
    const { result } = renderHook(() => useEvents(), { wrapper })
    act(() => result.current.track('search', { query: 'chelas' }))
    await act(() => result.current.flush())
    act(() => result.current.track('cart_add', { concept_id: 'cerveza' }))
    await act(() => result.current.flush())
    const events = sentEvents(fetchMock)
    expect(events.map((e) => e.type)).toEqual(['app_open', 'search', 'cart_add'])
    expect(new Set(events.map((e) => e.session_id)).size).toBe(1)
    expect(events[0].session_id).toBe(sessionId())
    expect(events.map((e) => e.seq)).toEqual([0, 1, 2])
    expect(consoleError).not.toHaveBeenCalled()
  })

  test('la sesión en memoria se renueva igual: tras 30 minutos sin actividad', () => {
    const t0 = Date.now() + 24 * 60 * 60 * 1000 // después de la sesión de las pruebas anteriores
    const a = sessionId(t0)
    expect(sessionId(t0 + 10 * 60 * 1000)).toBe(a)
    expect(sessionId(t0 + 10 * 60 * 1000 + 31 * 60 * 1000)).not.toBe(a)
  })
})
