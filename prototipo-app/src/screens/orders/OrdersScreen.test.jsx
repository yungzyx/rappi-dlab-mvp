import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { fixture, stubApi } from '../../test/api'
import { ToastProvider } from '../../components/Toast'
import { CartProvider, useCart } from '../../state/CartContext'
import { OrdersProvider, useOrders } from '../../state/OrdersContext'
import OrdersScreen from './OrdersScreen'

const events = vi.hoisted(() => ({ track: vi.fn(), flush: async () => {}, clear: () => {}, settled: async () => {} }))
vi.mock('../../state/EventsContext', async (importOriginal) => ({
  ...(await importOriginal()),
  useEvents: () => events,
}))

// Las líneas son las de `catalog-availability` (make contract): el café sigue a la venta en su tienda, el helado no
// se vende en el súper y el plato sigue en su restaurante.
const product = (entityType, entityId, extra) => ({
  id: `${entityType === 'menu_item' ? 'menu' : 'cat'}-${entityId}`,
  entityType,
  entityId,
  price: '$4.590',
  img: 'x.webp',
  ...extra,
})
const COFFEE = product('catalog_item', '91004', {
  name: 'Café molido',
  storeId: 9101,
  store: 'Súper',
  vertical: 'grocery',
  concept: 'cafe',
})
const ICE_CREAM = product('catalog_item', '93001', {
  name: 'Helado',
  storeId: 9101,
  store: 'Súper',
  vertical: 'grocery',
})
const DISH = product('menu_item', '98001', { name: 'Pizza', price: '$12.990', vertical: 'restaurants' })
const line = (p, qty = 1) => ({ name: p.name, img: p.img, price: p.price, qty, vertical: p.vertical, product: p })

const ORDER = {
  stores: ['Unimarc'],
  cartId: 'c-antes',
  items: [line(COFFEE, 2), line(ICE_CREAM), line(DISH)],
  total: 1000,
}

function Harness({ push, reset, order = ORDER }) {
  const orders = useOrders()
  const cart = useCart()
  return (
    <>
      <button type="button" onClick={() => orders.place(order)}>
        pedir
      </button>
      <button type="button" onClick={() => cart.add({ ...DISH, id: 'otro', entityId: '1' })}>
        llenar
      </button>
      <output data-testid="cart">
        {cart.items.map(({ product: p, qty }) => `${qty}×${p.name}@${p.price}`).join(',')}
      </output>
      <OrdersScreen back={() => {}} push={push} reset={reset} />
    </>
  )
}

const setup = (order) => {
  const push = vi.fn()
  const reset = vi.fn()
  render(
    <OrdersProvider>
      <CartProvider>
        <ToastProvider>
          <Harness push={push} reset={reset} order={order} />
        </ToastProvider>
      </CartProvider>
    </OrdersProvider>,
  )
  return { push, reset }
}

let api
beforeEach(() => {
  vi.useFakeTimers()
  events.track.mockClear()
  api = stubApi({ 'POST /catalog/availability': fixture('catalog-availability') })
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  localStorage.clear()
})

const deliver = () => act(() => vi.advanceTimersByTime(21_000))
const cartText = () => screen.getByTestId('cart').textContent

