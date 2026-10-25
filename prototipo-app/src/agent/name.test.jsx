import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, test, vi } from 'vitest'
import { fixture, stubApi } from '../test/api'
import AssistantPanel from '../components/assistant/AssistantPanel'
import SmartBar from '../components/assistant/SmartBar'
import ConnectionGate from '../components/ConnectionGate'
import { AssistantProvider, useAssistant } from '../state/AssistantContext'
import { CartProvider } from '../state/CartContext'
import { DemoProvider } from '../state/DemoContext'
import { ProductSheetProvider } from '../state/ProductSheetContext'
import { ProfileProvider } from '../state/ProfileContext'

// Si el nombre cambia en un solo lugar, los textos visibles lo siguen.
vi.mock('./name', () => ({ AGENT_NAME: 'Koko' }))

const api = vi.hoisted(() => ({ health: vi.fn(), ask: vi.fn(), forget: vi.fn(), profile: vi.fn() }))
vi.mock('../api/client', async (importOriginal) => ({ ...(await importOriginal()), ...api }))

beforeAll(() => {
  Element.prototype.scrollTo = () => {} // jsdom no lo implementa
})
afterAll(() => {
  delete Element.prototype.scrollTo
})
beforeEach(() => {
  api.health.mockResolvedValue({})
  api.profile.mockResolvedValue({ interests: [] })
  api.forget.mockResolvedValue({})
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.clearAllMocks()
  localStorage.clear()
  sessionStorage.clear()
})

function OpenButton() {
  const assistant = useAssistant()
  return (
    <button type="button" onClick={() => assistant.open()}>
      abrir
    </button>
  )
}

describe('el nombre del agente sale de AGENT_NAME', () => {
  test('la puerta de conexión', async () => {
    stubApi({ '/health': 'offline' })
    render(
      <ConnectionGate>
        <p>La app</p>
      </ConnectionGate>,
    )
    expect(await screen.findByRole('heading', { name: 'Sin conexión con Koko' })).toBeTruthy()
  })

  test('la barra de búsqueda: su etiqueta y su sugerencia', async () => {
    vi.useFakeTimers()
    render(
      <AssistantProvider>
        <SmartBar />
      </AssistantProvider>,
    )
    expect(screen.getByRole('button', { name: 'Abrir buscador con Koko' })).toBeTruthy()
    await act(() => vi.advanceTimersByTimeAsync(3200))
    expect(screen.getByText('Busca o pídele ideas a Koko')).toBeTruthy()
  })

  test('el saludo y el nombre del buscador', async () => {
    vi.useFakeTimers()
    stubApi({
      '/catalog/home': fixture('catalog-home'),
      '/search': fixture('search-grouped'),
      '/recommendations': { rows: [] },
    })
    render(
      <DemoProvider>
        <ProfileProvider>
          <AssistantProvider>
            <CartProvider>
              <ProductSheetProvider>
                <OpenButton />
                <AssistantPanel push={() => {}} />
              </ProductSheetProvider>
            </CartProvider>
          </AssistantProvider>
        </ProfileProvider>
      </DemoProvider>,
    )
    fireEvent.click(screen.getByText('abrir'))
    for (let i = 0; i < 100 && vi.getTimerCount() > 0; i++) await act(() => vi.advanceTimersByTimeAsync(250))
    const bubbles = [...document.querySelectorAll('.agent-msg-bubble')].map((el) => el.textContent)
    expect(bubbles[0]).toBe('¡Hola! Soy Koko, tu asistente de compras 🧡 ¿Qué se te antoja hoy?')
    expect(screen.getByRole('dialog', { name: 'Buscador con Koko' })).toBeTruthy()
  })
})
