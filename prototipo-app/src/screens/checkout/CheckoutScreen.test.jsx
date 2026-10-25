import { StrictMode, useState } from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { toPrototypeProduct } from '../../api/client'
import { ordersSettled } from '../../api/orders'
import { fixture } from '../../test/api'
import { ToastProvider } from '../../components/Toast'
import { AddressProvider } from '../../state/AddressContext'
import { AssistantProvider } from '../../state/AssistantContext'
import { CartProvider, useCart } from '../../state/CartContext'
import { DemoProvider } from '../../state/DemoContext'
import { OrdersProvider } from '../../state/OrdersContext'
import { ProfileProvider } from '../../state/ProfileContext'
import CheckoutScreen from './CheckoutScreen'

const api = vi.hoisted(() => ({ health: vi.fn(), sendOrder: vi.fn() }))
vi.mock('../../api/client', async (importOriginal) => ({ ...(await importOriginal()), ...api }))
const events = vi.hoisted(() => ({
  track: vi.fn(),
  flush: vi.fn(async () => {}),
  clear: () => {},
  settled: vi.fn(async () => {}),
}))
vi.mock('../../state/EventsContext', async (importOriginal) => ({
  ...(await importOriginal()),
  useEvents: () => events,
}))

// Un producto de Licores y uno del Súper: el carro va en dos pedidos.
// Ambos salen de las respuestas de ejemplo de la API, con su tipo e id reales.
const BEER = toPrototypeProduct(fixture('search-grouped').groups[0].products[0])
const AVOCADO = toPrototypeProduct(fixture('catalog-store').products[0])

/** Llena el carro y abre el checkout, como al tocar la barra del carrito. */
function Harness() {
  const cart = useCart()
  const [open, setOpen] = useState(false)
  if (open) return <CheckoutScreen back={() => setOpen(false)} push={() => {}} />
  return (
    <button
      type="button"
      onClick={() => {
        cart.add(BEER)
        cart.add(AVOCADO)
        setOpen(true)
      }}
    >
      ir a pagar
    </button>
  )
}

function renderCheckout() {
  render(
    <StrictMode>
      <DemoProvider>
        <ProfileProvider>
          <AssistantProvider>
            <CartProvider>
              <OrdersProvider>
                <AddressProvider>
                  <ToastProvider>
                    <Harness />
                  </ToastProvider>
                </AddressProvider>
              </OrdersProvider>
            </CartProvider>
          </AssistantProvider>
        </ProfileProvider>
      </DemoProvider>
    </StrictMode>,
  )
  fireEvent.click(screen.getByText('ir a pagar'))
}

function deferred() {
  let resolve
  const promise = new Promise((res) => (resolve = res))
  return { promise, resolve }
}
const tick = () => new Promise((resolve) => setTimeout(resolve, 0))

const checkoutStarts = () =>
  events.track.mock.calls.filter(([type]) => type === 'checkout_start').map(([, fields]) => fields)

beforeEach(() => {
  api.health.mockResolvedValue({ voz: false })
  api.sendOrder.mockResolvedValue({})
})
afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  localStorage.clear()
})

describe('inicio de pago', () => {
  test('abrir el checkout ya es iniciar el pago: uno por vertical del carro, antes de «Hacer pedido»', () => {
    renderCheckout()
    const starts = checkoutStarts()
    expect(starts.map((fields) => fields.vertical).sort()).toEqual(['licores', 'supermercado'])
    expect(new Set(starts.map((fields) => fields.cart_id)).size).toBe(1)
  })

  test('volver sin pagar deja el inicio de pago y ningún pedido', () => {
    renderCheckout()
    fireEvent.click(screen.getByLabelText('Volver'))
    expect(checkoutStarts()).toHaveLength(2)
    expect(api.sendOrder).not.toHaveBeenCalled()
  })

  test('pagar no repite el inicio de pago', async () => {
    renderCheckout()
    fireEvent.click(screen.getByText(/Hacer pedido/))
    await vi.waitFor(() => expect(api.sendOrder).toHaveBeenCalledTimes(2))
    expect(checkoutStarts()).toHaveLength(2)
  })

  test('el pedido guardado lleva el tipo y el id de cada línea (con ellos Mochi arma el próximo pedido)', async () => {
    renderCheckout()
    fireEvent.click(screen.getByText(/Hacer pedido/))
    await vi.waitFor(() => expect(api.sendOrder).toHaveBeenCalledTimes(2))
    const [order] = JSON.parse(localStorage.getItem('rappi-proto-orders'))
    expect(order.items.find((item) => item.entityId === '94001')).toMatchObject({ entityType: 'catalog_item' })
  })

  test('el inicio de pago llega al servidor antes que el pedido (la hora la pone el servidor al recibir)', async () => {
    const queued = deferred() // la cola, con los checkout_start
    const inFlight = deferred() // un lote que ya había salido
    events.flush.mockReturnValueOnce(queued.promise)
    events.settled.mockReturnValueOnce(inFlight.promise)
    renderCheckout()
    fireEvent.click(screen.getByText(/Hacer pedido/))
    await tick()
    expect(api.sendOrder).not.toHaveBeenCalled()

    queued.resolve()
    await tick()
    expect(api.sendOrder).not.toHaveBeenCalled()

    inFlight.resolve()
    await vi.waitFor(() => expect(api.sendOrder).toHaveBeenCalledTimes(2))
  })
})

describe('pedidos en vuelo', () => {
  test('placing the order is tracked from the first wait until the last send ends', async () => {
    const inFlight = deferred() // un lote de eventos que ya había salido
    const sending = deferred() // el POST del pedido
    events.settled.mockReturnValueOnce(inFlight.promise)
    api.sendOrder.mockReturnValue(sending.promise)
    renderCheckout()
    fireEvent.click(screen.getByText(/Hacer pedido/))

    let settled = false
    const waiting = ordersSettled().then(() => (settled = true))
    await tick()
    expect(api.sendOrder).not.toHaveBeenCalled() // todavía espera los eventos: ya cuenta como en vuelo
    expect(settled).toBe(false)

    inFlight.resolve()
    await vi.waitFor(() => expect(api.sendOrder).toHaveBeenCalledTimes(2))
    await tick()
    expect(settled).toBe(false) // los POST siguen en camino

    sending.resolve({})
    await waiting
    expect(settled).toBe(true)
  })
})

describe('carrito vacío', () => {
  test('ofrece seguir comprando (vuelve atrás)', () => {
    const back = vi.fn()
    render(
      <DemoProvider>
        <ProfileProvider>
          <AssistantProvider>
            <CartProvider>
              <OrdersProvider>
                <AddressProvider>
                  <ToastProvider>
                    <CheckoutScreen back={back} push={() => {}} />
                  </ToastProvider>
                </AddressProvider>
              </OrdersProvider>
            </CartProvider>
          </AssistantProvider>
        </ProfileProvider>
      </DemoProvider>,
    )
    expect(screen.getByText('Tu carro está vacío.')).toBeTruthy()
    fireEvent.click(screen.getByText('Seguir comprando'))
    expect(back).toHaveBeenCalled()
  })
})
