import { StrictMode, useState } from 'react'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
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
import { setPro } from '../../state/pro'
import { addCredits, readWallet } from '../../state/credits'
import CheckoutScreen from './CheckoutScreen'
import { forgetAge } from './restrictions'

const api = vi.hoisted(() => ({ health: vi.fn(), sendOrder: vi.fn() }))
vi.mock('../../api/client', async (importOriginal) => ({ ...(await importOriginal()), ...api }))
// Lo que trae /catalog/terms de cada tienda, por test (sin entrada: la API no la conoce y van los supuestos).
const terms = vi.hoisted(() => ({ byStore: {} }))
vi.mock('../../api/catalog', async (importOriginal) => ({
  ...(await importOriginal()),
  storeTerms: async (ids) => new Map(ids.map((id) => [id, terms.byStore[id] ?? null])),
}))
// La ventana de «Deshacer pedido»: 0 en los tests (sale de inmediato), salvo en los que la prueban.
const undo = vi.hoisted(() => ({ UNDO_MS: 0 }))
vi.mock('./undo', () => undo)
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

// Un producto de Licores (+18) y uno del Súper: el carro va en dos pedidos, uno por tienda.
// Ambos salen de las respuestas de ejemplo de la API, con su tipo e id reales.
const BEER = toPrototypeProduct(fixture('search-grouped').groups[0].products[0])
const OIL = toPrototypeProduct(fixture('catalog-store').products[0])
const NO_MINIMUM = { deliveryFee: null, minOrder: 0, servicePct: null }

/** Llena el carro con `products` y abre el checkout, como al tocar la barra del carrito. */
function Harness({ products, push }) {
  const cart = useCart()
  const [open, setOpen] = useState(false)
  if (open) return <CheckoutScreen back={() => setOpen(false)} push={push} />
  return (
    <button
      type="button"
      onClick={() => {
        products.forEach((product) => cart.add(product))
        setOpen(true)
      }}
    >
      ir a pagar
    </button>
  )
}

function renderCheckout(products = [BEER, OIL], push = () => {}) {
  render(
    <StrictMode>
      <DemoProvider>
        <ProfileProvider>
          <AssistantProvider>
            <CartProvider>
              <OrdersProvider>
                <AddressProvider>
                  <ToastProvider>
                    <Harness products={products} push={push} />
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
const placeButton = () => screen.getByRole('button', { name: /^Hacer pedido/ })

/** «Hacer pedido» y, si pregunta la edad, «Sí». Con la ventana de deshacer en 0, el pedido sale solo. */
async function pay() {
  await act(tick) // las condiciones de las tiendas (/catalog/terms)
  fireEvent.click(placeButton())
  const yes = screen.queryByText('Sí, soy mayor de edad')
  if (yes) fireEvent.click(yes)
}

const checkoutStarts = () =>
  events.track.mock.calls.filter(([type]) => type === 'checkout_start').map(([, fields]) => fields)

beforeEach(() => {
  api.health.mockResolvedValue({ voz: false })
  api.sendOrder.mockResolvedValue({})
  terms.byStore = { [BEER.storeId]: NO_MINIMUM, [OIL.storeId]: NO_MINIMUM }
  undo.UNDO_MS = 0
})
afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  localStorage.clear()
  sessionStorage.clear()
  forgetAge()
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
    await pay()
    await vi.waitFor(() => expect(api.sendOrder).toHaveBeenCalledTimes(2))
    expect(checkoutStarts()).toHaveLength(2)
  })

  test('el pedido guardado lleva el tipo y el id de cada línea (con ellos Mochi arma el próximo pedido)', async () => {
    renderCheckout()
    await pay()
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
    await pay()
    await act(tick)
    expect(api.sendOrder).not.toHaveBeenCalled()

    queued.resolve()
    await tick()
    expect(api.sendOrder).not.toHaveBeenCalled()

    inFlight.resolve()
    await vi.waitFor(() => expect(api.sendOrder).toHaveBeenCalledTimes(2))
  })
})

