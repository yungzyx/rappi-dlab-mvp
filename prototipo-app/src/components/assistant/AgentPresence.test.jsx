import { useEffect } from 'react'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { AssistantProvider, useAssistant } from '../../state/AssistantContext'
import { CartProvider, formatPrice, useCart } from '../../state/CartContext'
import { DemoProvider } from '../../state/DemoContext'
import { stubApi } from '../../test/api'
import { AGENT_DRAG_TYPE } from '../../assistant/agentAsk'
import { AGENT_CART_EVENT, resetLive } from '../../state/liveMemory'
import { QUIET_KEY, resetQuiet } from '../../state/agentQuiet'
import { ProfileProvider } from '../../state/ProfileContext'
import { today } from '../../utils/today'
import AgentPresence, { SIDE_KEY } from './AgentPresence'

const events = vi.hoisted(() => ({ track: vi.fn(), flush: async () => {}, clear: () => {}, settled: async () => {} }))
vi.mock('../../state/EventsContext', async (importOriginal) => ({
  ...(await importOriginal()),
  useEvents: () => events,
}))

const BEER = { id: 'b1', name: 'Cerveza Escudo 470 cc', price: '$1.380', vertical: 'liquor', store: 'Botillería' }

// Lo que el componente de prueba ve de los contextos, para actuar sobre ellos desde el test.
const probe = {}
function Probe() {
  const assistant = useAssistant()
  const cart = useCart()
  useEffect(() => {
    probe.assistant = assistant
    probe.cart = cart
  })
  return null
}

const tree = (props = {}) => (
  <DemoProvider>
    <ProfileProvider>
      <AssistantProvider>
        <CartProvider>
          <div className="phone">
            <Probe />
            <AgentPresence screen="vertical" homeTab="home" push={vi.fn()} raised={false} {...props} />
          </div>
        </CartProvider>
      </AssistantProvider>
    </ProfileProvider>
  </DemoProvider>
)
const mountTree = (props) => render(tree(props))
const agentButton = () => screen.queryByRole('button', { name: 'Mochi: ayuda y opciones' })

beforeEach(() => {
  localStorage.setItem('rappi-proto-demo-mode', 'final')
  stubApi({})
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  resetQuiet()
  localStorage.clear()
})

const added = (product) => act(() => window.dispatchEvent(new CustomEvent(AGENT_CART_EVENT, { detail: { product } })))
const bubble = () => document.querySelector('.agent-bubble')

describe('Mochi y el carro', () => {
  test('al agregar dice «¡Listo! … está en tu carrito» y se va a los 4 s', async () => {
    vi.useFakeTimers()
    mountTree()
    added(BEER)
    expect(bubble().textContent).toContain(`¡Listo! ${BEER.name} está en tu carrito.`)
    act(() => vi.advanceTimersByTime(4000))
    expect(bubble()).toBeNull()
  })

  test('«Deshacer» quita el producto', async () => {
    mountTree()
    act(() => probe.cart.add(BEER))
    added(BEER)
    fireEvent.click(screen.getByRole('button', { name: 'Deshacer' }))
    expect(probe.cart.count).toBe(0)
    expect(bubble()).toBeNull()
  })

  test('silenciado no dice nada', async () => {
    localStorage.setItem(QUIET_KEY, today())
    mountTree()
    added(BEER)
    expect(bubble()).toBeNull()
  })

  test('cerrar el globo cuenta como ignorarlo: a la segunda, se calla', async () => {
    mountTree()
    for (let i = 0; i < 2; i++) {
      added(BEER)
      fireEvent.click(screen.getByRole('button', { name: 'Cerrar' }))
    }
    added(BEER)
    expect(bubble()).toBeNull()
  })
})

