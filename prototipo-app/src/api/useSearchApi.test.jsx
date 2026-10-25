import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { fixture, stubApi } from '../test/api'
import { useSearchApi } from './useSearchApi'

beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const advance = (ms) => act(async () => vi.advanceTimersByTimeAsync(ms))
const asked = (fetchMock) => fetchMock.mock.calls.map(([url]) => new URL(url).searchParams.get('q'))

/** Respuesta de /search con un solo producto, para distinguir cuál llegó. */
const reply = (name) => {
  const base = fixture('search-grouped')
  base.groups = [{ ...base.groups[0], products: [{ ...base.groups[0].products[0], name }] }]
  return base
}

describe('useSearchApi', () => {
  test('la búsqueda espera 250 ms tras la última tecla', async () => {
    const fetchMock = stubApi({ '/search': fixture('search-grouped') })
    const { result, rerender } = renderHook(({ q }) => useSearchApi(q), { initialProps: { q: '' } })

    rerender({ q: 'ce' })
    await advance(200)
    rerender({ q: 'cer' })
    await advance(200)
    rerender({ q: 'cerv' })
    await advance(249)
    expect(fetchMock).not.toHaveBeenCalled()
    expect(result.current.loading).toBe(true)

    await advance(1)
    expect(asked(fetchMock)).toEqual(['cerv'])
    expect(result.current).toMatchObject({ loading: false, error: null })
    expect(result.current.data.groups[0].vertical).toBe('liquor')
  })

  test('con menos de 2 caracteres no consulta', async () => {
    const fetchMock = stubApi({ '/search': fixture('search-grouped') })
    const { result, rerender } = renderHook(({ q }) => useSearchApi(q), { initialProps: { q: ' c ' } })
    await advance(1000)
    expect(fetchMock).not.toHaveBeenCalled()
    expect(result.current).toMatchObject({ data: null, loading: false, error: null })

    rerender({ q: 'cerveza' })
    await advance(250)
    expect(result.current.data).not.toBeNull()
    // Al borrar el texto no quedan a la vista los resultados anteriores.
    rerender({ q: 'c' })
    expect(result.current).toMatchObject({ data: null, loading: false })
    await advance(1000)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  test('una respuesta vieja no reemplaza a una nueva', async () => {
    stubApi({
      '/search': (req) => (req.query.get('q') === 'cerv' ? { slow: 1000, body: reply('vieja') } : reply('nueva')),
    })
    const { result, rerender } = renderHook(({ q }) => useSearchApi(q), { initialProps: { q: 'cerv' } })
    await advance(250) // sale la consulta lenta
    rerender({ q: 'cerve' })
    await advance(250) // sale la rápida y llega primero
    expect(result.current.data.groups[0].products[0].name).toBe('nueva')

    await advance(2000) // llega la lenta
    expect(result.current.data.groups[0].products[0].name).toBe('nueva')
    expect(result.current.loading).toBe(false)
  })

  test('mientras carga se ven los resultados anteriores', async () => {
    stubApi({
      '/search': (req) => (req.query.get('q') === 'cerveza' ? reply('primera') : { slow: 500, body: reply('segunda') }),
    })
    const { result, rerender } = renderHook(({ q }) => useSearchApi(q), { initialProps: { q: 'cerveza' } })
    await advance(250)
    expect(result.current.data.groups[0].products[0].name).toBe('primera')

    rerender({ q: 'cerveza fria' })
    // Esperando la tecla y esperando la API: los de antes siguen, y se avisa que carga.
    expect(result.current).toMatchObject({ loading: true })
    expect(result.current.data.groups[0].products[0].name).toBe('primera')
    await advance(250)
    expect(result.current.loading).toBe(true)
    expect(result.current.data.groups[0].products[0].name).toBe('primera')

    await advance(500)
    expect(result.current.loading).toBe(false)
    expect(result.current.data.groups[0].products[0].name).toBe('segunda')
  })

  test('con vertical busca solo ahí y sin API entrega el error y reintenta', async () => {
    let online = false
    const fetchMock = stubApi({
      '/search': (req) =>
        online ? { vertical: req.query.get('vertical'), products: [], unmet: true, unmet_reason: 'nada' } : 'offline',
    })
    const { result } = renderHook(() => useSearchApi('cerveza', { vertical: 'licores' }))
    await advance(250)
    expect(result.current.error).toMatchObject({ kind: 'offline' })
    expect(new URL(fetchMock.mock.calls[0][0]).searchParams.get('vertical')).toBe('licores')

    online = true
    act(() => result.current.retry())
    await advance(0)
    expect(result.current.error).toBeNull()
    expect(result.current.data).toMatchObject({ unmet: true, groups: [{ backendVertical: 'licores', products: [] }] })
  })
})
