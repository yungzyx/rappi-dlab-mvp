import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { apiUrl, getFallbacks, loadAnalytics, refreshSource, retryConnection, subscribeConnection } from './api.js'
import savedKpis from '../fixtures/sin-conexion/kpis.json'
import savedWeekly from '../fixtures/sin-conexion/weekly.json'
import savedSuggestions from '../fixtures/sin-conexion/suggestions.json'
import savedOffers from '../fixtures/sin-conexion/offers.json'

const jsonResponse = (body, status = 200) => ({ ok: status < 400, status, json: async () => body })

describe('loadAnalytics', () => {
  beforeEach(() => {
    retryConnection()
    vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  test('usa la API cuando responde', async () => {
    const live = { source: 'synthetic', data: { usuarios_activos: 7 } }
    const fetchMock = vi.fn(async () => jsonResponse(live))
    vi.stubGlobal('fetch', fetchMock)

    const result = await loadAnalytics('kpis', 'synthetic')

    expect(result).toEqual({ data: { usuarios_activos: 7 }, offline: false, saved: null })
    expect(fetchMock.mock.calls[0][0]).toBe('http://localhost:8000/analytics/kpis?source=synthetic')
    expect(getFallbacks()).toEqual([])
  })

  test('solo el motor acepta `data: null`: otra métrica con null cae a lo guardado', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ source: 'synthetic', data: null })),
    )

    const result = await loadAnalytics('kpis', 'synthetic')

    expect(result).toEqual({ data: savedKpis.data, offline: true, saved: savedKpis.guardado })
  })

  test('una métrica sin datos (`data: null`, el motor que no corrió) es una respuesta válida', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ source: 'prototype', data: null })),
    )

    await expect(loadAnalytics('motor', 'prototype')).resolves.toEqual({ data: null, offline: false, saved: null })
  })

  test('si la API no responde usa los datos guardados y anota la consulta', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))),
    )
    const listener = vi.fn()
    const unsubscribe = subscribeConnection(listener)

    const result = await loadAnalytics('kpis', 'synthetic')

    expect(result).toEqual({ data: savedKpis.data, offline: true, saved: savedKpis.guardado })
    expect(getFallbacks()).toEqual([
      { key: 'kpis.synthetic', name: 'kpis', reason: 'no responde', guardado: savedKpis.guardado },
    ])
    expect(listener).toHaveBeenCalledTimes(1)
    unsubscribe()
  })

  test('una consulta lenta cae a los datos guardados con el motivo', async () => {
    const timeout = new DOMException('signal timed out', 'TimeoutError')
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Promise.reject(timeout)),
    )

    const result = await loadAnalytics('weekly', 'synthetic')

    expect(result.data).toEqual(savedWeekly.data)
    expect(getFallbacks()[0].reason).toBe('no respondió en 30 s')
  })

  test('un error HTTP también cae a los datos guardados', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ detail: 'boom' }, 500)),
    )

    const result = await loadAnalytics('suggestions', 'synthetic')

    expect(result).toEqual({ data: savedSuggestions.data, offline: true, saved: savedSuggestions.guardado })
    expect(getFallbacks()[0]).toMatchObject({ name: 'suggestions', reason: 'respondió 500' })
  })

  test('descarta una respuesta de otra fuente (nunca mezcla simulados con prototipo)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ source: 'prototype', data: [{ x: 1 }] })),
    )

    const result = await loadAnalytics('trends', 'synthetic')

    expect(result.offline).toBe(true)
    expect(result.data).not.toEqual([{ x: 1 }])
    expect(getFallbacks()[0].reason).toBe('respuesta no válida')
  })

  test('la fuente prototipo nunca cae a datos guardados: sin la API dice que no responde', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))),
    )

    await expect(loadAnalytics('offers', 'prototype')).rejects.toThrow(
      'La API no responde: el uso del MVP solo se ve con la base viva.',
    )
    expect(getFallbacks()).toEqual([])
  })

  test('una respuesta de otra fuente tampoco cae a datos guardados en el prototipo', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ source: 'synthetic', data: [{ x: 1 }] })),
    )

    await expect(loadAnalytics('trends', 'prototype')).rejects.toThrow('La API no responde')
  })

  test('lo guardado trae su origen y su fecha, y quedan en el aviso', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))),
    )

    const result = await loadAnalytics('offers', 'synthetic')

    expect(result.saved).toEqual(savedOffers.guardado)
    expect(result.saved.origen).toMatch(/\S/)
    expect(getFallbacks()[0]).toMatchObject({ key: 'offers.synthetic', guardado: savedOffers.guardado })
  })

  test('una petición vieja que falla tarde no deja «sin conexión» si ya hay otra en curso', async () => {
    let rejectOld
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(() => new Promise((_, reject) => (rejectOld = reject)))
      .mockImplementation(async () => jsonResponse({ source: 'synthetic', data: { usuarios_activos: 9 } }))
    vi.stubGlobal('fetch', fetchMock)

    const old = loadAnalytics('kpis', 'synthetic')
    refreshSource('synthetic')
    const fresh = await loadAnalytics('kpis', 'synthetic')
    rejectOld(new TypeError('Failed to fetch'))
    await old

    expect(fresh.offline).toBe(false)
    expect(getFallbacks()).toEqual([])
  })

  test('guarda en caché por métrica y fuente, y retryConnection la limpia', async () => {
    const fetchMock = vi.fn(async (url) => jsonResponse({ source: new URL(url).searchParams.get('source'), data: [] }))
    vi.stubGlobal('fetch', fetchMock)

    await loadAnalytics('trends', 'synthetic')
    await loadAnalytics('trends', 'synthetic')
    await loadAnalytics('trends', 'prototype')
    expect(fetchMock).toHaveBeenCalledTimes(2)

    retryConnection()
    await loadAnalytics('trends', 'synthetic')
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  test('refreshSource vuelve a pedir lo de esa fuente y deja en caché lo demás (sin repetir weekly)', async () => {
    const fetchMock = vi.fn(async (url) => jsonResponse({ source: new URL(url).searchParams.get('source'), data: [] }))
    vi.stubGlobal('fetch', fetchMock)

    await loadAnalytics('suggestions', 'prototype')
    await loadAnalytics('weekly', 'synthetic')
    refreshSource('prototype')
    await loadAnalytics('suggestions', 'prototype')
    await loadAnalytics('weekly', 'synthetic')

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      'http://localhost:8000/analytics/suggestions?source=prototype',
      'http://localhost:8000/analytics/weekly?source=synthetic',
      'http://localhost:8000/analytics/suggestions?source=prototype',
    ])
  })

  test('refreshSource olvida el aviso sin conexión de esa fuente y avisa', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))),
    )
    await loadAnalytics('suggestions', 'synthetic')
    await loadAnalytics('kpis', 'synthetic')
    const listener = vi.fn()
    const unsubscribe = subscribeConnection(listener)

    refreshSource('synthetic')

    expect(getFallbacks()).toEqual([])
    expect(listener).toHaveBeenCalledTimes(1)
    unsubscribe()
  })

  test('rechaza fuentes desconocidas', () => {
    expect(() => loadAnalytics('kpis', 'real')).toThrow('Fuente desconocida')
  })
})

describe('apiUrl', () => {
  test('el panel en desarrollo usa el host de la página', () => {
    expect(apiUrl({ PROD: false }, { hostname: '10.0.0.5' })).toBe('http://10.0.0.5:8000')
    expect(apiUrl({}, undefined)).toBe('http://localhost:8000')
  })

  test('en producción sin variable devuelve /api y con variable le quita la barra final', () => {
    expect(apiUrl({ PROD: true }, { hostname: 'demo.example.cl' })).toBe('/api')
    expect(apiUrl({ VITE_API_URL: 'https://api.example.cl/', PROD: true }, {})).toBe('https://api.example.cl')
    expect(apiUrl({ VITE_API_URL: '', PROD: true }, {})).toBe('/api')
  })
})
