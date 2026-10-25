import { afterEach, describe, expect, test, vi } from 'vitest'
import { ApiError } from './client'
import { searchAll, searchSuggestions } from './search'
import { fixture, stubApi } from '../test/api'

afterEach(() => vi.unstubAllGlobals())

describe('searchAll', () => {
  test('agrupa por vertical con los nombres del prototipo y productos convertidos', async () => {
    const calls = stubApi({ '/search': fixture('search-grouped') })
    const result = await searchAll('cerveza', { current: 'grocery', limit: 4 })

    expect(result.unmet).toBe(false)
    expect(result.query).toBe('cerveza')
    expect(result.groups.map((g) => [g.vertical, g.backendVertical])).toEqual([
      ['liquor', 'licores'],
      ['express', 'conveniencia'],
      ['grocery', 'supermercado'],
    ])
    expect(result.groups[0].products[0]).toMatchObject({
      id: 'cat-94001',
      vertical: 'liquor',
      backendVertical: 'licores',
      storeId: 9402,
      entityType: 'catalog_item',
      entityId: '94001',
    })
    const url = new URL(calls.mock.calls[0][0])
    expect(Object.fromEntries(url.searchParams)).toEqual({ q: 'cerveza', current: 'grocery', limit: '4' })
  })

  test('sin coincidencias devuelve unmet con su motivo y ningún grupo', async () => {
    stubApi({ '/search': fixture('search-grouped-unmet') })
    const result = await searchAll('xyzzy')
    expect(result.groups).toEqual([])
    expect(result.unmet).toBe(true)
    expect(result.unmetReason).toMatch(/sin coincidencia/)
  })

  test('si la API corrigió un error de tipeo dice qué buscó; con exact pide buscar tal cual', async () => {
    const calls = stubApi({
      '/search': (req) =>
        req.query.get('correct') === 'false' ? fixture('search-grouped-unmet') : fixture('search-grouped-corrected'),
    })
    const corrected = await searchAll('cervezaaaa')
    expect(corrected.correctedQuery).toBe('cerveza')
    expect(corrected.groups.length).toBeGreaterThan(0)
    expect(new URL(calls.mock.calls[0][0]).searchParams.has('correct')).toBe(false)

    const exact = await searchAll('cervezaaaa', { exact: true })
    expect(new URL(calls.mock.calls[1][0]).searchParams.get('correct')).toBe('false')
    expect(exact.correctedQuery).toBeNull()
    expect(exact.unmet).toBe(true)
  })

  test('con vertical busca solo ahí y devuelve un solo grupo', async () => {
    const calls = stubApi({
      '/search': (req) =>
        req.query.get('vertical')
          ? {
              vertical: 'licores',
              products: fixture('search-grouped').groups[0].products,
              unmet: false,
              unmet_reason: null,
            }
          : fixture('search-grouped'),
    })
    const result = await searchAll('cerveza', { vertical: 'liquor' })
    expect(new URL(calls.mock.calls[0][0]).searchParams.get('vertical')).toBe('liquor')
    expect(result.groups).toHaveLength(1)
    expect(result.groups[0]).toMatchObject({ vertical: 'liquor', backendVertical: 'licores' })
    expect(result.groups[0].products).toHaveLength(2)
  })

  test('sin API lanza un ApiError', async () => {
    stubApi({ '/search': 'offline' })
    await expect(searchAll('cerveza')).rejects.toBeInstanceOf(ApiError)
  })
})

describe('tiendas, restaurantes y lo de antes de escribir', () => {
  test('las tiendas que se llaman así vienen como tarjetas con su lugar, y la búsqueda no queda sin resultado', async () => {
    stubApi({ '/search': fixture('search-grouped-places') })
    const result = await searchAll('chocolateria de prueba')
    expect(result.unmet).toBe(false)
    expect(result.places.stores.map((s) => [s.name, s.placement.origin])).toEqual([
      ['Chocolatería de prueba Centro', 'resultados-tiendas'],
      ['Chocolatería de prueba Oriente', 'resultados-tiendas'],
    ])
    expect(result.whimAllowed).toBe(false)
  })

  test('sin resultados, la API dice si se puede ofrecer «Lo que sea»', async () => {
    stubApi({ '/search': fixture('search-grouped-unmet') })
    expect((await searchAll('xyzzy')).whimAllowed).toBe(true)
  })

  test('searchSuggestions: recientes y lo más buscado con su población', async () => {
    stubApi({ 'GET /profile/*': fixture('profile-busquedas') })
    expect(await searchSuggestions('u-contrato')).toEqual({
      recent: ['pizza'],
      top: [],
      population: 'synthetic',
      requestId: 'contrato-profile-busquedas',
    })
  })
})
