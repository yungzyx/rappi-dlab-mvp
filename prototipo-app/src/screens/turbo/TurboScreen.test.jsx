import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, test, vi } from 'vitest'
import { fixture, stubApi } from '../../test/api'
import ProductSheet from '../../components/ProductSheet'
import { ToastProvider } from '../../components/Toast'
import { AssistantProvider } from '../../state/AssistantContext'
import { CartProvider, useCart } from '../../state/CartContext'
import { DemoProvider } from '../../state/DemoContext'
import { FavoritesProvider } from '../../state/FavoritesContext'
import { ProductSheetProvider } from '../../state/ProductSheetContext'
import { ProfileProvider } from '../../state/ProfileContext'
import TurboScreen from './TurboScreen'

const events = vi.hoisted(() => ({ track: vi.fn(), flush: async () => {}, clear: () => {}, settled: async () => {} }))
vi.mock('../../state/EventsContext', async (importOriginal) => ({
  ...(await importOriginal()),
  useEvents: () => events,
}))

beforeAll(() => {
  Element.prototype.scrollIntoView = () => {} // jsdom no lo implementa
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  localStorage.clear()
})

function AddToCart({ product }) {
  const cart = useCart()
  return (
    <button type="button" onClick={() => cart.add(product)}>
      sumar
    </button>
  )
}

function Providers({ children }) {
  return (
    <DemoProvider>
      <ProfileProvider>
        <AssistantProvider>
          <CartProvider>
            <FavoritesProvider>
              <ToastProvider>
                <ProductSheetProvider>
                  {children}
                  <ProductSheet />
                </ProductSheetProvider>
              </ToastProvider>
            </FavoritesProvider>
          </CartProvider>
        </AssistantProvider>
      </ProfileProvider>
    </DemoProvider>
  )
}

const TURBO = { id: 9301, name: 'Tienda turbo de prueba Centro', vertical: 'turbo' }

/** Las dos tiendas Turbo de la API: la primera es la de más productos. */
const turboStores = () => {
  const { stores } = fixture('catalog-vertical-stores')
  return {
    vertical: 'turbo',
    stores: [
      { ...stores[0], ...TURBO },
      { ...stores[1], id: 9302, name: 'Tienda turbo de prueba Sur', vertical: 'turbo' },
    ],
  }
}

/** Un producto de ejemplo, como si lo vendiera la tienda Turbo. */
const sold = (product) => ({ ...product, store: TURBO.name, store_id: TURBO.id, vertical: 'turbo' })

/** La tienda Turbo: 30 productos en su primer pasillo (de a 24 por página) y uno en «Bebidas». */
function turboShop(req) {
  const aisle = req.query.get('aisle')
  const reply = fixture(req.query.get('page') === '2' ? 'catalog-store-page-2' : 'catalog-store')
  reply.store = { ...reply.store, ...TURBO }
  reply.products = reply.products.map(sold)
  if (aisle === '300') {
    const cola = sold(fixture('catalog-deals').find((deal) => deal.name.startsWith('Gaseosa')))
    return { ...reply, aisle: reply.aisles[2], products: [cola], has_more: false }
  }
  return reply
}

/** Las bajas de precio de la vertical que se pida (código del backend). */
const dealsOf = (req) => fixture('catalog-deals').filter((deal) => deal.vertical === req.query.get('vertical'))

const stubTurbo = (extra = {}) =>
  stubApi({
    '/catalog/verticals/turbo/stores': turboStores(),
    '/catalog/stores/9301': turboShop,
    '/catalog/deals': dealsOf,
    ...extra,
  })

const renderTurbo = (extra = null) => {
  const push = vi.fn()
  render(
    <>
      <TurboScreen back={vi.fn()} push={push} />
      {extra}
    </>,
    { wrapper: Providers },
  )
  return push
}
const names = () => [...document.querySelectorAll('.turbo-grid .product-name')].map((node) => node.textContent)
const tabNames = () => screen.getAllByRole('tab').map((tab) => tab.textContent)
const requests = (fetchMock) =>
  fetchMock.mock.calls.map(([url]) => {
    const { pathname, searchParams } = new URL(url)
    return { path: pathname, query: Object.fromEntries(searchParams) }
  })

