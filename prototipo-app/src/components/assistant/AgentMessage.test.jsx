import { StrictMode } from 'react'
import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { toMessage } from '../../api/client'
import { fixture, stubApi } from '../../test/api'
import { CartProvider } from '../../state/CartContext'
import { DemoProvider } from '../../state/DemoContext'
import { ProductSheetProvider } from '../../state/ProductSheetContext'
import { ProfileProvider } from '../../state/ProfileContext'
import AgentMessage from './AgentMessage'

const noop = () => {}

function mount(response, { animate = false } = {}) {
  const message = { ...toMessage(response), animate }
  const result = render(
    <StrictMode>
      <DemoProvider>
        <ProfileProvider>
          <CartProvider>
            <ProductSheetProvider>
              <AgentMessage message={message} onOpenProduct={noop} onOpenStore={noop} onAction={noop} onRetry={noop} />
            </ProductSheetProvider>
          </CartProvider>
        </ProfileProvider>
      </DemoProvider>
    </StrictMode>,
  )
  return result
}

beforeEach(() => {
  stubApi({})
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('reducir movimiento', () => {
  const matchMedia = (reduce) => (query) => ({
    matches: reduce && query.includes('prefers-reduced-motion'),
    addEventListener() {},
    removeEventListener() {},
  })

  test('con reduce la respuesta aparece entera en el primer render', () => {
    vi.stubGlobal('matchMedia', matchMedia(true))
    const response = fixture('agent-ask')
    mount(response, { animate: true })
    expect(screen.getByText(response.text)).toBeTruthy()
  })

  test('sin reduce la respuesta se escribe de a poco', () => {
    vi.stubGlobal('matchMedia', matchMedia(false))
    const response = fixture('agent-ask')
    mount(response, { animate: true })
    expect(screen.queryByText(response.text)).toBeNull()
  })
})

// Lo que el panel tiene debajo de la respuesta no debe moverse mientras se escribe: la respuesta ocupa desde el primer
// render el lugar que tendrá al terminar.
describe('mientras se escribe, nada se mueve', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {} }))
  })
  afterEach(() => vi.useRealTimers())
  /** Hasta que no quedan temporizadores: el texto ya se escribió entero. */
  const finishTyping = async () => {
    for (let i = 0; i < 100 && vi.getTimerCount() > 0; i++) await act(() => vi.advanceTimersByTimeAsync(250))
  }

  test('la burbuja reserva el texto entero: lo que falta escribir va invisible, sin ser texto de la página', async () => {
    const response = fixture('agent-ask')
    const { container } = mount(response, { animate: true })
    const bubble = container.querySelector('.agent-msg-bubble')
    const rest = () => bubble.querySelector('.agent-msg-rest')
    expect(bubble.textContent).toBe('')
    expect(rest().dataset.rest).toBe(response.text)

    await act(() => vi.advanceTimersByTimeAsync(200))
    expect(bubble.textContent.length).toBeGreaterThan(0)
    expect(bubble.textContent + rest().dataset.rest).toBe(response.text)

    await finishTyping()
    expect(bubble.textContent).toBe(response.text)
    expect(rest()).toBeNull()
  })

  test('las tarjetas ocupan su lugar desde el principio, pero no se ven ni se tocan hasta terminar el texto', async () => {
    const response = fixture('agent-ask')
    const { container } = mount(response, { animate: true })
    const extras = container.querySelector('.agent-msg-extras')
    expect(extras.classList.contains('is-pending')).toBe(true)
    const add = () => screen.getAllByRole('button', { name: /^Agregar / })
    expect(add().length).toBeGreaterThanOrEqual(response.products.length) // también las de la sugerencia
    expect(add().every((button) => extras.contains(button))).toBe(true)
    expect(extras.hasAttribute('inert')).toBe(true) // el navegador no los muestra al lector de pantalla ni al foco

    await finishTyping()
    expect(extras.classList.contains('is-pending')).toBe(false)
    expect(extras.hasAttribute('inert')).toBe(false)
  })
})
