import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { ToastProvider } from '../components/Toast'
import { fixture, stubApi } from '../test/api'
import { useShopAisles } from './useShopAisles'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

/** La tienda 9101: 30 productos en su primer pasillo (de a 24 por página) y uno en «Bebidas». */
function shop(req) {
  if (req.query.get('aisle') === '300') {
    const reply = fixture('catalog-store')
    const cola = fixture('catalog-deals').find((deal) => deal.name.startsWith('Gaseosa'))
    return { ...reply, aisle: reply.aisles[2], products: [cola], has_more: false }
  }
  return fixture(req.query.get('page') === '2' ? 'catalog-store-page-2' : 'catalog-store')
}

const hook = (shopId) => renderHook(() => useShopAisles(shopId), { wrapper: ToastProvider })
const requests = (fetchMock) =>
  fetchMock.mock.calls.map(([url]) => {
    const { pathname, searchParams } = new URL(url)
    return [pathname, Object.fromEntries(searchParams)]
  })

describe('useShopAisles', () => {
  test('sin tienda no pide nada', async () => {
    const fetchMock = stubApi({})
    const { result } = hook(null)
    await act(async () => {})
    expect(fetchMock).not.toHaveBeenCalled()
    expect(result.current).toMatchObject({
      data: null,
      error: null,
      aisles: [],
      aisle: null,
      products: [],
      hasMore: false,
    })
  })

  test('trae los pasillos y la primera página del primero', async () => {
    stubApi({ '/catalog/stores/9101': shop })
    const { result } = hook(9101)
    await waitFor(() => expect(result.current.products).toHaveLength(24))
    expect(result.current.aisles.map((aisle) => aisle.name)).toEqual([
      'Despensa',
      'Snacks y Dulces',
      'Bebidas',
      'Cuidado del bebé',
      'Cervezas',
    ])
    expect(result.current.aisle).toBe(100) // el primero, sin que nadie lo elija
    expect(result.current.hasMore).toBe(true)
  })

  test('loadMore suma la página siguiente sin repetir ni saltarse productos', async () => {
    const fetchMock = stubApi({ '/catalog/stores/9101': shop })
    const { result } = hook(9101)
    await waitFor(() => expect(result.current.products).toHaveLength(24))

    await act(() => result.current.loadMore())
    expect(result.current.products).toHaveLength(30)
    expect(new Set(result.current.products.map((product) => product.id)).size).toBe(30)
    expect(result.current.products.slice(24).map((product) => product.name)).toEqual(
      fixture('catalog-store-page-2').products.map((product) => product.name),
    )
    expect(result.current.hasMore).toBe(false) // era la última página
    expect(requests(fetchMock)).toEqual([
      ['/catalog/stores/9101', {}],
      ['/catalog/stores/9101', { aisle: '100', page: '2' }],
    ])
  })

  test('un producto que la página siguiente repite no se agrega dos veces', async () => {
    stubApi({
      '/catalog/stores/9101': (req) => {
        const reply = shop(req)
        if (req.query.get('page') !== '2') return reply
        return { ...reply, products: [fixture('catalog-store').products[0], ...reply.products] }
      },
    })
    const { result } = hook(9101)
    await waitFor(() => expect(result.current.products).toHaveLength(24))
    await act(() => result.current.loadMore())
    expect(result.current.products).toHaveLength(30)
  })

  test('elegir otro pasillo trae sus productos y deja los pasillos a la vista mientras llegan', async () => {
    const fetchMock = stubApi({ '/catalog/stores/9101': shop })
    const { result } = hook(9101)
    await waitFor(() => expect(result.current.products).toHaveLength(24))
    await act(() => result.current.loadMore())

    act(() => result.current.setAisle(300))
    expect(result.current.aisle).toBe(300)
    expect(result.current.data).toBeNull() // cargando: nada de lo del pasillo anterior
    expect(result.current.aisles).toHaveLength(5)
    await waitFor(() =>
      expect(result.current.products.map((product) => product.name)).toEqual(['Gaseosa cola 1,5 L (prueba)']),
    )
    expect(result.current.hasMore).toBe(false)
    expect(requests(fetchMock).at(-1)).toEqual(['/catalog/stores/9101', { aisle: '300' }])
  })

  test('si falla loadMore avisa con un toast y se queda lo que ya había', async () => {
    stubApi({ '/catalog/stores/9101': (req) => (req.query.get('page') === '2' ? 'offline' : shop(req)) })
    const { result } = hook(9101)
    await waitFor(() => expect(result.current.products).toHaveLength(24))

    await act(() => result.current.loadMore())
    expect(document.querySelector('.toast').textContent).toBe('No se pudo cargar más productos')
    expect(result.current.products).toHaveLength(24)
    expect(result.current.hasMore).toBe(true)
    expect(result.current.loadingMore).toBe(false)
  })

  test('una tienda que no está es un 404, y un fallo de red no lo es', async () => {
    stubApi({})
    const missing = hook(1)
    await waitFor(() => expect(missing.result.current.error?.status).toBe(404))

    stubApi({ '/catalog/stores/9101': 'offline' })
    const offline = hook(9101)
    await waitFor(() => expect(offline.result.current.error?.kind).toBe('offline'))
    expect(offline.result.current.error.status).toBeUndefined()
  })
})
