// En su propio archivo: los ids de los mensajes son un contador del módulo y aquí parten de 1, como al abrir la app.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { AssistantProvider, useAssistant } from '../../state/AssistantContext'
import { CartProvider } from '../../state/CartContext'
import { DemoProvider } from '../../state/DemoContext'
import { ProductSheetProvider } from '../../state/ProductSheetContext'
import { ProfileProvider } from '../../state/ProfileContext'
import AssistantPanel from './AssistantPanel'

const api = vi.hoisted(() => ({
  ask: vi.fn(async () => ({ text: 'Para el carrete', products: [] })),
  forget: vi.fn(),
  profile: vi.fn(async () => ({ interests: [] })),
}))
vi.mock('../../api/client', async (importOriginal) => ({ ...(await importOriginal()), ...api }))
const events = vi.hoisted(() => ({ track: vi.fn(), flush: vi.fn(), clear: vi.fn(), settled: vi.fn() }))
vi.mock('../../state/EventsContext', async (importOriginal) => ({
  ...(await importOriginal()),
  useEvents: () => events,
}))

const advance = (ms) => act(() => vi.advanceTimersByTimeAsync(ms))
async function runUntilIdle() {
  await advance(0)
  for (let i = 0; i < 100 && vi.getTimerCount() > 0; i++) await advance(250)
}

function OpenButton() {
  const assistant = useAssistant()
  return (
    <button type="button" onClick={() => assistant.open()}>
      abrir
    </button>
  )
}

function renderPanel() {
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
}

const answersShown = () => document.querySelectorAll('.agent-card .agent-msg-row').length
const bubbleText = () => document.querySelector('.agent-card .agent-msg-bubble')?.textContent

let consoleError
beforeEach(() => {
  vi.useFakeTimers()
  Element.prototype.scrollTo = () => {} // jsdom no lo implementa
  consoleError = vi.spyOn(console, 'error')
})
afterEach(() => {
  cleanup()
  delete Element.prototype.scrollTo
  consoleError.mockRestore()
  vi.useRealTimers()
  localStorage.clear()
})

describe('la respuesta de Mochi nunca sale repetida', () => {
  test('al abrir, cerrar, volver a abrir y tocar ideas siempre se ve una sola respuesta', async () => {
    renderPanel()
    for (let round = 0; round < 4; round++) {
      fireEvent.click(screen.getByText('abrir'))
      await runUntilIdle()
      expect(answersShown()).toBe(1)
      fireEvent.click(screen.getAllByRole('button', { name: /carrete/i })[0])
      await runUntilIdle()
      expect(answersShown()).toBe(1)
      fireEvent.click(screen.getByRole('button', { name: 'Volver' }))
      await runUntilIdle()
    }
    const sameKey = consoleError.mock.calls.filter(([message]) => String(message).includes('same key'))
    expect(sameKey).toEqual([])
  })
})

describe('con el teclado, el foco no se pierde al llegar la respuesta', () => {
  test('la idea que se tocó sigue con el foco', async () => {
    renderPanel()
    fireEvent.click(screen.getByText('abrir'))
    await runUntilIdle()
    const chip = screen.getByRole('button', { name: '🍫 Algo dulce' })
    chip.focus()
    fireEvent.click(chip)
    await runUntilIdle()
    expect(document.activeElement).not.toBe(document.body)
    expect(document.activeElement).toBe(chip)
  })

  const beers = {
    text: 'Mira estas cervezas',
    vertical: 'licores',
    intent: { query: 'cerveza', concepts: ['cerveza'], follow_up: false },
    products: [{ id: 'cat-1', entity_type: 'catalog_item', entity_id: '1', name: 'Escudo', price: '$1.290' }],
    conversation: { query: 'cerveza', concepts: ['cerveza'], vertical: 'licores', people: null, order: null },
  }
  /** Una respuesta con chips para refinar, ya escrita. */
  async function renderBeers(...next) {
    api.ask.mockResolvedValueOnce(beers)
    for (const text of next) api.ask.mockResolvedValueOnce({ ...beers, text })
    renderPanel()
    fireEvent.click(screen.getByText('abrir'))
    await runUntilIdle()
    fireEvent.click(screen.getByRole('button', { name: '🍻 Arma un carrete' }))
    await runUntilIdle()
  }

  test('tras un chip para refinar (la respuesta se reemplaza entera), el foco pasa al texto de la nueva', async () => {
    await renderBeers('Otra opción de cerveza')
    const refine = screen.getByRole('button', { name: 'Otra opción' })
    refine.focus()
    fireEvent.click(refine)
    await runUntilIdle()
    expect(document.activeElement).not.toBe(document.body)
    expect(document.activeElement.textContent).toBe('Otra opción de cerveza')
  })

  test('si tras refinar la persona se va al buscador antes de que llegue la respuesta, la nueva no le quita el foco', async () => {
    await renderBeers('Otra opción de cerveza')
    const refine = screen.getByRole('button', { name: 'Otra opción' })
    refine.focus()
    fireEvent.click(refine)
    const field = screen.getByLabelText('Buscar en Rappi')
    field.focus()
    await runUntilIdle()
    expect(bubbleText()).toBe('Otra opción de cerveza')
    expect(document.activeElement).toBe(field)
  })

  test('si el foco salió de la respuesta a otro control, la próxima respuesta no lo trae aunque el foco se pierda', async () => {
    await renderBeers('Una cerveza para el asado')
    screen.getByRole('button', { name: 'Otra opción' }).focus()
    const field = screen.getByLabelText('Buscar en Rappi')
    field.focus()
    fireEvent.change(field, { target: { value: '¿qué cerveza va con un asado?' } })
    fireEvent.keyDown(field, { key: 'Enter' }) // pedírselo a Mochi suelta el campo: el foco queda en body
    await runUntilIdle()
    expect(bubbleText()).toBe('Una cerveza para el asado')
    expect(document.activeElement).toBe(document.body)
  })
})
