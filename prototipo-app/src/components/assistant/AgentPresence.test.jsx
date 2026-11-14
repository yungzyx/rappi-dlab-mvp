import { useEffect } from 'react'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { AssistantProvider, useAssistant } from '../../state/AssistantContext'
import { CartProvider, formatPrice, useCart } from '../../state/CartContext'
import { DemoProvider } from '../../state/DemoContext'
import { stubApi } from '../../test/api'
import { AGENT_DRAG_TYPE } from '../../assistant/agentAsk'
import { OPEN_CART_EVENT } from '../../state/cartSheet'
import { AGENT_CART_EVENT, resetLive } from '../../state/liveMemory'
import { QUIET_KEY, resetQuiet } from '../../state/agentQuiet'
import { HIDDEN_KEY } from '../../state/agentHidden'
import { setAgentEnabled } from '../../state/agentEnabled'
import { ProfileProvider } from '../../state/ProfileContext'
import { today } from '../../utils/today'
import AgentPresence, { SIDE_KEY } from './AgentPresence'

const events = vi.hoisted(() => ({ track: vi.fn(), flush: async () => {}, clear: () => {}, settled: async () => {} }))
vi.mock('../../state/EventsContext', async (importOriginal) => ({
  ...(await importOriginal()),
  useEvents: () => events,
}))
// Qué tiene Mochi debajo (agentSpot.js mide el layout, que jsdom no calcula): lo decide cada test.
const spot = vi.hoisted(() => ({ covers: false, lift: 0 }))
vi.mock('./agentSpot', () => ({ coversControl: () => spot.covers, tuckLift: () => spot.lift }))

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
  spot.covers = false
  spot.lift = 0
})

const added = (product) => act(() => window.dispatchEvent(new CustomEvent(AGENT_CART_EVENT, { detail: { product } })))
const bubble = () => document.querySelector('.agent-bubble')

