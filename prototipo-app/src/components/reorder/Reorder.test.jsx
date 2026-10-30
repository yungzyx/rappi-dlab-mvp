import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { fixture, stubApi } from '../../test/api'
import { reorderPlan } from '../../api/reorder'
import { CartProvider } from '../../state/CartContext'
import { OrdersProvider, useOrders } from '../../state/OrdersContext'
import { ToastProvider } from '../Toast'
import { ReorderCarousel, ReorderHomeRow, boughtAt } from './Reorder'

const product = (entityId, extra = {}) => ({
  id: `cat-${entityId}`,
  entityType: 'catalog_item',
  entityId,
  name: `Producto ${entityId}`,
  price: '$4.590',
  before: '$5.000',
  storeId: 9101,
  vertical: 'grocery',
  ...extra,
})
const COFFEE = product('91004', { name: 'Café molido' })
const ICE_CREAM = product('93001', { name: 'Helado' })
const line = (p, qty = 1) => ({ name: p.name, img: 'x.webp', price: p.price, qty, vertical: p.vertical, product: p })
const ORDER = { stores: ['Súper de prueba'], cartId: 'c-1', items: [line(COFFEE, 2), line(ICE_CREAM)], total: 9000 }

function Place({ order = ORDER }) {
  const orders = useOrders()
  return (
    <button type="button" onClick={() => orders.place(order)}>
      pedir
    </button>
  )
}

const renderWith = (children) =>
  render(
    <OrdersProvider>
      <CartProvider>
        <ToastProvider>
          <Place />
          {children}
        </ToastProvider>
      </CartProvider>
    </OrdersProvider>,
  )

beforeEach(() => {
  vi.useFakeTimers()
  // Las dos primeras líneas de `catalog-availability`: el café sigue a la venta en el súper y el helado no.
  stubApi({
    'POST /catalog/availability': (req) => ({
      lines: fixture('catalog-availability').lines.slice(0, req.body.lines.length),
    }),
  })
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('reorderPlan', () => {
  test('lo disponible lleva el precio de hoy (sin el "antes" de esa vez) y su lugar; lo demás queda aparte', () => {
    const lines = [line(COFFEE, 2), line(ICE_CREAM)]
    const plan = reorderPlan(lines, fixture('catalog-availability').lines, { surface: 'orders' })
    expect(plan.available).toEqual([
      {
        product: {
          ...COFFEE,
          price: '$3.990',
          before: undefined,
          discount: undefined,
          placement: { surface: 'orders', origin: 'pidelo-de-nuevo', position: 0 },
        },
        qty: 2,
      },
    ])
    expect(plan.unavailable).toEqual([{ product: ICE_CREAM, qty: 1 }])
  })
})

describe('carrusel de la tienda', () => {
  test('boughtAt junta lo comprado en esa tienda, una vez cada producto', () => {
    const other = { ...ORDER, items: [line(product('1', { storeId: 1 })), line(COFFEE)] }
    expect(boughtAt([ORDER, other], 9101).map((l) => l.product.entityId)).toEqual(['91004', '93001'])
    expect(boughtAt([ORDER], 1)).toEqual([])
  })

  test('muestra lo que ya compró ahí y sigue a la venta, con el precio de hoy', async () => {
    renderWith(<ReorderCarousel storeId={9101} />)
    expect(screen.queryByRole('region', { name: 'Pídelo de nuevo' })).toBeNull()
    await act(async () => screen.getByText('pedir').click())
    const carousel = screen.getByRole('region', { name: 'Pídelo de nuevo' })
    expect(carousel.textContent).toContain('Café molido')
    expect(carousel.textContent).toContain('$3.990')
    expect(carousel.textContent).not.toContain('Helado') // ya no se vende en esa tienda
  })

  test('en otra tienda no aparece', async () => {
    renderWith(<ReorderCarousel storeId={1} />)
    await act(async () => screen.getByText('pedir').click())
    expect(screen.queryByRole('region', { name: 'Pídelo de nuevo' })).toBeNull()
  })
})

describe('Home de "Rappi hoy"', () => {
  test('los pedidos entregados traen "Pídelo de nuevo"; uno en curso todavía no', async () => {
    renderWith(<ReorderHomeRow />)
    await act(async () => screen.getByText('pedir').click())
    expect(screen.queryByRole('region', { name: 'Pídelo de nuevo' })).toBeNull()
    await act(() => vi.advanceTimersByTimeAsync(22_000))
    const row = screen.getByRole('region', { name: 'Pídelo de nuevo' })
    expect(row.textContent).toContain('Súper de prueba')
    expect(row.textContent).toContain('3 productos · $9.000')
    expect(screen.getByRole('button', { name: 'Pídelo de nuevo' })).toBeTruthy()
  })
})