describe('OrdersScreen', () => {
  test('sin pedidos: estado vacío con botón al inicio', () => {
    const { reset } = setup()
    expect(screen.getByText('Todavía no tienes pedidos')).toBeTruthy()
    fireEvent.click(screen.getByText('Ir al inicio'))
    expect(reset).toHaveBeenCalled()
  })

  test('cada pedido muestra su día real, el paso de su vertical, "Por calificar" al entregar y abre su seguimiento', () => {
    const { push } = setup({ ...ORDER, items: [line(COFFEE)] })
    fireEvent.click(screen.getByText('pedir'))
    expect(screen.getByText('Unimarc')).toBeTruthy()
    expect(screen.getByText(/Hoy ·/)).toBeTruthy()
    expect(screen.getByText('Confirmado')).toBeTruthy()
    act(() => vi.advanceTimersByTime(4_000))
    expect(screen.getByText('En tienda')).toBeTruthy() // el súper: con shopper
    expect(screen.queryByText('Pídelo de nuevo')).toBeNull()
    act(() => vi.advanceTimersByTime(17_000))
    expect(screen.getByText('Por calificar')).toBeTruthy()
    fireEvent.click(screen.getByText('Unimarc'))
    expect(push).toHaveBeenCalledWith('tracking', { orderId: expect.stringMatching(/^order-/) })
  })

  test('un pedido cancelado dice "Cancelado" y no ofrece "Pídelo de nuevo" ni ayuda; uno entregado ofrece ayuda', () => {
    setup({ ...ORDER, items: [line(COFFEE)], cancelled: { reason: 'ya_no', stage: 'antes_de_tienda', fee: 0 } })
    fireEvent.click(screen.getByText('pedir'))
    expect(screen.getByText('Cancelado')).toBeTruthy()
    deliver()
    expect(screen.getByText('Cancelado')).toBeTruthy()
    expect(screen.queryByText('Pídelo de nuevo')).toBeNull()
    expect(screen.queryByText('Ayuda con este pedido')).toBeNull()

    cleanup()
    localStorage.clear()
    setup({ ...ORDER, items: [line(COFFEE)] })
    fireEvent.click(screen.getByText('pedir'))
    deliver()
    expect(screen.getByText('Ayuda con este pedido')).toBeTruthy()
  })

  test('el total es el del seguimiento: con el ajuste del sustituto, y cancelado solo su costo', () => {
    const substituted = {
      index: 0,
      choice: 'sustituto',
      product: { name: 'Café en grano', price: '$3.190' },
      delta: -2_800,
    }
    setup({ ...ORDER, items: [line(COFFEE)], total: 14_440, liveChange: substituted })
    fireEvent.click(screen.getByText('pedir'))
    expect(screen.getByText(/Hoy · \$11\.640/)).toBeTruthy()

    cleanup()
    localStorage.clear()
    setup({
      ...ORDER,
      items: [line(COFFEE)],
      total: 14_440,
      cancelled: { reason: 'ya_no', stage: 'en_tienda', fee: 990 },
    })
    fireEvent.click(screen.getByText('pedir'))
    expect(screen.getByText(/Hoy · \$990/)).toBeTruthy()
  })

  test('programado: "Programado · hoy HH:00–HH:00" hasta su franja', () => {
    const slot = new Date(Date.now() + 3 * 3_600_000).setMinutes(0, 0, 0)
    setup({ ...ORDER, items: [line(COFFEE)], scheduledFor: slot })
    fireEvent.click(screen.getByText('pedir'))
    expect(screen.getByText(/^Programado · (hoy|mañana) \d\d:00–\d\d:00$/)).toBeTruthy()
  })

  test('"Pídelo de nuevo" arma el carro con lo que sigue disponible, al precio de hoy, y marca lo que no', async () => {
    setup()
    fireEvent.click(screen.getByText('pedir'))
    deliver()
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Pídelo de nuevo' })))
    const sheet = screen.getByRole('dialog', { name: 'Pídelo de nuevo' })
    expect(within(sheet).getByText('No disponible').closest('li').textContent).toContain('Helado')
    const [request] = api.mock.calls.filter(([url]) => url.endsWith('/catalog/availability'))
    expect(JSON.parse(request[1].body).lines).toEqual([
      { entity_type: 'catalog_item', entity_id: '91004', store_id: 9101 },
      { entity_type: 'catalog_item', entity_id: '93001', store_id: 9101 },
      { entity_type: 'menu_item', entity_id: '98001' },
    ])

    fireEvent.click(within(sheet).getByRole('button', { name: /^Agregar al carro/ }))

    expect(cartText()).toBe('2×Café molido@$3.990,1×Pizza@$12.990')
    expect(events.track).toHaveBeenCalledWith('reorder', {
      surface: 'orders',
      origin: 'pidelo-de-nuevo',
      position: 0,
      cart_id: expect.any(String),
      value: 2 * 3990 + 12990,
      payload: { available: 2, unavailable: 1 },
    })
    expect(events.track).toHaveBeenCalledWith(
      'cart_add',
      expect.objectContaining({ entity_id: '91004', origin: 'pidelo-de-nuevo', surface: 'orders', position: 0 }),
    )
  })

  test('con productos en el carro pregunta si mantenerlos', async () => {
    setup()
    fireEvent.click(screen.getByText('pedir'))
    fireEvent.click(screen.getByText('llenar'))
    deliver()
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Pídelo de nuevo' })))
    expect(screen.getByText('Tu carro ya tiene productos. ¿Los mantienes?')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Vaciar el carro y agregar' }))

    expect(cartText()).toBe('2×Café molido@$3.990,1×Pizza@$12.990')
    expect(events.track).toHaveBeenCalledWith('cart_remove', expect.objectContaining({ entity_id: '1' }))
    expect(events.track).toHaveBeenCalledWith(
      'reorder',
      expect.objectContaining({ payload: { available: 2, unavailable: 1, kept: false } }),
    )
  })

  test('un pedido guardado sin sus productos (de antes) no ofrece "Pídelo de nuevo"', () => {
    setup({ stores: ['Unimarc'], items: [{ name: 'Palta', img: 'p.webp', price: '$1.000', qty: 1 }], total: 1000 })
    fireEvent.click(screen.getByText('pedir'))
    deliver()
    expect(screen.queryByRole('button', { name: 'Pídelo de nuevo' })).toBeNull()
  })
})
