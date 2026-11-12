// Los flujos del seguimiento de la fase 8: cancelar con rescate, programado, cambios en vivo del Súper, el atraso del
// "Panel de la demo", "Ayuda con este pedido" y la compra dividida en pedidos por tienda.
import { useState } from 'react'
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { fixture, stubApi } from '../../test/api'
import { ToastProvider } from '../../components/Toast'
import { AddressProvider } from '../../state/AddressContext'
import { AssistantProvider } from '../../state/AssistantContext'
import { CartProvider } from '../../state/CartContext'
import { DemoProvider } from '../../state/DemoContext'
import { resetQuiet } from '../../state/agentQuiet'
import { OrdersProvider, useOrders } from '../../state/OrdersContext'
import { markCoupon, readWallet, spendCredits } from '../../state/credits'
import { ProfileProvider } from '../../state/ProfileContext'
import { DEMO_DELAY_EVENT } from './delay'
import TrackingScreen from './TrackingScreen'

const events = vi.hoisted(() => ({ track: vi.fn(), flush: async () => {}, clear: () => {}, settled: async () => {} }))
vi.mock('../../state/EventsContext', async (importOriginal) => ({
  ...(await importOriginal()),
  useEvents: () => events,
}))

const PIZZA = {
  name: 'Pizza (prueba)',
  img: 'pizza.webp',
  price: '$10.000',
  qty: 1,
  entityType: 'menu_item',
  entityId: '95001',
  product: { id: 'menu-95001', entityId: '95001', entityType: 'menu_item', storeId: 9801, price: '$10.000' },
}
const RESTAURANT = {
  stores: ['Pizzería de prueba'],
  storeId: 9801,
  vertical: 'restaurantes',
  cartId: 'c-prueba',
  items: [PIZZA],
  total: 12_000,
  address: 'Av. La Plaza 630',
}
const PASTA = {
  name: 'Tallarines (prueba)',
  img: 'tallarines.webp',
  price: '$1.290',
  qty: 2,
  entityType: 'catalog_item',
  entityId: '91101',
  substitution: 'sustituto',
  product: { id: 'cat-91101', entityId: '91101', entityType: 'catalog_item', storeId: 9101, price: '$1.290' },
}
const SUPER = {
  ...RESTAURANT,
  stores: ['Supermercado de prueba Centro'],
  storeId: 9101,
  vertical: 'supermercado',
  items: [{ ...PASTA, vertical: 'grocery' }],
  total: 5_000,
}
const TURBO = {
  ...RESTAURANT,
  stores: ['Turbo de prueba'],
  storeId: 9301,
  vertical: 'turbo',
  items: [{ ...PASTA, vertical: 'turbo', substitution: undefined }],
  total: 6_500,
}

const push = vi.fn()
function Harness({ placed }) {
  const orders = useOrders()
  const order = orders.orders[0]
  if (!order)
    return (
      <button type="button" onClick={() => orders.placeMany(placed)}>
        pedir
      </button>
    )
  return <TrackingScreen back={() => {}} reset={() => {}} push={push} params={{ orderId: order.id }} />
}

function renderTracking(placed = [RESTAURANT]) {
  render(
    <DemoProvider>
      <ProfileProvider>
        <AssistantProvider>
          <CartProvider>
            <OrdersProvider>
              <AddressProvider>
                <ToastProvider>
                  <Harness placed={placed} />
                </ToastProvider>
              </AddressProvider>
            </OrdersProvider>
          </CartProvider>
        </AssistantProvider>
      </ProfileProvider>
    </DemoProvider>,
  )
  fireEvent.click(screen.getByText('pedir'))
}

const advance = (ms) => act(() => vi.advanceTimersByTimeAsync(ms))
const tracked = (type) => events.track.mock.calls.filter(([t]) => t === type).map(([, fields]) => fields)
const saved = () => JSON.parse(localStorage.getItem('rappi-proto-orders'))

let api
beforeEach(() => {
  vi.useFakeTimers({ now: new Date(2026, 9, 21, 12) })
  events.track.mockClear()
  push.mockClear()
  api = stubApi({
    'POST /agent/offer': 204,
    'GET /catalog/products/catalog_item/*': fixture('catalog-product-stores-agotado'),
  })
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  resetQuiet()
  localStorage.clear()
})

