import { useEffect } from 'react'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { fixture, stubApi } from '../../test/api'
import { ToastProvider } from '../../components/Toast'
import { AssistantProvider, useAssistant } from '../../state/AssistantContext'
import { CartProvider } from '../../state/CartContext'
import { DemoProvider } from '../../state/DemoContext'
import { QUIET_KEY, noteDismissed, resetQuiet } from '../../state/agentQuiet'
import { setAgentEnabled } from '../../state/agentEnabled'
import { OrdersProvider, useOrders } from '../../state/OrdersContext'
import { ProfileProvider } from '../../state/ProfileContext'
import { today } from '../../utils/today'
import TrackingScreen from './TrackingScreen'

const events = vi.hoisted(() => ({ track: vi.fn(), flush: async () => {}, clear: () => {}, settled: async () => {} }))
vi.mock('../../state/EventsContext', async (importOriginal) => ({
  ...(await importOriginal()),
  useEvents: () => events,
}))

// Lo que se pidió son productos de la API: la línea guarda su tipo e id, con los que Mochi arma el próximo pedido.
const ORDER = {
  stores: ['Pizzería de prueba'],
  cartId: 'c-prueba',
  items: [
    { name: 'Pizza (prueba)', img: 'pizza.webp', price: '$7.990', qty: 1, entityType: 'menu_item', entityId: '95001' },
  ],
  total: 7990,
}

function Harness({ reset, placed = ORDER }) {
  const orders = useOrders()
  const order = orders.orders[0]
  if (!order)
    return (
      <button type="button" onClick={() => orders.place(placed)}>
        pedir
      </button>
    )
  return <TrackingScreen back={() => {}} reset={reset} push={push} params={{ orderId: order.id }} />
}
const push = vi.fn()

// Las ofertas de ejemplo de cada momento (make contract): el OnTop mientras llega, el próximo pedido al entregar.
const byMoment =
  (moments = {}) =>
  (req) =>
    moments[req.body.moment] ??
    fixture(req.body.moment === 'ontop' ? 'agent-offer-ontop' : 'agent-offer-proximo-pedido')

let api
beforeEach(() => {
  // A mediodía: "en silencio por hoy" guarda la fecha y `deliver()` adelanta el reloj 21 s; con la hora real, un test que
  // partía antes de la medianoche terminaba en otro día.
  vi.useFakeTimers({ now: new Date(2026, 9, 21, 12) })
  events.track.mockClear()
  api = stubApi({ 'POST /agent/offer': byMoment() })
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  resetQuiet()
  localStorage.clear()
})

const probe = {}
function Probe() {
  const assistant = useAssistant()
  useEffect(() => {
    probe.assistant = assistant
  })
  return null
}

const renderTracking = (reset = vi.fn(), placed = ORDER) => {
  render(
    <DemoProvider>
      <ProfileProvider>
        <AssistantProvider>
          <CartProvider>
            <OrdersProvider>
              <ToastProvider>
                <Probe />
                <Harness reset={reset} placed={placed} />
              </ToastProvider>
            </OrdersProvider>
          </CartProvider>
        </AssistantProvider>
      </ProfileProvider>
    </DemoProvider>,
  )
}

// Hace el pedido y deja pasar el reloj hasta la entrega, con la respuesta de la API ya recibida.
const deliver = async () => {
  fireEvent.click(screen.getByText('pedir'))
  await act(() => vi.advanceTimersByTimeAsync(21_000))
}
const offerRequests = (moment = 'proximo_pedido') =>
  api.mock.calls
    .filter(([url]) => url.endsWith('/agent/offer'))
    .map(([, init]) => JSON.parse(init.body))
    .map(({ session_id: _session, ...body }) => body) // la sesión la revisa api/agent.test.js
    .filter((body) => body.moment === moment)
const NEXT_CARD = /¿Y ahora/

