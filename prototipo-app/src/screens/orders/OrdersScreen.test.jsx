import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { OrdersProvider, useOrders } from '../../state/OrdersContext'
import OrdersScreen from './OrdersScreen'

const ORDER = {
  stores: ['Unimarc'],
  items: [{ name: 'Palta', img: 'palta.webp', price: '$1.000', qty: 1 }],
  total: 1000,
}

function Harness({ push, reset }) {
  const orders = useOrders()
  return (
    <>
      <button type="button" onClick={() => orders.place(ORDER)}>
        pedir
      </button>
      <OrdersScreen back={() => {}} push={push} reset={reset} />
    </>
  )
}

const setup = () => {
  const push = vi.fn()
  const reset = vi.fn()
  render(<Harness push={push} reset={reset} />, { wrapper: OrdersProvider })
  return { push, reset }
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  localStorage.clear()
})

describe('OrdersScreen', () => {
  test('sin pedidos: estado vacío con botón al inicio', () => {
    const { reset } = setup()
    expect(screen.getByText('Todavía no tienes pedidos')).toBeTruthy()
    fireEvent.click(screen.getByText('Ir al inicio'))
    expect(reset).toHaveBeenCalled()
  })

  test('cada pedido muestra su día real, pasa de «En camino» a «Entregado» y abre su seguimiento', () => {
    const { push } = setup()
    fireEvent.click(screen.getByText('pedir'))
    expect(screen.getByText('Unimarc')).toBeTruthy()
    expect(screen.getByText(/Hoy ·/)).toBeTruthy()
    expect(screen.getByText('En camino')).toBeTruthy()
    act(() => vi.advanceTimersByTime(21_000))
    expect(screen.getByText('Entregado')).toBeTruthy()
    fireEvent.click(screen.getByText('Unimarc'))
    expect(push).toHaveBeenCalledWith('tracking', { orderId: expect.stringMatching(/^order-/) })
  })
})
