import { cleanup, fireEvent, render, screen } from '@testing-library/react'
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
