import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { ToastProvider } from '../../components/Toast'
import { stubApi } from '../../test/api'
import { AddressProvider } from '../../state/AddressContext'
import { DemoProvider } from '../../state/DemoContext'
import { OrdersProvider } from '../../state/OrdersContext'
import { ProfileProvider } from '../../state/ProfileContext'
import AccountScreen from './AccountScreen'

beforeEach(() => {
  localStorage.clear()
  stubApi({})
})
afterEach(() => {
  cleanup()
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
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

describe('la fila «Modo demo» de Cuenta', () => {
  test('en desarrollo está', () => {
    renderAccount()
    expect(screen.getByRole('button', { name: /Modo demo/ })).toBeTruthy()
  })

  test('sin VITE_DEMO no está: el sitio desplegado no cambia de modo', () => {
    vi.stubEnv('DEV', false)
    vi.stubEnv('VITE_DEMO', '')
    renderAccount()
    expect(screen.queryByRole('button', { name: /Modo demo/ })).toBeNull()
  })

  test('con VITE_DEMO=1 está aunque no sea desarrollo', () => {
    vi.stubEnv('DEV', false)
    vi.stubEnv('VITE_DEMO', '1')
    renderAccount()
    expect(screen.getByRole('button', { name: /Modo demo/ })).toBeTruthy()
  })
})
