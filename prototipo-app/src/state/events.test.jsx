import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { DemoProvider } from './DemoContext'
import { resetHealthCache } from '../api/client'
import { userId } from '../api/user'
import { EventsProvider, noteShownTopic, sessionId, shownTopics, useEvents } from './EventsContext'

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
})
afterEach(() => vi.unstubAllGlobals())

describe('identidad seudónima y sesiones', () => {
  test('el id de usuario se conserva en este navegador', () => {
    const first = userId()
    expect(first).toMatch(/^proto-/)
    expect(userId()).toBe(first)
  })

  test('sin randomUUID (página por http en el iPhone) el id sigue siendo aleatorio y largo', () => {
    // randomUUID solo existe en contexto seguro (https o localhost); por la IP de la red local no está.
    const original = crypto.randomUUID
    Object.defineProperty(crypto, 'randomUUID', { value: undefined, configurable: true })
    try {
      localStorage.clear()
      const id = userId()
      expect(id).toMatch(/^proto-[0-9a-f]{16}$/)
      expect(id.slice(6).startsWith(String(Date.now()).slice(0, 8))).toBe(false) // no es la hora: no se adivina
    } finally {
      Object.defineProperty(crypto, 'randomUUID', { value: original, configurable: true })
    }
  })

  test('la sesión se renueva tras 30 minutos sin actividad', () => {
    const t0 = 1_000_000
    const a = sessionId(t0)
    expect(sessionId(t0 + 10 * 60 * 1000)).toBe(a)
    expect(sessionId(t0 + 10 * 60 * 1000 + 31 * 60 * 1000)).not.toBe(a)
  })

  test('los temas ya sugeridos viven con la sesión: una recarga no los olvida, una sesión nueva empieza sin ellos', () => {
    const t0 = 1_000_000
    noteShownTopic('jugos', t0)
    noteShownTopic('jugos', t0)
    expect(shownTopics(t0 + 60 * 1000)).toEqual(['jugos'])
    expect(shownTopics(t0 + 60 * 1000 + 31 * 60 * 1000)).toEqual([])
  })
})

describe('eventos', () => {
  const setup = () =>
    renderHook(() => useEvents(), {
      wrapper: ({ children }) => (
        <DemoProvider>
          <EventsProvider>{children}</EventsProvider>
        </DemoProvider>
      ),
    })

  test('se envían en lote con el id del usuario y la sesión', async () => {
    const fetchMock = vi.fn(async (url) => ({
      ok: true,
      json: async () => (String(url).endsWith('/health') ? { capacidades: {} } : { guardados: 2 }),
    }))
    vi.stubGlobal('fetch', fetchMock)
    const { result } = setup()
    act(() => result.current.track('search', { query: 'chelas', concept_id: 'cerveza' }))
    await act(() => result.current.flush())
    const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/events'))
    const body = JSON.parse(call[1].body)
    expect(body.user_id).toMatch(/^proto-/)
    expect(body.events.map((e) => e.type)).toEqual(['app_open', 'search'])
    expect(body.events[1]).toMatchObject({ query: 'chelas', concept_id: 'cerveza' })
    expect(body.events[1].payload).toBeUndefined() // en la propuesta no van marcados: enseñan
  })

  test('en modo "Rappi hoy" los eventos van sin concepto y marcados `mode: actual`: ni Mochi ni el motor aprenden', async () => {
    localStorage.setItem('rappi-proto-demo-mode', 'actual')
    const fetchMock = vi.fn(async (url) => ({
      ok: true,
      json: async () => (String(url).endsWith('/health') ? { capacidades: {} } : {}),
    }))
    vi.stubGlobal('fetch', fetchMock)
    const { result } = setup()
    act(() => result.current.track('cart_add', { concept_id: 'cerveza' }))
    act(() => result.current.track('vertical_open', { vertical: 'farmacia' }))
    act(() => result.current.track('service_shown', { payload: { servicio: 'travel' } }))
    await act(() => result.current.flush())
    const body = JSON.parse(fetchMock.mock.calls.find(([url]) => String(url).endsWith('/events'))[1].body)
    expect(body.events.find((e) => e.type === 'cart_add').concept_id).toBeUndefined()
    expect(body.events.find((e) => e.type === 'vertical_open').payload).toEqual({ mode: 'actual' })
    // Lo que ya traía el payload se conserva.
    expect(body.events.find((e) => e.type === 'service_shown').payload).toEqual({ servicio: 'travel', mode: 'actual' })
    expect(body.events.every((e) => e.payload?.mode === 'actual')).toBe(true)
  })
})

