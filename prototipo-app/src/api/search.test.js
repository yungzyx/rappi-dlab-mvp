import { afterEach, describe, expect, test, vi } from 'vitest'
import { ApiError } from './client'
import { searchAll } from './search'
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