describe('Mochi y el carro', () => {
  test('al agregar dice "¡Listo! … está en tu carro" y se va a los 4 s', async () => {
    vi.useFakeTimers()
    mountTree()
    added(BEER)
    expect(bubble().textContent).toContain(`¡Listo! ${BEER.name} está en tu carro.`)
    act(() => vi.advanceTimersByTime(4000))
    expect(bubble()).toBeNull()
  })

  test('"Deshacer" quita el producto', async () => {
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

  test('en "Rappi hoy" no aparece', async () => {
    localStorage.setItem('rappi-proto-demo-mode', 'actual')
    mountTree()
    expect(agentButton()).toBeNull()
  })

  test('con el buscador con Mochi abierto no aparece', async () => {
    mountTree()
    act(() => probe.assistant.open())
    expect(agentButton()).toBeNull()
  })

  test('tocarlo salta y abre el menú con sus 5 opciones; Escape lo cierra', async () => {
    const { container } = mountTree()
    fireEvent.pointerDown(agentButton())
    fireEvent.click(agentButton())
    expect(container.querySelector('.agent-presence .mascot').classList).toContain('mascot--jump')
    expect(agentButton().getAttribute('aria-expanded')).toBe('true')
    for (const name of [
      'Buscar con Mochi',
      '¿Qué puedo probar?',
      'Mover a la izquierda',
      'Silenciar por hoy',
      'Ocultar a Mochi',
    ])
      expect(screen.getByRole('button', { name })).toBeTruthy()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('group', { name: 'Opciones de Mochi' })).toBeNull()
    expect(document.activeElement).toBe(agentButton())
  })

  test('"¿Qué puedo probar?" abre el buscador con la oferta de la vertical por probar, sin contexto', async () => {
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
    expect(screen.getByRole('button', { name: `Revisar mi carro · ${formatPrice(probe.cart.total)}` })).toBeTruthy()
  })

  test('"Revisar mi carro" pide abrir la hoja del carro y cierra el menú', async () => {
    const opened = vi.fn()
    window.addEventListener(OPEN_CART_EVENT, opened)
    mountTree()
    act(() => probe.cart.add(BEER))
    fireEvent.click(agentButton())
    fireEvent.click(screen.getByRole('button', { name: /^Revisar mi carro/ }))
    window.removeEventListener(OPEN_CART_EVENT, opened)
    expect(opened).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('button', { name: /^Revisar mi carro/ })).toBeNull()
  })

  test('"Mover a la izquierda" lo cambia de lado y lo recuerda', async () => {
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

  test('"Silenciar por hoy" lo deja como pestañita y tocarla lo despierta; los dos quedan medidos', async () => {
    const { container } = mountTree()
    fireEvent.click(agentButton())
    events.track.mockClear()
    fireEvent.click(screen.getByRole('button', { name: 'Silenciar por hoy' }))
    expect(container.querySelector('.agent-presence').classList).toContain('is-quiet')
    // Silenciarlo no es ocultarlo: sigue visible (`visible: true`) y `quiet` dice que se calló.
    expect(events.track.mock.calls).toEqual([
      ['agent_visibility', { surface: 'agent', origin: 'menu-mochi', payload: { visible: true, quiet: true } }],
    ])
    const tab = screen.getByRole('button', { name: 'Mochi está en silencio: tocar para despertarlo' })
    fireEvent.click(tab)
    expect(container.querySelector('.agent-presence').classList).not.toContain('is-quiet')
    expect(agentButton()).toBeTruthy()
    expect(events.track).toHaveBeenLastCalledWith('agent_visibility', {
      surface: 'agent',
      origin: 'pestana-silencio',
      payload: { visible: true, quiet: false },
    })
  })

  test('silenciado o despertado desde la Home, al salir de ella lo respeta', async () => {
    const { container, rerender } = mountTree({ screen: 'home', homeTab: 'home' })
    expect(container.querySelector('.agent-presence')).toBeNull()
    localStorage.setItem(QUIET_KEY, today()) // "Silenciar por hoy" en el menú de la Home
    rerender(tree({ screen: 'vertical' }))
    expect(container.querySelector('.agent-presence').classList).toContain('is-quiet')

    rerender(tree({ screen: 'home', homeTab: 'home' }))
    localStorage.removeItem(QUIET_KEY) // "Volver a hablar" en la Home
    rerender(tree({ screen: 'vertical' }))
    expect(container.querySelector('.agent-presence').classList).not.toContain('is-quiet')
  })

  test('"Ocultar a Mochi" pide confirmar; "Cancelar" vuelve al menú y "Ocultar" lo saca para siempre', async () => {
    const { container } = mountTree()
    fireEvent.click(agentButton())
    fireEvent.click(screen.getByRole('button', { name: 'Ocultar a Mochi' }))
    const confirm = screen.getByRole('group', { name: 'Ocultar a Mochi' })
    expect(confirm.textContent).toContain('Mochi no volverá a aparecer. Puedes traerlo de vuelta en Cuenta.')
    expect(localStorage.getItem(HIDDEN_KEY)).toBeNull() // todavía no

    fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }))
    expect(screen.getByRole('group', { name: 'Opciones de Mochi' })).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Ocultar a Mochi' }))
    fireEvent.click(screen.getByRole('button', { name: 'Ocultar' }))
    expect(container.querySelector('.agent-presence')).toBeNull()
    expect(localStorage.getItem(HIDDEN_KEY)).toBe('1')
    expect(events.track).toHaveBeenCalledWith('agent_visibility', {
      surface: 'agent',
      origin: 'menu-mochi',
      payload: { visible: false },
    })

    // Recargar no lo trae: ni Mochi, ni su pestañita, ni sus globos al agregar al carro.
    cleanup()
    const again = mountTree()
    added(BEER)
    expect(again.container.querySelector('.agent-presence')).toBeNull()
    expect(bubble()).toBeNull()
  })

  test('en el grupo de control (Mochi apagado) no flota, y "Repetir escena" no lo trae', async () => {
    setAgentEnabled(false)
    mountTree()
    expect(agentButton()).toBeNull()
    act(() => resetLive())
    expect(agentButton()).toBeNull()
    act(() => setAgentEnabled(true)) // la API lo volvió a encender (el grupo de control se apagó)
    expect(agentButton()).toBeTruthy()
  })

  test('"Repetir escena" trae de vuelta a Mochi oculto, como a una persona nueva', async () => {
    localStorage.setItem(HIDDEN_KEY, '1')
    mountTree()
    expect(agentButton()).toBeNull()
    act(() => resetLive())
    expect(agentButton()).toBeTruthy()
    expect(localStorage.getItem(HIDDEN_KEY)).toBeNull()
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

  test('"Repetir escena" lo despierta', async () => {
    localStorage.setItem(QUIET_KEY, today())
    const { container } = mountTree()
    expect(container.querySelector('.agent-presence').classList).toContain('is-quiet')
    act(() => resetLive())
    expect(container.querySelector('.agent-presence').classList).not.toContain('is-quiet')
  })

  test('"Buscar con Mochi" abre el buscador', async () => {
    mountTree()
    fireEvent.click(agentButton())
    fireEvent.click(screen.getByRole('button', { name: 'Buscar con Mochi' }))
    expect(probe.assistant.isOpen).toBe(true)
  })
})

describe('Mochi no tapa los "+"', () => {
  const host = () => document.querySelector('.agent-presence')

  test('al hacer scroll se aparta al borde y, al parar sin nada debajo, vuelve', () => {
    vi.useFakeTimers()
    mountTree()
    fireEvent.scroll(document.querySelector('.phone'))
    expect(host().classList).toContain('is-tucked')
    act(() => vi.advanceTimersByTime(750))
    expect(host().classList).not.toContain('is-tucked')
  })

  test('si al parar queda sobre un control, sigue apartado; tocarlo abre el menú y ahí sale entero', () => {
    vi.useFakeTimers()
    spot.covers = true
    mountTree()
    act(() => vi.advanceTimersByTime(200))
    expect(host().classList).toContain('is-tucked')
    fireEvent.scroll(document.querySelector('.phone'))
    act(() => vi.advanceTimersByTime(750))
    expect(host().classList).toContain('is-tucked')
    fireEvent.click(agentButton())
    expect(host().classList).not.toContain('is-tucked')
  })

  test('cuando deja de tener algo debajo (cambió la pantalla) vuelve a salir', async () => {
    vi.useFakeTimers()
    spot.covers = true
    const { container } = mountTree()
    act(() => vi.advanceTimersByTime(200))
    expect(host().classList).toContain('is-tucked')
    spot.covers = false
    // El aviso del MutationObserver llega en una microtarea
    await act(async () => container.querySelector('.phone').append(document.createElement('div')))
    act(() => vi.advanceTimersByTime(200))
    expect(host().classList).not.toContain('is-tucked')
  })

  test('apartado, sube lo que diga tuckLift para no pisar un "+" con lo que asoma', () => {
    vi.useFakeTimers()
    spot.covers = true
    spot.lift = 48
    mountTree()
    act(() => vi.advanceTimersByTime(200))
    expect(host().style.getPropertyValue('--tuck-lift')).toBe('48px')
  })
})