describe('un pedido por tienda', () => {
  test('dos tiendas: «dividida en 2 pedidos», un POST por tienda y cada uno con sus líneas', async () => {
    const dish = toPrototypeProduct(fixture('catalog-menu').sections[0].items[0])
    const other = { ...dish, id: 'menu-otro', entityId: '98010', storeId: dish.storeId + 2, store: 'Otro local' }
    terms.byStore = { [dish.storeId]: NO_MINIMUM, [other.storeId]: NO_MINIMUM }
    renderCheckout([dish, other])
    expect(screen.getByText(/Tu compra será dividida en 2 pedidos/)).toBeTruthy()
    await pay()
    await vi.waitFor(() => expect(api.sendOrder).toHaveBeenCalledTimes(2))
    const sent = api.sendOrder.mock.calls.map(([order]) => order)
    expect(sent.map((order) => order.vertical)).toEqual(['restaurantes', 'restaurantes'])
    expect(sent.map((order) => order.lines.map((line) => line.store_id))).toEqual([[dish.storeId], [other.storeId]])
  })
})

describe('Mis pedidos: un pedido de la demo por tienda', () => {
  test('dos tiendas son dos pedidos guardados, con su tienda y su vertical, que suman el total del checkout', async () => {
    renderCheckout()
    await act(tick)
    const total = screen.getByText('Total').nextSibling.textContent
    await pay()
    await vi.waitFor(() => expect(api.sendOrder).toHaveBeenCalledTimes(2))
    const saved = JSON.parse(localStorage.getItem('rappi-proto-orders'))
    expect(saved).toHaveLength(2)
    expect(saved.map((order) => order.vertical).sort()).toEqual(['licores', 'supermercado'])
    expect(saved.map((order) => order.storeId).sort()).toEqual([BEER.storeId, OIL.storeId].sort())
    expect(new Set(saved.map((order) => order.cartId)).size).toBe(1)
    expect(saved.every((order) => order.items.length === 1)).toBe(true)
    const sum = saved.reduce((acc, order) => acc + order.total, 0)
    expect(`$${sum.toLocaleString('es-CL')}`).toBe(total)
  })
})

describe('si un producto se agota (Súper y Turbo)', () => {
  test('el Súper pregunta por línea; la elección va en la línea del pedido y la de Licores no pregunta', async () => {
    renderCheckout()
    await act(tick)
    expect(screen.queryByLabelText(`Si se agota ${BEER.name}`)).toBeNull()
    const select = screen.getByLabelText(`Si se agota ${OIL.name}`)
    expect(select.value).toBe('elijan') // por defecto, «Si no contesto, elijan por mí»
    fireEvent.change(select, { target: { value: 'reembolso' } })
    await pay()
    await vi.waitFor(() => expect(api.sendOrder).toHaveBeenCalledTimes(2))
    const sent = Object.fromEntries(api.sendOrder.mock.calls.map(([order]) => [order.vertical, order]))
    expect(sent.supermercado.lines[0].substitution).toBe('reembolso')
    expect(sent.licores.lines[0].substitution).toBeUndefined()
    const saved = JSON.parse(localStorage.getItem('rappi-proto-orders'))
    expect(saved.find((order) => order.vertical === 'supermercado').items[0].substitution).toBe('reembolso')
  })
})