describe('cancelar con rescate', () => {
  test('antes de que la tienda empiece es gratis y registra order_cancelled con su tienda', async () => {
    renderTracking()
    await advance(1000)
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar pedido' }))
    expect(screen.getByText('¿Por qué quieres cancelar?')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Ya no lo necesito' }))
    expect(screen.getByText('Cancelarlo ahora no tiene costo.')).toBeTruthy()
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancelar pedido' }))

    expect(tracked('order_cancelled')).toEqual([
      {
        surface: 'tracking',
        cart_id: 'c-prueba',
        vertical: 'restaurantes',
        value: undefined,
        payload: { reason: 'ya_no', stage: 'antes_de_tienda', store_id: 9801 },
      },
    ])
    expect(screen.getByRole('heading', { name: 'Pedido cancelado' })).toBeTruthy()
    expect(screen.getByText('La tienda aún no lo empezaba: no tuvo costo.')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Cancelar pedido' })).toBeNull()
    expect(saved()[0].cancelled).toMatchObject({ reason: 'ya_no', stage: 'antes_de_tienda', fee: 0 })
    // Un pedido cancelado no llega: pasado su tiempo sigue cancelado.
    await advance(30_000)
    expect(screen.getByRole('heading', { name: 'Pedido cancelado' })).toBeTruthy()
  })

  test('ya empezado muestra el costo de ejemplo y lo manda con su supuesto', async () => {
    renderTracking()
    await advance(4000) // el restaurante ya prepara
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar pedido' }))
    fireEvent.click(screen.getByRole('button', { name: 'Está tardando mucho' }))
    expect(screen.getByText(/La tienda ya empezó tu pedido: cancelarlo cuesta \$3\.000/)).toBeTruthy()
    expect(screen.getByText(/Costo de ejemplo de la demo/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar pedido · $3.000' }))
    const [sent] = tracked('order_cancelled')
    expect(sent.payload).toEqual({ reason: 'demora', stage: 'en_tienda', store_id: 9801, fee: 3000, basis: 'supuesto' })
    expect(screen.getByText(/Costo de cancelación: \$3\.000 \(de ejemplo/)).toBeTruthy()
  })

  test('"Aún tiene solución": cambiar la dirección en vez de cancelar; mientras decide, el pedido espera', async () => {
    renderTracking()
    await advance(1000)
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar pedido' }))
    await advance(20_000) // la hoja abierta: el reloj de la demo espera
    fireEvent.click(screen.getByRole('button', { name: 'Me equivoqué de dirección' }))
    expect(screen.getByText('Aún tiene solución')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Entregar en Trabajo/ }))
    expect(tracked('order_cancelled')).toEqual([])
    expect(saved()[0].address).toBe('Av. Apoquindo 3000')
    expect(saved()[0].cancelled).toBeUndefined()
    // Siguió donde quedó: todavía se puede cancelar (no va en camino).
    expect(screen.getByRole('button', { name: 'Cancelar pedido' })).toBeTruthy()
  })

  test('"Continuar con la cancelación" después de la solución; en camino ya no se puede cancelar', async () => {
    renderTracking()
    await advance(1000)
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar pedido' }))
    fireEvent.click(screen.getByRole('button', { name: 'Quiero cambiar el medio de pago' }))
    expect(screen.getByRole('button', { name: /Pagar con Efectivo al recibir/ })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Continuar con la cancelación' }))
    expect(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancelar pedido' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Mantener mi pedido' }))

    await advance(10_000)
    expect(screen.queryByRole('button', { name: 'Cancelar pedido' })).toBeNull()
  })
})

describe('programado', () => {
  test('espera su franja, se cancela gratis y después sigue sus pasos', async () => {
    const at = new Date(2026, 9, 21, 15).getTime()
    renderTracking([{ ...RESTAURANT, scheduledFor: at }])
    await advance(1000)
    expect(screen.getByText('Programado para')).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'hoy 15:00–16:00' })).toBeTruthy()
    // Confirmado ya está hecho; sin ruta en el mapa hasta su franja.
    expect(screen.getByText('Pedido confirmado').closest('li').className).toBe('is-done')
    expect(document.querySelector('.tracking-route')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar pedido' }))
    fireEvent.click(screen.getByRole('button', { name: 'Otro motivo' }))
    expect(screen.getByText('Tu pedido aún no empieza: cancelarlo no tiene costo.')).toBeTruthy()
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancelar pedido' }))
    expect(tracked('order_cancelled')[0].payload.stage).toBe('programado')
  })
})

