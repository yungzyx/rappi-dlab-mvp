import { useEffect } from 'react'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { fixture, stubApi } from '../../test/api'
import { ToastProvider } from '../../components/Toast'
import { AssistantProvider, useAssistant } from '../../state/AssistantContext'
import { DemoProvider } from '../../state/DemoContext'
import { QUIET_KEY, noteDismissed, resetQuiet } from '../../state/agentQuiet'
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
  items: [
    { name: 'Pizza (prueba)', img: 'pizza.webp', price: '$7.990', qty: 1, entityType: 'menu_item', entityId: '95001' },
  ],
  total: 7990,
}

function Harness({ reset }) {
  const orders = useOrders()
  const order = orders.orders[0]
  if (!order)
    return (
      <button type="button" onClick={() => orders.place(ORDER)}>
        pedir
      </button>
    )
  return <TrackingScreen back={() => {}} reset={reset} params={{ orderId: order.id }} />
}

let api
beforeEach(() => {
  // A mediodía: «en silencio por hoy» guarda la fecha y `deliver()` adelanta el reloj 21 s; con la hora real, un test que
  // partía antes de la medianoche terminaba en otro día.
  vi.useFakeTimers({ now: new Date(2026, 9, 21, 12) })
  events.track.mockClear()
  api = stubApi({ 'POST /agent/offer': fixture('agent-offer-proximo-pedido') })
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

const renderTracking = (reset = vi.fn()) => {
  render(
    <DemoProvider>
      <ProfileProvider>
        <AssistantProvider>
          <OrdersProvider>
            <ToastProvider>
              <Probe />
              <Harness reset={reset} />
            </ToastProvider>
          </OrdersProvider>
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
const offerRequests = () =>
  api.mock.calls.filter(([url]) => url.endsWith('/agent/offer')).map(([, init]) => JSON.parse(init.body))
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
        context: { items: [{ entity_type: 'menu_item', entity_id: '95001' }] },
      },
    ])
    const card = screen.getByRole('button', { name: NEXT_CARD })
    expect(card.textContent).toContain('¿Y ahora bebidas gaseosas?')
    expect(card.textContent).toContain('Mochi te arma el próximo pedido')
    expect(events.track).toHaveBeenCalledWith('suggestion_shown', {
      concept_id: 'gaseosas',
      vertical: 'express',
      payload: { origen: 'agent-proximo_pedido' },
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

  test('al entregar aparece «Volver al inicio», que reinicia la pila', async () => {
    const reset = vi.fn()
    renderTracking(reset)
    fireEvent.click(screen.getByText('pedir'))
    expect(screen.queryByText('Volver al inicio')).toBeNull()
    await act(() => vi.advanceTimersByTimeAsync(21_000))
    fireEvent.click(screen.getByText('Volver al inicio'))
    expect(reset).toHaveBeenCalled()
  })

  test('antes de la entrega no pide nada, y sin oferta (204) o sin respuesta la tarjeta no aparece', async () => {
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

  test('en «Rappi hoy», al entregar no hay oferta de Mochi (ni se pide)', async () => {
    localStorage.setItem('rappi-proto-demo-mode', 'actual')
    renderTracking()
    await deliver()
    expect(offerRequests()).toEqual([])
    expect(screen.queryByRole('button', { name: NEXT_CARD })).toBeNull()
  })

  test('en «Rappi hoy» el mapa queda como antes: Mochi de frente y sin «¡Ya casi!»', async () => {
    localStorage.setItem('rappi-proto-demo-mode', 'actual')
    renderTracking()
    fireEvent.click(screen.getByText('pedir'))
    const image = () => document.querySelector('.tracking-rider image')
    act(() => vi.advanceTimersByTime(1_000)) // preparando
    expect(image().getAttribute('y')).toBe('0')
    act(() => vi.advanceTimersByTime(17_500)) // tramo final de la ruta
    expect(image().getAttribute('x')).toBe('0')
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
})