describe('Mochi flotante', () => {
  test('aparece en una vertical y no en la Home, el checkout ni el seguimiento', async () => {
    mountTree()
    expect(agentButton()).toBeTruthy()
    for (const screenName of ['home', 'checkout', 'tracking']) {
      cleanup()
      mountTree({ screen: screenName, homeTab: 'home' })
      expect(agentButton(), screenName).toBeNull()
    }
  })

  test('en las otras pestañas de la Home sí aparece', async () => {
    mountTree({ screen: 'home', homeTab: 'offers' })
    expect(agentButton()).toBeTruthy()
  })

  test('en «Rappi hoy» no aparece', async () => {
    localStorage.setItem('rappi-proto-demo-mode', 'actual')
    mountTree()
    expect(agentButton()).toBeNull()
  })

  test('con el buscador con Mochi abierto no aparece', async () => {
    mountTree()
    act(() => probe.assistant.open())
    expect(agentButton()).toBeNull()
  })

  test('tocarlo salta y abre el menú con sus 4 opciones; Escape lo cierra', async () => {
    const { container } = mountTree()
    fireEvent.pointerDown(agentButton())
    fireEvent.click(agentButton())
    expect(container.querySelector('.agent-presence .mascot').classList).toContain('mascot--jump')
    expect(agentButton().getAttribute('aria-expanded')).toBe('true')
    for (const name of ['Buscar con Mochi', '¿Qué puedo probar?', 'Mover a la izquierda', 'Silenciar por hoy'])
      expect(screen.getByRole('button', { name })).toBeTruthy()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('group', { name: 'Opciones de Mochi' })).toBeNull()
    expect(document.activeElement).toBe(agentButton())
  })

  test('«¿Qué puedo probar?» abre el buscador con la oferta de la vertical por probar, sin contexto', async () => {
    mountTree()
    fireEvent.click(agentButton())
    fireEvent.click(screen.getByRole('button', { name: '¿Qué puedo probar?' }))
    expect(probe.assistant.isOpen).toBe(true)
    expect(probe.assistant.session.offer).toEqual({ moment: 'vertical_por_probar', context: {} })
    expect(probe.assistant.session.query).toBe('Muéstrame algo nuevo para probar')
  })

  test('con carro, la segunda opción es revisarlo con el total', async () => {
    mountTree()
    act(() => probe.cart.add(BEER))
    fireEvent.click(agentButton())
    expect(screen.getByRole('button', { name: `Revisar mi carrito · ${formatPrice(probe.cart.total)}` })).toBeTruthy()
  })

  test('«Mover a la izquierda» lo cambia de lado y lo recuerda', async () => {
    const { container } = mountTree()
    fireEvent.click(agentButton())
    fireEvent.click(screen.getByRole('button', { name: 'Mover a la izquierda' }))
    expect(container.querySelector('.agent-presence').classList).toContain('is-left')
    expect(localStorage.getItem(SIDE_KEY)).toBe('left')
    cleanup()
    const again = mountTree()
    expect(again.container.querySelector('.agent-presence').classList).toContain('is-left')
  })

  test('arrastrarlo más allá de la mitad del teléfono lo deja en ese lado, sin abrir el menú', async () => {
    const { container } = mountTree()
    container.querySelector('.phone').getBoundingClientRect = () => ({ left: 0, width: 400, top: 0, height: 800 })
    const body = agentButton()
    fireEvent.pointerDown(body, { clientX: 360, pointerId: 1 })
    fireEvent.pointerMove(body, { clientX: 200, pointerId: 1 })
    fireEvent.pointerUp(body, { clientX: 40, pointerId: 1 })
    fireEvent.click(body)
    expect(container.querySelector('.agent-presence').classList).toContain('is-left')
    expect(screen.queryByRole('group', { name: 'Opciones de Mochi' })).toBeNull()
  })

  test('«Silenciar por hoy» lo deja como pestañita y tocarla lo despierta', async () => {
    const { container } = mountTree()
    fireEvent.click(agentButton())
    fireEvent.click(screen.getByRole('button', { name: 'Silenciar por hoy' }))
    expect(container.querySelector('.agent-presence').classList).toContain('is-quiet')
    const tab = screen.getByRole('button', { name: 'Mochi está en silencio: tocar para despertarlo' })
    fireEvent.click(tab)
    expect(container.querySelector('.agent-presence').classList).not.toContain('is-quiet')
    expect(agentButton()).toBeTruthy()
  })

  test('soltar una tarjeta sobre Mochi pregunta por ese producto', async () => {
    mountTree()
    const data = { [AGENT_DRAG_TYPE]: JSON.stringify(BEER) }
    const dataTransfer = { types: [AGENT_DRAG_TYPE], getData: (type) => data[type] ?? '' }
    fireEvent.dragOver(agentButton(), { dataTransfer })
    fireEvent.drop(agentButton(), { dataTransfer })
    expect(probe.assistant.session.query).toBe(`¿Con qué acompaño ${BEER.name}?`)
    expect(probe.assistant.session.product).toMatchObject({ name: BEER.name }) // el panel pide su complemento a la API
  })

  test('en silencio queda a la misma altura: sobre el carro y la barra inferior, sin taparlos', async () => {
    localStorage.setItem(QUIET_KEY, today())
    const { container } = mountTree({ raised: true })
    act(() => probe.cart.add(BEER))
    const classes = container.querySelector('.agent-presence').classList
    expect(classes).toContain('is-quiet')
    expect(classes).toContain('has-cart')
    expect(classes).toContain('is-raised')
  })

  test('«Repetir escena» lo despierta', async () => {
    localStorage.setItem(QUIET_KEY, today())
    const { container } = mountTree()
    expect(container.querySelector('.agent-presence').classList).toContain('is-quiet')
    act(() => resetLive())
    expect(container.querySelector('.agent-presence').classList).not.toContain('is-quiet')
  })

  test('«Buscar con Mochi» abre el buscador', async () => {
    mountTree()
    fireEvent.click(agentButton())
    fireEvent.click(screen.getByRole('button', { name: 'Buscar con Mochi' }))
    expect(probe.assistant.isOpen).toBe(true)
  })
})