describe('entrega: tipo y programar', () => {
  test('«Prioritaria» suma su monto de ejemplo y va en el pedido', async () => {
    renderCheckout([OIL])
    await act(tick)
    const before = screen.getByText('Total').nextSibling.textContent
    fireEvent.click(screen.getByRole('radio', { name: /Prioritaria/ }))
    expect(screen.getByText('Entrega prioritaria (de ejemplo)')).toBeTruthy()
    expect(screen.getByText('Total').nextSibling.textContent).not.toBe(before)
    await pay()
    await vi.waitFor(() => expect(api.sendOrder).toHaveBeenCalledTimes(1))
    expect(api.sendOrder.mock.calls[0][0]).toMatchObject({ delivery_type: 'prioritaria' })
    expect(api.sendOrder.mock.calls[0][0].scheduled_for).toBeUndefined()
  })

  test('programar: la franja va en el pedido, y deshacer vuelve al checkout con la franja elegida', async () => {
    undo.UNDO_MS = 60_000
    renderCheckout([OIL])
    await act(tick)
    fireEvent.click(screen.getByRole('radio', { name: 'Programar' }))
    const slots = screen.getAllByRole('radio', { name: /^(hoy|mañana) \d\d:00–\d\d:00$/ })
    expect(slots.length).toBeGreaterThan(0)
    fireEvent.click(slots[1])
    await pay()
    expect(screen.getByText(/Programado para (hoy|mañana)/, { selector: '.checkout-sheet p' })).toBeTruthy()
    fireEvent.click(screen.getByText('Deshacer pedido'))
    await act(tick)
    expect(api.sendOrder).not.toHaveBeenCalled()
    expect(screen.getAllByRole('radio', { name: /^(hoy|mañana)/ })[1].getAttribute('aria-checked')).toBe('true')

    undo.UNDO_MS = 0
    fireEvent.click(placeButton())
    await vi.waitFor(() => expect(api.sendOrder).toHaveBeenCalledTimes(1))
    const sent = api.sendOrder.mock.calls[0][0]
    expect(new Date(sent.scheduled_for).getMinutes()).toBe(0)
    expect(sent.delivery_type).toBe('basica')
    const [saved] = JSON.parse(localStorage.getItem('rappi-proto-orders'))
    expect(saved.scheduledFor).toBe(new Date(sent.scheduled_for).getTime())
  })

  test('con la tienda cerrada solo se programa: «Ahora» no se puede y pide una franja', async () => {
    terms.byStore[OIL.storeId] = { ...NO_MINIMUM, hours: { source: 'descarga', open: false }, spans: null }
    renderCheckout([OIL])
    await act(tick)
    expect(screen.getByText('La tienda está cerrada pero puedes programar tu pedido.')).toBeTruthy()
    expect(screen.getByRole('radio', { name: 'Ahora' }).disabled).toBe(true)
    expect(placeButton().disabled).toBe(true)
    fireEvent.click(screen.getByRole('radio', { name: 'Programar' }))
    // Cerrada en la descarga y sin hora de apertura: las franjas son de mañana.
    expect(
      screen.getAllByRole('radio', { name: /^(hoy|mañana)/ }).every((slot) => /^mañana/.test(slot.textContent)),
    ).toBe(true)
    expect(placeButton().disabled).toBe(false)
  })
})

describe('compra mínima y envío por tienda', () => {
  test('bajo la compra mínima no se puede pedir: «Te faltan $X para hacer el pedido»', async () => {
    terms.byStore[OIL.storeId] = { deliveryFee: null, minOrder: 8490, servicePct: null }
    renderCheckout()
    await act(tick)
    expect(screen.getAllByText('Te faltan $5.300 para hacer el pedido').length).toBeGreaterThan(0)
    expect(screen.getByText(/Te faltan \$5\.300 para hacer el pedido en Supermercado de prueba Centro/)).toBeTruthy()
    expect(placeButton().disabled).toBe(true)
    fireEvent.click(placeButton())
    await tick()
    expect(api.sendOrder).not.toHaveBeenCalled()
  })

  test('sin dato del catálogo el mínimo y el envío son supuestos rotulados', async () => {
    terms.byStore = {}
    renderCheckout([OIL, OIL, OIL])
    await act(tick)
    expect(screen.getAllByText(/mínimo de ejemplo/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/envío de ejemplo/).length).toBeGreaterThan(0)
  })

  test('el envío real de un restaurante (delivery_cost) va en su canasta y en el total', async () => {
    const dish = toPrototypeProduct(fixture('catalog-menu').sections[0].items[0])
    terms.byStore = { [dish.storeId]: { deliveryFee: 1490, minOrder: null, servicePct: null } }
    renderCheckout([dish])
    await act(tick)
    expect(screen.getByText(/^Envío \$1\.490/)).toBeTruthy()
    expect(screen.queryByText(/envío de ejemplo/)).toBeNull()
  })
})

describe('Rappi Pro', () => {
  test('sin Pro: se cobra el envío y se ofrece «Ahorra $X con Pro»; el pedido dice que no es Pro', async () => {
    renderCheckout([OIL, OIL, OIL, OIL])
    await act(tick)
    expect(screen.getByText(/^Ahorra \$.* con Pro$/)).toBeTruthy()
    await pay()
    await vi.waitFor(() => expect(api.sendOrder).toHaveBeenCalledTimes(1))
    expect(api.sendOrder.mock.calls[0][0].pro).toBe(false)
  })

  test('con Pro: envío gratis sobre el mínimo Pro; bajo él, «Te faltan $X para envío gratis con Pro»', async () => {
    setPro(true)
    renderCheckout([OIL, OIL, OIL, OIL, BEER]) // $12.760 en el súper y $1.190 en la botillería
    await act(tick)
    expect(screen.getByText(/Envío gratis con Pro/)).toBeTruthy()
    expect(screen.getByText('Te faltan $8.810 para envío gratis con Pro')).toBeTruthy()
    await pay()
    await vi.waitFor(() => expect(api.sendOrder).toHaveBeenCalledTimes(2))
    expect(api.sendOrder.mock.calls.every(([order]) => order.pro === true)).toBe(true)
  })
})

