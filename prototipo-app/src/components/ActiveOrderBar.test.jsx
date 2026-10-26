import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { CartProvider } from '../state/CartContext'
import { OrdersProvider, useOrders } from '../state/OrdersContext'
import ActiveOrderBar from './ActiveOrderBar'

const ORDER = {
  stores: ['Pizzería'],
  items: [{ name: 'Pizza', img: 'p.webp', price: '$7.990', qty: 1, vertical: 'restaurants' }],
  total: 7990,
}

function Place() {
  const orders = useOrders()
  return (
    <>
      <button type="button" onClick={() => orders.place(ORDER)}>
        pedir
      </button>
      <button type="button" onClick={() => orders.placeMany([ORDER, { ...ORDER, stores: ['Súper'] }])}>
        pedir en dos tiendas
      </button>
      <button type="button" onClick={() => orders.cancel(orders.orders[0].id, { reason: 'ya_no' })}>
        cancelar
      </button>
      <button type="button" onClick={() => orders.hold(orders.orders[0].id, 'cambio')}>
        agotar
      </button>
    </>
  )
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  localStorage.clear()
})

test('«Pedido en curso» con el paso y lo que falta; abre el seguimiento y se va al entregar', () => {
  const push = vi.fn()
  render(
    <OrdersProvider>
      <CartProvider>
        <Place />
        <ActiveOrderBar push={push} />
      </CartProvider>
    </OrdersProvider>,
  )
  expect(screen.queryByText('Pedido en curso')).toBeNull()
  fireEvent.click(screen.getByText('pedir'))
  expect(screen.getByText('Pedido en curso')).toBeTruthy()
  expect(screen.getByText('Confirmado · 22 min')).toBeTruthy()
  act(() => vi.advanceTimersByTime(7_000))
  expect(screen.getByText('Buscando un Rappi · 22 min')).toBeTruthy()
  fireEvent.click(screen.getByText('Pedido en curso'))
  expect(push).toHaveBeenCalledWith('tracking', { orderId: expect.stringMatching(/^order-/) })
  act(() => vi.advanceTimersByTime(14_000))
  expect(screen.queryByText('Pedido en curso')).toBeNull()
})

test('una compra en dos tiendas son dos pedidos en curso; uno cancelado ya no está en curso', () => {
  render(
    <OrdersProvider>
      <CartProvider>
        <Place />
        <ActiveOrderBar push={() => {}} />
      </CartProvider>
    </OrdersProvider>,
  )
  fireEvent.click(screen.getByText('pedir en dos tiendas'))
  expect(screen.getByText('2 pedidos en curso')).toBeTruthy()
  fireEvent.click(screen.getByText('cancelar'))
  expect(screen.getByText('Pedido en curso')).toBeTruthy()
})

test('con un producto agotado esperando respuesta, la barra dice que el pedido la espera', () => {
  render(
    <OrdersProvider>
      <CartProvider>
        <Place />
        <ActiveOrderBar push={() => {}} />
      </CartProvider>
    </OrdersProvider>,
  )
  fireEvent.click(screen.getByText('pedir'))
  fireEvent.click(screen.getByText('agotar'))
  expect(screen.getByText('Tus productos te necesitan')).toBeTruthy()
})
