import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { ToastProvider } from '../../components/Toast'
import { stubApi } from '../../test/api'
import { AddressProvider } from '../../state/AddressContext'
import { DemoProvider } from '../../state/DemoContext'
import { OrdersProvider } from '../../state/OrdersContext'
import { ProfileProvider } from '../../state/ProfileContext'
import { HIDDEN_KEY } from '../../state/agentHidden'
import { setAgentEnabled } from '../../state/agentEnabled'
import AccountScreen from './AccountScreen'

const events = vi.hoisted(() => ({ track: vi.fn(), flush: async () => {}, clear: () => {}, settled: async () => {} }))
vi.mock('../../state/EventsContext', async (importOriginal) => ({
  ...(await importOriginal()),
  useEvents: () => events,
}))

beforeEach(() => {
  localStorage.clear()
  events.track.mockClear()
  stubApi({})
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  localStorage.clear()
})

function renderAccount() {
  render(
    <DemoProvider>
      <ProfileProvider>
        <ToastProvider>
          <AddressProvider>
            <OrdersProvider>
              <AccountScreen onBack={() => {}} push={() => {}} />
            </OrdersProvider>
          </AddressProvider>
        </ToastProvider>
      </ProfileProvider>
    </DemoProvider>,
  )
}

const row = () => screen.getByRole('switch', { name: 'Mostrar a Mochi' })

test('en el grupo de control (Mochi apagado) Cuenta no ofrece mostrar, ocultar ni repetir la escena de Mochi', () => {
  setAgentEnabled(false)
  renderAccount()
  expect(screen.queryByRole('switch', { name: 'Mostrar a Mochi' })).toBeNull()
  expect(screen.queryByRole('button', { name: /Repetir escena/ })).toBeNull()
  expect(screen.queryByText(/Mochi/)).toBeNull()
  expect(screen.getByRole('button', { name: /Notificaciones/ })).toBeTruthy() // lo demás de Cuenta sigue
})

describe('"Mostrar a Mochi" en Cuenta', () => {
  test('encendido por defecto; apagarlo pide confirmar, y "Cancelar" lo deja como estaba', () => {
    renderAccount()
    expect(row().getAttribute('aria-checked')).toBe('true')
    fireEvent.click(row())
    expect(screen.getByText('Mochi no volverá a aparecer. Puedes traerlo de vuelta en Cuenta.')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }))
    expect(row().getAttribute('aria-checked')).toBe('true')
    expect(localStorage.getItem(HIDDEN_KEY)).toBeNull()
  })

  test('"Ocultar" lo apaga y lo recuerda; volver a tocarlo trae a Mochi sin preguntar', () => {
    renderAccount()
    fireEvent.click(row())
    fireEvent.click(screen.getByRole('button', { name: 'Ocultar' }))
    expect(row().getAttribute('aria-checked')).toBe('false')
    expect(localStorage.getItem(HIDDEN_KEY)).toBe('1')
    expect(events.track).toHaveBeenLastCalledWith('agent_visibility', {
      origin: 'cuenta',
      payload: { visible: false },
    })

    fireEvent.click(row())
    expect(row().getAttribute('aria-checked')).toBe('true')
    expect(localStorage.getItem(HIDDEN_KEY)).toBeNull()
    expect(screen.getByText('Mochi está de vuelta')).toBeTruthy()
    expect(events.track).toHaveBeenLastCalledWith('agent_visibility', { origin: 'cuenta', payload: { visible: true } })
  })

  test('"Repetir escena" con Mochi oculto lo trae de vuelta y lo anota; sin ocultar, no anota nada', () => {
    localStorage.setItem(HIDDEN_KEY, '1')
    renderAccount()
    fireEvent.click(screen.getByRole('button', { name: /Repetir escena/ }))
    expect(localStorage.getItem(HIDDEN_KEY)).toBeNull()
    expect(events.track).toHaveBeenLastCalledWith('agent_visibility', {
      origin: 'repetir-escena',
      payload: { visible: true },
    })

    events.track.mockClear()
    fireEvent.click(screen.getByRole('button', { name: /Repetir escena/ }))
    expect(events.track).not.toHaveBeenCalled()
  })

  test('en "Rappi hoy" no está: ahí no hay Mochi', () => {
    localStorage.setItem('rappi-proto-demo-mode', 'actual')
    renderAccount()
    expect(screen.queryByRole('switch', { name: 'Mostrar a Mochi' })).toBeNull()
  })
})