describe('créditos y cupones de ejemplo', () => {
  test('los créditos del banner se descuentan del total y se pueden apagar', async () => {
    renderCheckout([OIL])
    await act(tick)
    expect(screen.getByText('−$1.900')).toBeTruthy()
    const total = () => screen.getByText('Total').nextSibling.textContent
    const withCredits = total()
    fireEvent.click(screen.getByRole('switch', { name: 'Usar créditos' }))
    expect(screen.queryByText('−$1.900')).toBeNull()
    expect(total()).not.toBe(withCredits)
  })

  test('un cupón a la vez: el del súper aplica, otro lo reemplaza y uno de otra tienda «no aplica para esta tienda»', async () => {
    renderCheckout([OIL, OIL, OIL, OIL])
    await act(tick)
    fireEvent.click(screen.getByRole('button', { name: 'SUPER20' }))
    expect(screen.getByText('Cupón SUPER20')).toBeTruthy()
    expect(screen.getByText('−$2.550')).toBeTruthy() // 20 % de $12.760
    fireEvent.change(screen.getByLabelText('Código del cupón'), { target: { value: 'bienvenida' } })
    fireEvent.click(screen.getByText('Aplicar'))
    expect(screen.getByText(/Reemplazó a SUPER20/)).toBeTruthy()
    expect(screen.queryByText('Cupón SUPER20')).toBeNull()
    expect(screen.getByText('Cupón BIENVENIDA')).toBeTruthy()
  })

  test('los créditos usados salen del saldo: el pedido siguiente ya no los tiene', async () => {
    renderCheckout([OIL])
    await pay()
    await vi.waitFor(() => expect(api.sendOrder).toHaveBeenCalled())
    const [order] = JSON.parse(localStorage.getItem('rappi-proto-orders'))
    expect(order.credits).toBe(1_900)
    expect(readWallet()).toMatchObject({ welcome: 0, extra: 0 })
    cleanup()
    renderCheckout([OIL])
    await act(tick)
    expect(screen.queryByText('−$1.900')).toBeNull()
    expect(screen.getByText('Ya los usaste o vencieron: no te quedan créditos')).toBeTruthy()
    expect(screen.getByRole('switch', { name: 'Usar créditos' }).disabled).toBe(true)
  })

  test('los créditos que sumó la ayuda o una cancelación se usan en el checkout', async () => {
    addCredits(1_000)
    renderCheckout([OIL])
    await act(tick)
    expect(screen.getByText('$2.900 en créditos de ejemplo')).toBeTruthy()
    expect(screen.getByText('−$2.900')).toBeTruthy()
  })

  test('un cupón se usa una vez', async () => {
    renderCheckout([OIL, OIL, OIL, OIL])
    await act(tick)
    fireEvent.click(screen.getByRole('button', { name: 'BIENVENIDA' }))
    await pay()
    await vi.waitFor(() => expect(api.sendOrder).toHaveBeenCalled())
    const [order] = JSON.parse(localStorage.getItem('rappi-proto-orders'))
    expect(order.coupon).toEqual({ code: 'BIENVENIDA', amount: 2_000 })
    expect(readWallet().coupons).toEqual(['BIENVENIDA'])
    cleanup()
    renderCheckout([OIL, OIL, OIL, OIL])
    await act(tick)
    fireEvent.click(screen.getByRole('button', { name: 'BIENVENIDA' }))
    expect(screen.getByText('Ya usaste este cupón de ejemplo: se usa una vez')).toBeTruthy()
    expect(screen.queryByText('Cupón BIENVENIDA')).toBeNull()
  })

  test('el cupón de Supermercado en un carro sin súper no descuenta nada', async () => {
    const dish = toPrototypeProduct(fixture('catalog-menu').sections[0].items[0])
    terms.byStore = { [dish.storeId]: NO_MINIMUM }
    renderCheckout([dish])
    await act(tick)
    fireEvent.click(screen.getByRole('button', { name: 'SUPER20' }))
    expect(screen.getByText('Este cupón no aplica para esta tienda')).toBeTruthy()
    expect(screen.queryByText('Cupón SUPER20')).toBeNull()
  })
})