describe('cambios en vivo en el Súper', () => {
  test('"Tus productos te necesitan": el sustituto de la misma tienda y el ajuste en el total', async () => {
    renderTracking([SUPER])
    await advance(4000) // en tienda
    const alert = screen.getByRole('region', { name: 'Tus productos te necesitan' })
    expect(within(alert).getByText(/el agotado es simulado/)).toBeTruthy()
    // Lo que eligió en el checkout va marcado.
    expect(within(alert).getByRole('button', { name: /Elegir un sustituto.*lo elegiste en el checkout/ })).toBeTruthy()
    const [url] = api.mock.calls.find(([u]) => u.includes('/catalog/products/catalog_item/91101/stores'))
    expect(url).toContain('store_id=9101')
    expect(url).toContain('sustitutos=true')

    await advance(20_000) // el shopper espera la respuesta: no avanza
    expect(screen.queryByText('¡Disfruta tu pedido!')).toBeNull()

    fireEvent.click(within(alert).getByRole('button', { name: /Elegir un sustituto/ }))
    const first = within(alert).getAllByRole('button')[0]
    fireEvent.click(first)
    expect(screen.queryByRole('region', { name: 'Tus productos te necesitan' })).toBeNull()
    expect(screen.getByText(/Ajuste en el total/)).toBeTruthy()
    expect(saved()[0].liveChange).toMatchObject({ index: 0, choice: 'sustituto' })

    await advance(20_000)
    expect(screen.getByText('¡Disfruta tu pedido!')).toBeTruthy()
  })

  test('"Prefiero el reembolso" descuenta el producto', async () => {
    renderTracking([SUPER])
    await advance(4000)
    fireEvent.click(screen.getByRole('button', { name: /Prefiero el reembolso/ }))
    expect(screen.getByText('Tallarines (prueba): se agotó y te lo reembolsamos')).toBeTruthy()
    expect(screen.getByText('−$2.580')).toBeTruthy()
  })

  test('un restaurante no tiene cambios en vivo', async () => {
    renderTracking()
    await advance(4000)
    expect(screen.queryByRole('region', { name: 'Tus productos te necesitan' })).toBeNull()
  })
})

describe('atraso del "Panel de la demo"', () => {
  test('en Turbo: el tiempo sube, llega el mensaje y la garantía de ejemplo se paga en Créditos', async () => {
    renderTracking([TURBO])
    await advance(4000)
    const before = Number(screen.getByRole('heading', { level: 1 }).textContent.replace(/\D/g, ''))
    act(() => window.dispatchEvent(new Event(DEMO_DELAY_EVENT)))
    await advance(500)
    const notice = screen.getByRole('status', { name: 'Tu pedido viene atrasado' })
    expect(notice.textContent).toMatch(/viene atrasado unos 12 min/)
    expect(notice.textContent).toMatch(/te devolvemos \$6\.500 en Créditos de/)
    expect(notice.textContent).toMatch(/son de ejemplo, no reglas de Rappi/)
    expect(Number(screen.getByRole('heading', { level: 1 }).textContent.replace(/\D/g, ''))).toBeGreaterThan(before)
    // La garantía de ejemplo se suma al saldo de créditos de la demo (lo usa el próximo checkout), una sola vez.
    expect(readWallet().extra).toBe(6_500)
    act(() => window.dispatchEvent(new Event(DEMO_DELAY_EVENT)))
    expect(readWallet().extra).toBe(6_500)
    // Se queda en su paso unos segundos más: a los 20 s de la demo todavía no llega.
    await advance(16_000)
    expect(screen.queryByText('¡Disfruta tu pedido!')).toBeNull()
    await advance(10_000)
    expect(screen.getByText('¡Disfruta tu pedido!')).toBeTruthy()
  })

  test('fuera de Turbo solo el mensaje, sin Créditos', async () => {
    renderTracking()
    await advance(4000)
    act(() => window.dispatchEvent(new Event(DEMO_DELAY_EVENT)))
    await advance(500)
    expect(screen.getByRole('status', { name: 'Tu pedido viene atrasado' }).textContent).not.toMatch(/Créditos de/)
  })
})

