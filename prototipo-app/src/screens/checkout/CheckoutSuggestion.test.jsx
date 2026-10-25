import { useEffect } from 'react'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { fixture, stubApi } from '../../test/api'
import { CartProvider, useCart } from '../../state/CartContext'
import { DemoProvider } from '../../state/DemoContext'
import { ProfileProvider } from '../../state/ProfileContext'
import CheckoutSuggestion from './CheckoutSuggestion'

const events = vi.hoisted(() => ({ track: vi.fn(), flush: async () => {}, clear: () => {}, settled: async () => {} }))
vi.mock('../../state/EventsContext', async (importOriginal) => ({
  ...(await importOriginal()),
  useEvents: () => events,
}))

// Productos de la API, como llegan al carro: con su tipo e id reales.
const PISCO = {
  id: 'cat-94005',
  name: 'Pisco 35° 750 cc (prueba)',
  price: '$6.990',
  vertical: 'liquor',
  entityType: 'catalog_item',
  entityId: '94005',
  concept: 'pisco',
}
const PIZZA = {
  id: 'menu-95001',
  name: 'Pizza (prueba)',
  price: '$7.990',
  vertical: 'restaurants',
  entityType: 'menu_item',
  entityId: '95001',
}

const probe = {}
function Probe() {
  const cart = useCart()
  useEffect(() => {
    probe.cart = cart
  })
  return null
}
const renderCheckout = (products = [PISCO]) => {
  const view = render(
    <DemoProvider>
      <ProfileProvider>
        <CartProvider>
          <Probe />
          <CheckoutSuggestion />
        </CartProvider>
      </ProfileProvider>
    </DemoProvider>,
  )
  act(() => products.forEach((product) => probe.cart.add(product)))
  return view
}
const ASK = '¿Me falta algo? Pregúntale a Mochi'
const ask = async () => {
  fireEvent.click(screen.getByRole('button', { name: ASK }))
  await act(async () => {}) // la respuesta de la API
}
const tracked = (type) =>
  events.track.mock.calls.filter(([name, fields]) => name === type && fields.payload?.origen === 'agent-checkout')

let api
beforeEach(() => {
  localStorage.setItem('rappi-proto-demo-mode', 'final')
  events.track.mockClear()
  api = stubApi({ 'POST /agent/offer': fixture('agent-offer-checkout') })
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  localStorage.clear()
})
const offerRequests = () =>
  api.mock.calls.filter(([url]) => url.endsWith('/agent/offer')).map(([, init]) => JSON.parse(init.body))

describe('«¿Me falta algo?» en el checkout (solo si se pide)', () => {
  // Primero: lo mostrado se recuerda lo que dura la pestaña (este archivo).
  test('pedirla registra suggestion_shown con origen agent-checkout, una sola vez', async () => {
    renderCheckout()
    await ask()
    expect(tracked('suggestion_shown')).toHaveLength(1)
    expect(tracked('suggestion_shown')[0][1]).toMatchObject({ concept_id: 'snacks-salados', vertical: 'express' })
    cleanup()
    renderCheckout()
    await ask()
    expect(tracked('suggestion_shown')).toHaveLength(1)
  })

  test('¿Me falta algo? pide la oferta solo al tocarlo y dice Tu carrito está completo en un 204', async () => {
    api = stubApi({ 'POST /agent/offer': 204 })
    renderCheckout([PISCO, PIZZA])
    await act(async () => {})
    expect(offerRequests()).toEqual([]) // nada aparece ni se pide por su cuenta
    expect(screen.queryByText('Tu carrito está completo')).toBeNull()

    await ask()
    expect(offerRequests()).toEqual([
      {
        moment: 'checkout',
        user_id: expect.any(String),
        context: {
          cart: [
            { entity_type: 'catalog_item', entity_id: '94005' },
            { entity_type: 'menu_item', entity_id: '95001' },
          ],
        },
      },
    ])
    expect(screen.getByText('Tu carrito está completo')).toBeTruthy()
    expect(screen.queryByRole('button', { name: ASK })).toBeNull()
    expect(events.track.mock.calls.filter(([name]) => name === 'suggestion_shown')).toHaveLength(0)
  })

  test('al tocarlo muestra la oferta del servidor: su texto, el producto y su razón', async () => {
    renderCheckout()
    expect(document.querySelector('.checkout-suggestion')).toBeNull()
    await ask()
    const card = document.querySelector('.checkout-suggestion')
    expect(card.querySelector('.checkout-suggestion-reason').textContent).toBe(fixture('agent-offer-checkout').text)
    expect(card.querySelector('.checkout-suggestion-product').textContent).toMatch(
      /^Papas fritas clásicas 180 g \(prueba\) · \$2\.290 · Express/,
    )
    expect(card.querySelector('.mascot')).toBeTruthy()
    expect(screen.queryByLabelText('Solo mayores de 18')).toBeNull()
  })

  test('the offer has ¿Por qué?', async () => {
    renderCheckout()
    await ask()
    fireEvent.click(screen.getByRole('button', { name: '¿Por qué?' }))
    expect(screen.getByText(fixture('agent-offer-checkout').reason.text)).toBeTruthy()
  })

  test('agregarla la suma al carro como sugerencia aceptada, con «Deshacer» que la quita', async () => {
    renderCheckout()
    await ask()
    fireEvent.click(screen.getByRole('button', { name: 'Agregar' }))
    expect(probe.cart.count).toBe(2)
    const added = probe.cart.items.find(({ product }) => product.entityId === '91001')
    expect(added.product).toMatchObject({ fromSuggestion: true, suggestionOrigin: 'agent-checkout' })
    expect(tracked('suggestion_accepted')).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: 'Deshacer' }))
    expect(probe.cart.count).toBe(1)
  })

  test('si la oferta es de alcohol, lleva su aviso +18', async () => {
    const body = fixture('agent-offer-checkout')
    body.products[0].age_restricted = true
    api = stubApi({ 'POST /agent/offer': body })
    renderCheckout([PIZZA])
    await ask()
    expect(screen.getByLabelText('Solo mayores de 18').textContent).toBe('+18')
  })

  test('si la API no contesta, Mochi no dice nada y se puede volver a pedir', async () => {
    api = stubApi({ 'POST /agent/offer': 'offline' })
    renderCheckout()
    await ask()
    expect(document.querySelector('.checkout-suggestion')).toBeNull()
    expect(screen.queryByText('Tu carrito está completo')).toBeNull()
    api = stubApi({ 'POST /agent/offer': fixture('agent-offer-checkout') })
    await ask()
    expect(document.querySelector('.checkout-suggestion')).not.toBeNull()
  })

  test('sin nada en el carro no ofrece el botón', async () => {
    renderCheckout([])
    expect(screen.queryByRole('button', { name: ASK })).toBeNull()
  })

  test('en «Rappi hoy» no aparece', () => {
    localStorage.setItem('rappi-proto-demo-mode', 'actual')
    renderCheckout()
    expect(screen.queryByRole('button', { name: ASK })).toBeNull()
  })
})