describe('TrackingScreen', () => {
  // Primero: lo mostrado se recuerda lo que dura la pestaña (este archivo).
  test('al entregar, la tarjeta ¿Y ahora…? sale de la API', async () => {
    renderTracking()
    await deliver()
    expect(offerRequests()).toEqual([
      {
        moment: 'proximo_pedido',
        user_id: expect.any(String),
        surface: 'tracking',
        context: { items: [{ entity_type: 'menu_item', entity_id: '95001' }] },
      },
    ])
    const card = screen.getByRole('button', { name: NEXT_CARD })
    expect(card.textContent).toContain('¿Y ahora bebidas gaseosas?')
    expect(card.textContent).toContain('Mochi te arma el próximo pedido')
    expect(events.track).toHaveBeenCalledWith('suggestion_shown', {
      concept_id: 'gaseosas',
      vertical: 'express',
      surface: 'tracking',
      origin: 'agent-proximo_pedido',
      request_id: 'contrato-agent-offer-proximo-pedido',
      payload: { basis: ['pedido'] }, // de qué sale su "¿Por qué?"
    })
    // Mientras llegaba se mostró el OnTop de Turbo (también una sugerencia de Mochi).
    expect(events.track).toHaveBeenCalledWith('suggestion_shown', {
      concept_id: 'helados',
      vertical: 'turbo',
      surface: 'tracking',
      origin: 'agent-ontop',
      request_id: 'contrato-agent-offer-ontop',
      payload: { basis: ['ofertas', 'ontop'] },
    })

    // Tocarla abre el buscador con esa misma oferta, para agregar lo que arma.
    fireEvent.click(card)
    expect(probe.assistant.session.offer).toEqual({
      moment: 'proximo_pedido',
      context: { items: [{ entity_type: 'menu_item', entity_id: '95001' }] },
    })
  })

  test('the offer has ¿Por qué?', async () => {
    renderTracking()
    await deliver()
    fireEvent.click(screen.getByRole('button', { name: '¿Por qué?' }))
    expect(screen.getByText(fixture('agent-offer-proximo-pedido').reason.text)).toBeTruthy()
  })

  test('al entregar aparece "Volver al inicio", que reinicia la pila', async () => {
    const reset = vi.fn()
    renderTracking(reset)
    fireEvent.click(screen.getByText('pedir'))
    expect(screen.queryByText('Volver al inicio')).toBeNull()
    await act(() => vi.advanceTimersByTimeAsync(21_000))
    fireEvent.click(screen.getByText('Volver al inicio'))
    expect(reset).toHaveBeenCalled()
  })

  test('antes de la entrega no pide el próximo pedido, y sin oferta (204) o sin respuesta la tarjeta no aparece', async () => {
    renderTracking()
    fireEvent.click(screen.getByText('pedir'))
    await act(() => vi.advanceTimersByTimeAsync(5_000))
    expect(offerRequests()).toEqual([])

    cleanup()
    localStorage.clear()
    api = stubApi({ 'POST /agent/offer': 204 })
    renderTracking()
    await deliver()
    expect(offerRequests()).toHaveLength(1)
    expect(screen.queryByRole('button', { name: NEXT_CARD })).toBeNull()

    cleanup()
    localStorage.clear()
    api = stubApi({ 'POST /agent/offer': 'offline' })
    renderTracking()
    await deliver()
    expect(screen.queryByRole('button', { name: NEXT_CARD })).toBeNull()
    expect(screen.getByText('Volver al inicio')).toBeTruthy()
  })

  test('Mochi en silencio no pide el próximo pedido', async () => {
    localStorage.setItem(QUIET_KEY, today())
    renderTracking()
    await deliver()
    expect(offerRequests()).toEqual([])
    expect(screen.queryByRole('button', { name: NEXT_CARD })).toBeNull()

    cleanup()
    localStorage.clear()
    noteDismissed()
    noteDismissed() // lo ignoraron dos veces seguidas
    renderTracking()
    await deliver()
    expect(offerRequests()).toEqual([])
  })

  test('en "Rappi hoy", al entregar no hay oferta de Mochi (ni se pide)', async () => {
    localStorage.setItem('rappi-proto-demo-mode', 'actual')
    renderTracking()
    await deliver()
    expect(offerRequests()).toEqual([])
    expect(screen.queryByRole('button', { name: NEXT_CARD })).toBeNull()
  })

  // "Rappi hoy" no tiene a Mochi, y el grupo de control ("Mochi apagado") tampoco: reparte un repartidor neutro.
  test.each([
    ['en "Rappi hoy"', () => localStorage.setItem('rappi-proto-demo-mode', 'actual')],
    ['con Mochi apagado (grupo de control)', () => setAgentEnabled(false)],
  ])('%s el repartidor del mapa es neutro: sin Mochi ni "¡Ya casi!"', async (_, setUp) => {
    setUp()
    renderTracking()
    fireEvent.click(screen.getByText('pedir'))
    act(() => vi.advanceTimersByTime(1_000)) // preparando
    expect(document.querySelector('.tracking-rider [data-rider="neutral"]')).toBeTruthy()
    expect(document.querySelector('.tracking-rider image')).toBeNull()
    act(() => vi.advanceTimersByTime(17_500)) // tramo final de la ruta
    expect(document.querySelector('.tracking-rider image')).toBeNull()
    expect(document.querySelector('.tracking-almost')).toBeNull()
  })

  test('en el prototipo final, preparando, Mochi está tímido', async () => {
    renderTracking()
    fireEvent.click(screen.getByText('pedir'))
    act(() => vi.advanceTimersByTime(1_000))
    expect(document.querySelector('.tracking-rider image').getAttribute('y')).toBe('-1')
  })

  test('mientras llega el pedido no se ofrece ningún juego', async () => {
    renderTracking()
    fireEvent.click(screen.getByText('pedir'))
    expect(screen.queryByText(/Juega mientras llega tu pedido/)).toBeNull()
    expect(screen.queryByRole('button', { name: /Juega/ })).toBeNull()
  })
  test('un restaurante pasa por "Buscando un Rappi" y, en camino, muestra el código de entrega', async () => {
    renderTracking()
    fireEvent.click(screen.getByText('pedir'))
    expect(screen.getByText('Buscando un Rappi')).toBeTruthy()
    expect(screen.queryByRole('note', { name: 'Código de entrega' })).toBeNull()
    await act(() => vi.advanceTimersByTimeAsync(10_000))
    expect(screen.getByRole('note', { name: 'Código de entrega' }).textContent).toMatch(/\d{4}/)
    expect(screen.getByText(/solo cuando tengas el pedido en tus manos/)).toBeTruthy()
    await act(() => vi.advanceTimersByTimeAsync(11_000))
    expect(screen.queryByRole('note', { name: 'Código de entrega' })).toBeNull()
  })

  test('mientras llega, el OnTop de Turbo con su plazo, rotulado de ejemplo; al entregar se va', async () => {
    renderTracking()
    fireEvent.click(screen.getByText('pedir'))
    await act(() => vi.advanceTimersByTimeAsync(500))
    expect(offerRequests('ontop')).toEqual([
      {
        moment: 'ontop',
        user_id: expect.any(String),
        surface: 'tracking',
        context: { vertical: 'restaurants', items: [{ entity_type: 'menu_item', entity_id: '95001' }] },
      },
    ])
    const ontop = screen.getByRole('region', { name: 'Turbo: suma a tu pedido' })
    expect(ontop.textContent).toMatch(/Turbo: suma esto antes de las \d{2}:\d{2}/)
    expect(ontop.textContent).toContain(fixture('agent-offer-ontop').text)
    expect(ontop.textContent).toContain('Plazo y envío de ejemplo')
    await act(() => vi.advanceTimersByTimeAsync(21_000))
    expect(screen.queryByRole('region', { name: 'Turbo: suma a tu pedido' })).toBeNull()
  })

  test('sin OnTop en "Rappi hoy", con Mochi en silencio ni en un pedido de Turbo', async () => {
    localStorage.setItem('rappi-proto-demo-mode', 'actual')
    renderTracking()
    fireEvent.click(screen.getByText('pedir'))
    await act(() => vi.advanceTimersByTimeAsync(500))
    expect(offerRequests('ontop')).toEqual([])

    cleanup()
    localStorage.clear()
    localStorage.setItem(QUIET_KEY, today())
    renderTracking()
    fireEvent.click(screen.getByText('pedir'))
    await act(() => vi.advanceTimersByTimeAsync(500))
    expect(offerRequests('ontop')).toEqual([])

    cleanup()
    localStorage.clear()
    const turbo = { ...ORDER, items: [{ ...ORDER.items[0], entityType: 'catalog_item', vertical: 'turbo' }] }
    renderTracking(vi.fn(), turbo)
    fireEvent.click(screen.getByText('pedir'))
    await act(() => vi.advanceTimersByTimeAsync(500))
    expect(offerRequests('ontop')).toEqual([])
    expect(screen.getByText('Turbo: tu pedido llega en minutos')).toBeTruthy()
  })

  test('5 estrellas se guardan de una: evento order_rated con el carro del pedido', async () => {
    renderTracking()
    await deliver()
    fireEvent.click(screen.getByRole('radio', { name: '5 estrellas' }))
    expect(events.track).toHaveBeenCalledWith('order_rated', {
      surface: 'tracking',
      cart_id: 'c-prueba',
      payload: { stars: 5, reasons: [] },
    })
    expect(screen.getByText('Tu calificación')).toBeTruthy()
    expect(screen.getByRole('radio', { name: '5 estrellas' }).disabled).toBe(true)
    expect(screen.queryByText('¿Qué problema tuvo el pedido?')).toBeNull()
    expect(screen.getByRole('button', { name: NEXT_CARD })).toBeTruthy()
  })

  test('con 3 estrellas o menos pregunta qué problema tuvo; mandarla oculta el próximo pedido de Mochi', async () => {
    renderTracking()
    await deliver()
    fireEvent.click(screen.getByRole('radio', { name: '2 estrellas' }))
    expect(events.track).not.toHaveBeenCalledWith('order_rated', expect.anything())
    expect(screen.getByText('¿Qué problema tuvo el pedido?')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Llegó tarde' }))
    fireEvent.click(screen.getByRole('button', { name: 'Faltó un producto' }))
    fireEvent.click(screen.getByRole('button', { name: 'Enviar calificación' }))
    expect(events.track).toHaveBeenCalledWith('order_rated', {
      surface: 'tracking',
      cart_id: 'c-prueba',
      payload: { stars: 2, reasons: ['tarde', 'faltante'] },
    })
    expect(screen.queryByRole('button', { name: NEXT_CARD })).toBeNull()
  })

  test('con las flechas las estrellas se marcan sin enviar: una nota alta sale al tocarla', async () => {
    renderTracking()
    await deliver()
    const star = (n) => screen.getByRole('radio', { name: `${n} estrellas` })
    star(1).focus()
    fireEvent.keyDown(star(1), { key: 'End' })
    expect(document.activeElement).toBe(star(5))
    expect(star(5).getAttribute('aria-checked')).toBe('true')
    expect(events.track).not.toHaveBeenCalledWith('order_rated', expect.anything())
    fireEvent.click(star(5))
    expect(events.track).toHaveBeenCalledWith(
      'order_rated',
      expect.objectContaining({ payload: { stars: 5, reasons: [] } }),
    )
  })

  test('una nota alta marcada con las flechas se puede enviar con "Enviar calificación"', async () => {
    renderTracking()
    await deliver()
    const star = (n) => screen.getByRole('radio', { name: `${n} estrellas` })
    expect(screen.queryByRole('button', { name: 'Enviar calificación' })).toBeNull()
    star(1).focus()
    fireEvent.keyDown(star(1), { key: 'ArrowLeft' }) // con vuelta: de 1 a 5
    fireEvent.keyDown(star(5), { key: 'ArrowLeft' }) // 4, sin enviar
    expect(star(4).getAttribute('aria-checked')).toBe('true')
    expect(events.track).not.toHaveBeenCalledWith('order_rated', expect.anything())
    expect(screen.queryByText('¿Qué problema tuvo el pedido?')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Enviar calificación' }))
    expect(events.track).toHaveBeenCalledWith(
      'order_rated',
      expect.objectContaining({ payload: { stars: 4, reasons: [] } }),
    )
    expect(screen.getByText('Tu calificación')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Enviar calificación' })).toBeNull()
  })

  test('un pedido guardado sin su carro se califica en el teléfono, sin evento', async () => {
    renderTracking(vi.fn(), { ...ORDER, cartId: undefined })
    await deliver()
    fireEvent.click(screen.getByRole('radio', { name: '4 estrellas' }))
    expect(screen.getByText('Tu calificación')).toBeTruthy()
    expect(events.track).not.toHaveBeenCalledWith('order_rated', expect.anything())
  })

  test('entregado: propina para el Rappi (no se cobra) y "Pídelo de nuevo"', async () => {
    renderTracking()
    await deliver()
    expect(screen.getByText(/El 100% es para tu Rappi/)).toBeTruthy()
    const tip = screen.getByRole('radio', { name: '$1.000' })
    fireEvent.click(tip)
    expect(tip.getAttribute('aria-checked')).toBe('true')
    expect(screen.getByText('Tu Rappi recibe el 100% de la propina')).toBeTruthy()
    expect(screen.getByText('Demo: no se cobra.')).toBeTruthy()
  })
})