describe('ayuda con este pedido', () => {
  test('productos y motivo, dónde va el reembolso y el plazo de ejemplo; no mueve dinero', async () => {
    renderTracking()
    await advance(21_000)
    fireEvent.click(screen.getByRole('button', { name: 'Ayuda con este pedido' }))
    const sheet = screen.getByRole('dialog', { name: 'Ayuda con este pedido' })
    expect(within(sheet).getByText(/plazo de ejemplo: 48 horas desde la entrega/)).toBeTruthy()
    expect(within(sheet).getByRole('button', { name: 'Siguiente' }).disabled).toBe(true)
    fireEvent.click(within(sheet).getByRole('button', { name: '1 × Pizza (prueba)' }))
    fireEvent.click(within(sheet).getByRole('button', { name: 'Llegó en mal estado' }))
    fireEvent.click(within(sheet).getByRole('button', { name: 'Siguiente' }))
    expect(within(sheet).getByText('¿Dónde reembolsamos tu dinero?')).toBeTruthy()
    fireEvent.click(within(sheet).getByRole('radio', { name: /Créditos de ejemplo/ }))
    fireEvent.click(within(sheet).getByRole('button', { name: 'Enviar solicitud' }))
    expect(within(sheet).getByRole('status').textContent).toMatch(/\$10\.000 en créditos de ejemplo, al instante/)
    expect(within(sheet).getByText(/no se mueve dinero/)).toBeTruthy()
    expect(saved()[0].help).toEqual([
      expect.objectContaining({ items: [0], reason: 'mal_estado', method: 'creditos', amount: 10_000 }),
    ])
    // El reembolso en créditos de ejemplo se suma al saldo de la demo.
    expect(readWallet().extra).toBe(10_000)
  })

  test('después de un sustituto, se reembolsa el sustituto que se cobró y no el agotado', async () => {
    renderTracking([SUPER])
    await advance(4000)
    const alert = screen.getByRole('region', { name: 'Tus productos te necesitan' })
    fireEvent.click(within(alert).getByRole('button', { name: /Elegir un sustituto/ }))
    fireEvent.click(within(alert).getAllByRole('button')[0])
    const { product } = saved()[0].liveChange
    await advance(21_000)
    fireEvent.click(screen.getByRole('button', { name: 'Ayuda con este pedido' }))
    const sheet = screen.getByRole('dialog', { name: 'Ayuda con este pedido' })
    expect(within(sheet).queryByRole('button', { name: '2 × Tallarines (prueba)' })).toBeNull()
    fireEvent.click(within(sheet).getByRole('button', { name: `2 × ${product.name}` }))
    fireEvent.click(within(sheet).getByRole('button', { name: 'No llegó' }))
    fireEvent.click(within(sheet).getByRole('button', { name: 'Siguiente' }))
    const charged = 2 * Number(product.price.replace(/\D/g, ''))
    expect(saved()[0].liveChange.delta).toBe(charged - 2_580)
    expect(within(sheet).getByText(`$${charged.toLocaleString('es-CL')}`, { exact: false })).toBeTruthy()
  })

  test('con el producto reembolsado en vivo, ya no aparece para pedir ayuda', async () => {
    renderTracking([SUPER])
    await advance(4000)
    fireEvent.click(screen.getByRole('button', { name: /Prefiero el reembolso/ }))
    await advance(21_000)
    fireEvent.click(screen.getByRole('button', { name: 'Ayuda con este pedido' }))
    const sheet = screen.getByRole('dialog', { name: 'Ayuda con este pedido' })
    expect(
      within(within(sheet).getByRole('group', { name: 'Productos con problemas' })).queryAllByRole('button'),
    ).toEqual([])
  })
})

describe('créditos y cupón de un pedido cancelado', () => {
  test('vuelven al saldo de la demo: los créditos se suman y el cupón se puede volver a usar', async () => {
    spendCredits(1_000)
    markCoupon('BIENVENIDA')
    renderTracking([{ ...RESTAURANT, credits: 1_000, coupon: { code: 'BIENVENIDA', amount: 2_000 } }])
    await advance(1000)
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar pedido' }))
    fireEvent.click(screen.getByRole('button', { name: 'Ya no lo necesito' }))
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancelar pedido' }))
    expect(readWallet().extra).toBe(1_000)
    expect(readWallet().coupons).toEqual([])
  })
})