describe('restricciones al pagar', () => {
  test('con un producto +18 pregunta la edad una vez por sesión', async () => {
    renderCheckout()
    await act(tick)
    fireEvent.click(placeButton())
    expect(screen.getByText('Sí, soy mayor de edad')).toBeTruthy()
    expect(api.sendOrder).not.toHaveBeenCalled()
    fireEvent.click(screen.getByText('Sí, soy mayor de edad'))
    await vi.waitFor(() => expect(api.sendOrder).toHaveBeenCalledTimes(2))
    cleanup()

    renderCheckout()
    await act(tick)
    fireEvent.click(placeButton())
    expect(screen.queryByText('Sí, soy mayor de edad')).toBeNull() // ya respondió en esta sesión
    await vi.waitFor(() => expect(api.sendOrder).toHaveBeenCalledTimes(4))
  })

  test('si no es mayor de edad no se pide; puede quitar los productos +18', async () => {
    renderCheckout()
    await act(tick)
    fireEvent.click(placeButton())
    fireEvent.click(screen.getByText('No'))
    fireEvent.click(screen.getByText('Quitar los productos +18'))
    expect(screen.queryByText(BEER.name)).toBeNull()
    expect(screen.getAllByText(OIL.name).length).toBeGreaterThan(0)
    const removes = events.track.mock.calls.filter(([type]) => type === 'cart_remove')
    expect(removes.map(([, fields]) => fields.entity_id)).toEqual([BEER.entityId])
    expect(api.sendOrder).not.toHaveBeenCalled()
  })

  test('con productos de Farmacia pide marcar «Tengo la receta médica» antes de pedir', async () => {
    const pill = { ...OIL, id: 'cat-farma', entityId: '95001', storeId: 9501, store: 'Farmacia', vertical: 'pharmacy' }
    pill.backendVertical = 'farmacia'
    terms.byStore = { 9501: NO_MINIMUM }
    renderCheckout([pill])
    await act(tick)
    expect(placeButton().disabled).toBe(true)
    expect(screen.getByText('Marca que tienes la receta médica para seguir')).toBeTruthy()
    fireEvent.click(screen.getByLabelText(/Tengo la receta médica/))
    expect(placeButton().disabled).toBe(false)
    await pay()
    await vi.waitFor(() => expect(api.sendOrder).toHaveBeenCalledTimes(1))
  })
})

describe('deshacer pedido', () => {
  test('en la ventana de deshacer no sale nada; deshacer vuelve al checkout con el carro', async () => {
    undo.UNDO_MS = 60_000
    const push = vi.fn()
    renderCheckout([OIL], push)
    await pay()
    expect(screen.getByText('¡Pedido creado!')).toBeTruthy()
    await act(tick)
    expect(api.sendOrder).not.toHaveBeenCalled()
    fireEvent.click(screen.getByText('Deshacer pedido'))
    await act(tick)
    expect(api.sendOrder).not.toHaveBeenCalled()
    expect(push).not.toHaveBeenCalled()
    expect(localStorage.getItem('rappi-proto-orders')).toBeNull()
    expect(screen.getAllByText(OIL.name).length).toBeGreaterThan(0)
  })

  test('pasada la ventana sale el pedido y abre su seguimiento', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    try {
      undo.UNDO_MS = 5000
      const push = vi.fn()
      renderCheckout([OIL], push)
      await act(() => vi.advanceTimersByTimeAsync(0))
      fireEvent.click(placeButton())
      await act(() => vi.advanceTimersByTimeAsync(4000))
      expect(push).not.toHaveBeenCalled()
      await act(() => vi.advanceTimersByTimeAsync(1000))
      expect(push).toHaveBeenCalledWith('tracking', expect.anything(), { swap: true })
      await vi.waitFor(() => expect(api.sendOrder).toHaveBeenCalledTimes(1))
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('pedidos en vuelo', () => {
  test('placing the order is tracked from the first wait until the last send ends', async () => {
    const inFlight = deferred() // un lote de eventos que ya había salido
    const sending = deferred() // el POST del pedido
    events.settled.mockReturnValueOnce(inFlight.promise)
    api.sendOrder.mockReturnValue(sending.promise)
    renderCheckout()
    await pay()
    await act(tick)

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