test('clear descarta lo pendiente (Olvidar no se deshace con eventos en cola)', async () => {
  const fetchMock = vi.fn(async (url) => ({
    ok: true,
    json: async () => (String(url).endsWith('/health') ? { capacidades: {} } : {}),
  }))
  vi.stubGlobal('fetch', fetchMock)
  const { result } = renderHook(() => useEvents(), {
    wrapper: ({ children }) => (
      <DemoProvider>
        <EventsProvider>{children}</EventsProvider>
      </DemoProvider>
    ),
  })
  act(() => result.current.track('cart_add', { concept_id: 'cerveza' }))
  act(() => result.current.clear())
  await act(() => result.current.flush())
  expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/events'))).toBe(false)
})

describe('regresiones', () => {
  const setup = () =>
    renderHook(() => useEvents(), {
      wrapper: ({ children }) => (
        <DemoProvider>
          <EventsProvider>{children}</EventsProvider>
        </DemoProvider>
      ),
    })
  const eventsBody = (fetchMock) =>
    JSON.parse(fetchMock.mock.calls.find(([url]) => String(url).endsWith('/events'))[1].body)

  test('un texto más largo que el límite del servidor se recorta: no hace fallar el lote completo', async () => {
    const fetchMock = vi.fn(async (url) => ({
      ok: true,
      json: async () => (String(url).endsWith('/health') ? { capacidades: {} } : {}),
    }))
    vi.stubGlobal('fetch', fetchMock)
    const { result } = setup()
    act(() => result.current.track('search', { query: 'a'.repeat(600), entity_id: 'x'.repeat(80) }))
    await act(() => result.current.flush())
    const search = eventsBody(fetchMock).events.find((e) => e.type === 'search')
    expect(search.query).toHaveLength(500)
    expect(search.entity_id).toHaveLength(64)
  })

  test('settled espera el lote que ya salió (Olvidar no se adelanta a un envío en curso)', async () => {
    let answer
    const fetchMock = vi.fn((url) =>
      String(url).endsWith('/health')
        ? Promise.resolve({ ok: true, json: async () => ({ capacidades: {} }) })
        : new Promise((resolve) => (answer = () => resolve({ ok: true, json: async () => ({}) }))),
    )
    vi.stubGlobal('fetch', fetchMock)
    const { result } = setup()
    act(() => result.current.track('cart_add', { concept_id: 'cerveza' }))
    let sending
    act(() => {
      sending = result.current.flush()
    })
    let settled = false
    result.current.settled().then(() => (settled = true))
    await vi.waitFor(() => expect(answer).toBeTypeOf('function'))
    await Promise.resolve()
    expect(settled).toBe(false)
    answer()
    await act(() => sending)
    await vi.waitFor(() => expect(settled).toBe(true))
  })

  test('al ocultar la página, la cola solo se vacía si el navegador aceptó el beacon', async () => {
    const fetchMock = vi.fn(async (url) => ({
      ok: true,
      json: async () => (String(url).endsWith('/health') ? { capacidades: {} } : {}),
    }))
    vi.stubGlobal('fetch', fetchMock)
    Object.defineProperty(navigator, 'sendBeacon', { value: vi.fn(() => false), configurable: true })
    try {
      const { result } = setup()
      act(() => result.current.track('cart_add', { concept_id: 'cerveza' }))
      window.dispatchEvent(new Event('pagehide'))
      await act(() => result.current.flush())
      expect(eventsBody(fetchMock).events.map((e) => e.type)).toEqual(['app_open', 'cart_add'])
    } finally {
      delete navigator.sendBeacon
    }
  })
})

test('con la API todavía sin responder, el lote espera en la cola y sale al segundo intento', async () => {
  resetHealthCache()
  let online = false
  const fetchMock = vi.fn(async (url) => {
    if (!online) throw new TypeError('Failed to fetch')
    return { ok: true, json: async () => (String(url).endsWith('/health') ? { capacidades: {} } : {}) }
  })
  vi.stubGlobal('fetch', fetchMock)
  const { result } = renderHook(() => useEvents(), {
    wrapper: ({ children }) => (
      <DemoProvider>
        <EventsProvider>{children}</EventsProvider>
      </DemoProvider>
    ),
  })
  act(() => result.current.track('cart_add', { concept_id: 'cerveza' }))
  await act(() => result.current.flush())
  expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/events'))).toBe(false)

  online = true
  resetHealthCache()
  await act(() => result.current.flush())
  const body = JSON.parse(fetchMock.mock.calls.find(([url]) => String(url).endsWith('/events'))[1].body)
  expect(body.events.map((e) => e.type)).toEqual(['app_open', 'cart_add'])
})