describe('la pausa de "Cancelar pedido"', () => {
  test('si el paso cambia justo al abrir la hoja, el pedido no queda detenido', async () => {
    renderTracking()
    await advance(8_500) // el último tic del reloj fue a los 8 s: todavía se puede cancelar
    vi.setSystemTime(Date.now() + 1_000) // el reloj real ya pasó a "En camino", sin tic todavía
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar pedido' }))
    await advance(0)
    expect(saved()[0].heldAt).toBeUndefined()
    await advance(1000) // con el tic, ya va en camino: no se cancela
    expect(screen.queryByRole('button', { name: 'Cancelar pedido' })).toBeNull()
    await advance(15_000)
    expect(screen.getByText('¡Disfruta tu pedido!')).toBeTruthy()
  })

  test('al recargar con la hoja abierta, el pedido sigue su reloj', async () => {
    renderTracking()
    await advance(1000)
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar pedido' }))
    expect(saved()[0]).toMatchObject({ heldBy: 'cancelar' })
    const stored = localStorage.getItem('rappi-proto-orders')
    cleanup()
    localStorage.setItem('rappi-proto-orders', stored) // lo que quedó guardado al recargar, con la pausa
    render(
      <OrdersProvider>
        <Saved />
      </OrdersProvider>,
    )
    expect(saved()[0].heldAt).toBeUndefined()
    expect(saved()[0].pausedMs).toBeGreaterThanOrEqual(0)
  })
})

describe('pasar de un pedido a otro de la misma compra', () => {
  test('la calificación de un pedido no aparece marcada en el otro', async () => {
    function Switcher() {
      const orders = useOrders()
      const [index, setIndex] = useState(0)
      const order = orders.orders[index]
      if (!order)
        return (
          <button type="button" onClick={() => orders.placeMany([RESTAURANT, SUPER])}>
            pedir
          </button>
        )
      return (
        <>
          <button type="button" onClick={() => setIndex(1)}>
            otro
          </button>
          <TrackingScreen back={() => {}} reset={() => {}} push={push} params={{ orderId: order.id }} />
        </>
      )
    }
    render(
      <DemoProvider>
        <ProfileProvider>
          <AssistantProvider>
            <CartProvider>
              <OrdersProvider>
                <AddressProvider>
                  <ToastProvider>
                    <Switcher />
                  </ToastProvider>
                </AddressProvider>
              </OrdersProvider>
            </CartProvider>
          </AssistantProvider>
        </ProfileProvider>
      </DemoProvider>,
    )
    fireEvent.click(screen.getByText('pedir'))
    await advance(21_000)
    fireEvent.click(screen.getByRole('radio', { name: '2 estrellas' }))
    expect(screen.getByRole('radio', { name: '2 estrellas' }).getAttribute('aria-checked')).toBe('true')
    fireEvent.click(screen.getByText('otro'))
    expect(screen.getByRole('radio', { name: '2 estrellas' }).getAttribute('aria-checked')).toBe('false')
  })
})

// Lee los pedidos del proveedor (y los guarda, como al cambiar algo).
function Saved() {
  const orders = useOrders()
  orders.orders.length && localStorage.setItem('rappi-proto-orders', JSON.stringify(orders.orders))
  return null
}

describe('una compra en dos tiendas', () => {
  test('cada pedido tiene su seguimiento y se pasa de uno a otro; la calificación dice su tienda', async () => {
    renderTracking([RESTAURANT, SUPER])
    const nav = screen.getByRole('navigation', { name: 'Tus pedidos de esta compra' })
    expect(
      within(nav)
        .getAllByRole('button')
        .map((b) => b.textContent),
    ).toEqual(['Pedido 1 · Pizzería de prueba', 'Pedido 2 · Supermercado de prueba Centro'])
    fireEvent.click(within(nav).getByRole('button', { name: /Pedido 2/ }))
    expect(push).toHaveBeenCalledWith('tracking', { orderId: saved()[1].id }, { swap: true })

    await advance(21_000)
    fireEvent.click(screen.getByRole('radio', { name: '5 estrellas' }))
    expect(tracked('order_rated')).toEqual([
      {
        surface: 'tracking',
        cart_id: 'c-prueba',
        vertical: 'restaurantes',
        payload: { stars: 5, reasons: [], store_id: 9801 },
      },
    ])
  })
})