describe('Turbo con el catálogo real', () => {
  test('Turbo usa los pasillos de la tienda Turbo como pestañas', async () => {
    const fetchMock = stubTurbo()
    renderTurbo()

    await waitFor(() => expect(names()).toHaveLength(24))
    expect(tabNames()).toEqual(['Despensa', 'Snacks y Dulces', 'Bebidas', 'Cuidado del bebé', 'Cervezas'])
    expect(screen.getByRole('tab', { name: 'Despensa' }).getAttribute('aria-selected')).toBe('true')
    expect(screen.getByRole('heading', { name: 'Despensa' })).toBeTruthy()
    // La tienda es la primera de la vertical (la de más productos), no la segunda.
    expect(requests(fetchMock).map(({ path }) => path)).toEqual([
      '/catalog/verticals/turbo/stores',
      '/catalog/stores/9301',
    ])

    fireEvent.click(screen.getByRole('tab', { name: 'Bebidas' }))
    await waitFor(() => expect(names()).toEqual(['Gaseosa cola 1,5 L (prueba)']))
    expect(screen.getByRole('tab', { name: 'Bebidas' }).getAttribute('aria-selected')).toBe('true')
    expect(screen.getByRole('tab', { name: 'Despensa' }).getAttribute('aria-selected')).toBe('false')
    expect(requests(fetchMock).at(-1)).toEqual({ path: '/catalog/stores/9301', query: { aisle: '300' } })
  })

  test('el tiempo de entrega es el de la tienda Turbo', async () => {
    stubTurbo()
    renderTurbo()
    await waitFor(() => expect(names()).toHaveLength(24))
    expect(document.querySelector('.turbo-eta strong').textContent).toBe('25 min')
  })

  test('Ver más trae la página siguiente del pasillo sin repetir productos', async () => {
    const fetchMock = stubTurbo()
    renderTurbo()
    await waitFor(() => expect(names()).toHaveLength(24))

    fireEvent.click(screen.getByRole('button', { name: 'Ver más' }))
    await waitFor(() => expect(names()).toHaveLength(30))
    expect(new Set(names()).size).toBe(30)
    expect(requests(fetchMock).at(-1)).toEqual({ path: '/catalog/stores/9301', query: { aisle: '100', page: '2' } })
    expect(screen.queryByRole('button', { name: 'Ver más' })).toBeNull() // era la última página
  })

  test('Ofertas muestra las bajas de precio de Turbo y Categorías lista los pasillos', async () => {
    const fetchMock = stubTurbo()
    renderTurbo()
    await waitFor(() => expect(names()).toHaveLength(24))

    fireEvent.click(screen.getByRole('button', { name: 'Ofertas' }))
    await waitFor(() => expect(names()).toEqual(['Helado de vainilla 1 L (prueba)']))
    expect(requests(fetchMock).find(({ path }) => path === '/catalog/deals').query).toEqual({ vertical: 'turbo' })
    expect(screen.queryByText('Esta sección no está en el prototipo')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Categorías' }))
    expect(screen.getByRole('button', { name: /^Despensa/ }).textContent).toContain('30 productos')
    expect(screen.getByRole('button', { name: /^Cervezas/ }).textContent).toContain('1 producto') // en singular
    expect(screen.getByRole('button', { name: /^Cervezas/ }).textContent).not.toContain('productos')
    fireEvent.click(screen.getByRole('button', { name: /^Bebidas/ }))
    await waitFor(() => expect(names()).toEqual(['Gaseosa cola 1,5 L (prueba)']))
    expect(screen.getByRole('tab', { name: 'Bebidas' }).getAttribute('aria-selected')).toBe('true')
  })

  test('Ofertas sin bajas dice que no hay, y si la API cae avisa con Reintentar', async () => {
    let online = false
    stubTurbo({ '/catalog/deals': () => (online ? [] : 'offline') })
    renderTurbo()
    await waitFor(() => expect(names()).toHaveLength(24))

    fireEvent.click(screen.getByRole('button', { name: 'Ofertas' }))
    const notice = (await screen.findByText('Sin conexión')).closest('.offline-notice')
    online = true
    fireEvent.click(within(notice).getByRole('button', { name: 'Reintentar' }))
    expect(await screen.findByText('Todavía no hay ofertas en Turbo.')).toBeTruthy()
  })

  test('la tarifa de servicio descuenta lo que hay en el carrito', async () => {
    stubTurbo()
    const product = { id: 'x', name: 'Caja', price: '$20.000', vertical: 'grocery', store: 'Unimarc' }
    renderTurbo(<AddToCart product={product} />)
    await waitFor(() => expect(names()).toHaveLength(24))
    expect(screen.getByText('$29.900')).toBeTruthy()
    fireEvent.click(screen.getByText('sumar'))
    expect(screen.getByText('$9.900')).toBeTruthy()
    fireEvent.click(screen.getByText('sumar'))
    expect(screen.getByText('Descuento activado.')).toBeTruthy()
  })

  test('las promos ya no apuntan a pestañas que no existen: avisan que no están en el prototipo', async () => {
    stubTurbo()
    renderTurbo()
    await waitFor(() => expect(names()).toHaveLength(24))

    fireEvent.click(screen.getByRole('button', { name: 'Saludable: frescos' }))
    expect(await screen.findByText('Esta sección no está en el prototipo')).toBeTruthy()
    expect(screen.getByRole('tab', { name: 'Despensa' }).getAttribute('aria-selected')).toBe('true')
  })

  test('el «Ver tienda» de un producto abre la tienda Turbo por id', async () => {
    stubTurbo()
    const push = renderTurbo()
    await waitFor(() => expect(names()).toHaveLength(24))

    fireEvent.click(screen.getByText('Aceite de canola 1 L (prueba)'))
    fireEvent.click(screen.getByRole('button', { name: /Ver tienda/ }))
    expect(push).toHaveBeenCalledWith('store', {
      store: { id: 9301, name: 'Tienda turbo de prueba Centro', vertical: 'turbo' },
      item: expect.objectContaining({ entityId: '91111' }),
    })
  })

  test('sin tiendas Turbo en el catálogo la pantalla lo dice y no se rompe', async () => {
    stubTurbo({ '/catalog/verticals/turbo/stores': { vertical: 'turbo', stores: [] } })
    renderTurbo()
    expect(await screen.findByText('Todavía no hay productos de Turbo en el catálogo.')).toBeTruthy()
    expect(screen.queryAllByRole('tab')).toEqual([])
    expect(screen.getByText('Busca en Turbo')).toBeTruthy()
  })

  test('sin conexión avisa dentro de la pantalla, y Reintentar la carga', async () => {
    let online = false
    stubTurbo({ '/catalog/verticals/turbo/stores': () => (online ? turboStores() : 'offline') })
    renderTurbo()

    const notice = (await screen.findByText('Sin conexión')).closest('.offline-notice')
    expect(screen.getByText('Busca en Turbo')).toBeTruthy() // el resto de la pantalla sigue
    online = true
    fireEvent.click(within(notice).getByRole('button', { name: 'Reintentar' }))
    await waitFor(() => expect(names()).toHaveLength(24))
    expect(screen.queryByText('Sin conexión')).toBeNull()
  })
})
