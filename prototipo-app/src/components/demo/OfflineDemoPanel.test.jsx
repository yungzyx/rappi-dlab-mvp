import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { HIDDEN_KEY, isAgentHidden } from '../../state/agentHidden'
import { DemoProvider } from '../../state/DemoContext'
import OfflineDemoPanel from './OfflineDemoPanel'

const events = vi.hoisted(() => ({ track: vi.fn(), flush: async () => {}, clear: () => {}, settled: async () => {} }))
vi.mock('../../state/EventsContext', async (importOriginal) => ({
  ...(await importOriginal()),
  useEvents: () => events,
}))
// La muestra del catálogo no hace falta para el botón de Mochi: una persona y una escalera vacía.
vi.mock('../../api/offline/snapshot', () => ({ loadSnapshot: async () => ({ meta: {} }) }))
vi.mock('../../api/offline/personas', async (importOriginal) => ({
  ...(await importOriginal()),
  personas: () => [{ id: 'nueva', label: 'Nueva (sin historial)' }],
  ladderReadout: () => 'Hoy: sin pedidos',
}))

beforeEach(() => {
  localStorage.clear()
  events.track.mockClear()
})
afterEach(() => {
  cleanup()
  localStorage.clear()
})

async function openPanel() {
  await act(async () => {
    render(
      <DemoProvider>
        <OfflineDemoPanel />
      </DemoProvider>,
    )
  })
  await act(async () => fireEvent.click(screen.getByRole('button', { name: '🎛️ Panel de la demo' })))
}

describe('"Panel de la demo": Mochi', () => {
  test('"Ocultar a Mochi" lo oculta sin confirmar y lo anota; el mismo botón, "Mostrar a Mochi", lo trae de vuelta', async () => {
    await openPanel()
    expect(screen.getByRole('heading', { name: 'Mochi' })).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Ocultar a Mochi' }))
    expect(isAgentHidden()).toBe(true)
    expect(localStorage.getItem(HIDDEN_KEY)).toBe('1')
    expect(events.track).toHaveBeenLastCalledWith('agent_visibility', {
      origin: 'panel-demo',
      payload: { visible: false },
    })

    fireEvent.click(screen.getByRole('button', { name: 'Mostrar a Mochi' }))
    expect(isAgentHidden()).toBe(false)
    expect(events.track).toHaveBeenLastCalledWith('agent_visibility', {
      origin: 'panel-demo',
      payload: { visible: true },
    })
    expect(screen.getByRole('button', { name: 'Ocultar a Mochi' })).toBeTruthy()
  })

  test('si se ocultó desde la app, el botón ya dice "Mostrar a Mochi"', async () => {
    localStorage.setItem(HIDDEN_KEY, '1')
    await openPanel()
    expect(screen.getByRole('button', { name: 'Mostrar a Mochi' })).toBeTruthy()
  })

  test('en "Rappi hoy" no está: ahí no hay Mochi', async () => {
    localStorage.setItem('rappi-proto-demo-mode', 'actual')
    await openPanel()
    expect(screen.queryByRole('heading', { name: 'Mochi' })).toBeNull()
    expect(screen.queryByRole('button', { name: /a Mochi$/ })).toBeNull()
  })
})
