import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { useAddToCart } from '../hooks/useAddToCart'
import { stubApi } from '../test/api'
import { CartProvider } from './CartContext'
import { DemoProvider } from './DemoContext'
import { EventsProvider, useEvents } from './EventsContext'
import { OrdersProvider, useOrders } from './OrdersContext'
import { ProfileProvider } from './ProfileContext'
import { quietToday } from './agentQuiet'
import { resetMochiMood, useMochiMood } from './mochiMood'
import { useAgentConversation } from '../components/assistant/useAgentConversation'
import { today } from '../utils/today'

// Lo que hace reaccionar a Mochi, con los mismos caminos de la app: los eventos que registra (EventsContext: `track`),
// el pedido hecho (OrdersContext) y las respuestas del buscador con Mochi (useAgentConversation).

const BEER = { id: 'b1', name: 'Cerveza Escudo 470 cc', price: '$1.380', vertical: 'liquor', store: 'Botillería' }

function Providers({ children }) {
  return (
    <DemoProvider>
      <ProfileProvider>
        <EventsProvider>
          <OrdersProvider>
            <CartProvider>{children}</CartProvider>
          </OrdersProvider>
        </EventsProvider>
      </ProfileProvider>
    </DemoProvider>
  )
}

const setup = () =>
  renderHook(
    () => ({
      mood: useMochiMood(),
      events: useEvents(),
      cart: useAddToCart(),
      orders: useOrders(),
      talk: useAgentConversation(),
    }),
    { wrapper: Providers },
  )

beforeEach(() => {
  vi.useFakeTimers()
  localStorage.clear()
  localStorage.setItem('rappi-proto-demo-mode', 'final')
  stubApi({})
  resetMochiMood()
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('qué hace reaccionar a Mochi', () => {
  test('agregar un producto de su sugerencia lo hace celebrar; uno cualquiera, no', () => {
    const { result } = setup()
    act(() => result.current.cart.add(BEER))
    expect(result.current.mood.emotion).toBeNull()
    act(() => result.current.cart.add({ ...BEER, id: 'b2', fromSuggestion: true, suggestionOrigin: 'agent-carrito' }))
    expect(result.current.mood.emotion).toBe('celebrate')
  })

  test('aceptar su oferta ("Ver en…" de la oferta sin resultado: `suggestion_accepted`) también', () => {
    const { result } = setup()
    act(() => result.current.events.track('suggestion_accepted', { origin: 'agent-sin_resultado' }))
    expect(result.current.mood.emotion).toBe('celebrate')
  })

  test('el pedido confirmado lo hace bailar', () => {
    const { result } = setup()
    act(() => result.current.orders.placeMany([{ stores: [], items: [], total: 1000 }]))
    expect(result.current.mood.emotion).toBe('dance')
  })

  test('una búsqueda sin resultados lo preocupa; con resultados, lo alegra', () => {
    const { result } = setup()
    act(() => result.current.events.track('search', { query: 'suchi', results: 0, unmet: true }))
    expect(result.current.mood.emotion).toBe('worried')
    act(() => resetMochiMood())
    act(() => result.current.events.track('search', { query: 'sushi', results: 8, unmet: false }))
    expect(result.current.mood.emotion).toBe('happy')
  })

  test('el buscador con Mochi: piensa mientras espera, se alegra con productos y se preocupa sin conexión', async () => {
    const { result } = setup()
    let answer
    act(() => {
      result.current.talk.ask(() => new Promise((resolve) => (answer = resolve)))
    })
    await act(async () => {})
    expect(result.current.talk.mood).toBe('thinking')
    await act(async () => answer({ text: 'Mira estas', products: [BEER] }))
    await act(() => vi.advanceTimersByTimeAsync(500))
    expect(result.current.mood.emotion).toBe('happy')

    act(() => resetMochiMood())
    act(() => {
      result.current.talk.ask(async () => ({ text: 'Sin conexión', retry: () => {} }))
    })
    await act(() => vi.advanceTimersByTimeAsync(500))
    expect(result.current.mood.emotion).toBe('worried')
  })

  test('silenciado por hoy no reacciona: dormita', () => {
    const { result } = setup()
    act(() => quietToday(today()))
    act(() => result.current.orders.placeMany([{ stores: [], items: [], total: 1000 }]))
    expect(result.current.mood).toMatchObject({ quiet: true, emotion: null })
  })
})
