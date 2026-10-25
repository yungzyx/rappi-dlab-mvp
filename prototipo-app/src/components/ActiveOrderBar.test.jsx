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
    <button type="button" onClick={() => orders.place(ORDER)}>
      pedir
    </button>
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
