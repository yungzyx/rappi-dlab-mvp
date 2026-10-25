import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useEffect } from 'react'
import { afterEach, expect, test, vi } from 'vitest'
import { toPrototypeProduct } from '../api/client'
import { fixture } from '../test/api'
import { AssistantProvider } from '../state/AssistantContext'
import { CartProvider, useCart } from '../state/CartContext'
import { DemoProvider } from '../state/DemoContext'
import { ProfileProvider } from '../state/ProfileContext'
import CartBar from './CartBar'

const events = vi.hoisted(() => ({ track: vi.fn(), flush: async () => {}, clear: () => {}, settled: async () => {} }))
vi.mock('../state/EventsContext', async (importOriginal) => ({ ...(await importOriginal()), useEvents: () => events }))
// /catalog/terms: la compra mínima que trae el catálogo de cada tienda (sin entrada, el supuesto de su vertical).
const terms = vi.hoisted(() => ({ byStore: {} }))
vi.mock('../api/catalog', async (importOriginal) => ({
  ...(await importOriginal()),
  storeTerms: async (ids) => new Map(ids.map((id) => [id, terms.byStore[id] ?? null])),
}))

function Seed({ products }) {
  const cart = useCart()
  useEffect(() => products.forEach((product) => cart.add(product)), []) // eslint-disable-line react-hooks/exhaustive-deps
  return null
}

afterEach(() => {
  cleanup()
  events.track.mockClear()
  localStorage.clear()
})

test('vaciar el carro lo registra (una salida por línea con sus unidades): si no, el panel lo cuenta como abandono', () => {
  const [beer, other] = fixture('catalog-store').products.slice(0, 2).map(toPrototypeProduct)
  render(
    <DemoProvider>
      <ProfileProvider>
        <AssistantProvider>
          <CartProvider>
            <Seed products={[beer, beer, other]} />
            <CartBar push={() => {}} />
          </CartProvider>
        </AssistantProvider>
      </ProfileProvider>
    </DemoProvider>,
  )
  fireEvent.click(screen.getByText('Ver carro'))
  fireEvent.click(screen.getByText('Vaciar carro'))

  const removes = events.track.mock.calls.filter(([type]) => type === 'cart_remove').map(([, fields]) => fields)
  expect(removes.map((r) => r.payload.qty).sort()).toEqual([1, 2])
  expect(new Set(removes.map((r) => r.cart_id)).size).toBe(1)
  expect(screen.queryByText('Ver carro')).toBeNull()
})

function renderCart(products) {
  render(
    <DemoProvider>
      <ProfileProvider>
        <AssistantProvider>
          <CartProvider>
            <Seed products={products} />
            <CartBar push={() => {}} />
          </CartProvider>
        </AssistantProvider>
      </ProfileProvider>
    </DemoProvider>,
  )
  fireEvent.click(screen.getByText('Ver carro'))
}

test('una canasta por tienda, con su compra mínima: «Tu compra será dividida en 2 pedidos»', async () => {
  const oil = toPrototypeProduct(fixture('catalog-store').products[0]) // $3.190 en el súper 9101
  const beer = toPrototypeProduct(fixture('search-grouped').groups[0].products[0]) // $1.190 en la botillería 9402
  terms.byStore = { [oil.storeId]: { deliveryFee: null, minOrder: 8490, servicePct: null } }
  renderCart([oil, beer])
  await act(() => new Promise((resolve) => setTimeout(resolve, 0)))
  expect(screen.getByText('Tu compra será dividida en 2 pedidos, uno por tienda.')).toBeTruthy()
  expect(screen.getByRole('region', { name: oil.store })).toBeTruthy()
  expect(screen.getByRole('region', { name: beer.store })).toBeTruthy()
  expect(screen.getByText('Te faltan $5.300 para hacer el pedido')).toBeTruthy()
  // La botillería no trae mínimo en el catálogo: el supuesto de Licores, rotulado.
  expect(screen.getByText(/Te faltan \$3\.810 para hacer el pedido/).textContent).toMatch(/mínimo de ejemplo/)
})
