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

const answersShown = () => document.querySelectorAll('.agent-card .agent-msg-row').length

let consoleError
beforeEach(() => {
  vi.useFakeTimers()
  consoleError = vi.spyOn(console, 'error')
})
afterEach(() => {
  cleanup()
  consoleError.mockRestore()
  vi.useRealTimers()
  localStorage.clear()
})

describe('la respuesta de Mochi nunca sale repetida', () => {
  test('al abrir, cerrar, volver a abrir y tocar ideas siempre se ve una sola respuesta', async () => {
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
