import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { fixture, stubApi } from '../../test/api'
import { userId } from '../../api/user'
import { ToastProvider } from '../../components/Toast'
import { AddressProvider } from '../../state/AddressContext'
import { DemoProvider } from '../../state/DemoContext'
import { forgetAll } from '../../state/forgetAll'
import { reloadToHome } from '../../state/reloadApp'
import { OrdersProvider, useOrders } from '../../state/OrdersContext'
import { ProfileProvider } from '../../state/ProfileContext'
import AccountScreen from './AccountScreen'

const order = { id: 'order-1', placedAt: 1, stores: ['Súper'], items: [], total: 1000, address: 'Casa de prueba' }

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  vi.mocked(reloadToHome).mockClear()
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function Orders() {
  return <p data-testid="orders">{useOrders().orders.length}</p>
}

function renderAccount() {
  render(
    <DemoProvider>
      <ProfileProvider>
        <ToastProvider>
          <AddressProvider>
            <OrdersProvider>
              <Orders />
              <AccountScreen onBack={() => {}} push={() => {}} />
            </OrdersProvider>
          </AddressProvider>
        </ToastProvider>
      </ProfileProvider>
    </DemoProvider>,
  )
}

const deletes = (api) =>
  api.mock.calls.filter(([, init]) => init?.method === 'DELETE').map(([url]) => new URL(url).pathname)

describe('Borrar mis datos (Cuenta)', () => {
  test('llama a forget, deja solo el id nuevo en el navegador y userId cambia', async () => {
    const before = userId()
    localStorage.setItem('rappi-proto-orders', JSON.stringify([order]))
    localStorage.setItem('rappi-proto-cart', '{"id":"c-1","lines":{}}')
    localStorage.setItem('rappi-proto-privacy-seen', '1')
    sessionStorage.setItem('rappi-proto-session', '{"id":"s-1","lastAt":1}')
    const api = stubApi({ 'DELETE /profile/*': {} })
    renderAccount()
    expect(screen.getByTestId('orders').textContent).toBe('1')

    fireEvent.click(screen.getByRole('button', { name: 'Borrar mis datos' }))
    fireEvent.click(screen.getByRole('button', { name: 'Sí, borrar' }))
    await waitFor(() => expect(deletes(api)).toEqual([`/profile/${before}`]))

    await waitFor(() => expect(userId()).not.toBe(before))
    const left = Object.keys(localStorage).filter((key) => key.startsWith('rappi-proto-'))
    expect(left.sort()).toEqual(['rappi-proto-token', 'rappi-proto-user'])
    expect(localStorage.getItem('rappi-proto-user')).toBe(userId())
    expect(localStorage.getItem('rappi-proto-token')).toBe(fixture('session').token)
    expect(sessionStorage.getItem('rappi-proto-session')).toBeNull()
    // Con todo borrado, la app se recarga en la Home: ni el carro ni los pedidos en memoria sobreviven.
    await waitFor(() => expect(reloadToHome).toHaveBeenCalledTimes(1))
  })

  test('si el servidor no borra, no se toca nada y se avisa', async () => {
    const before = userId()
    localStorage.setItem('rappi-proto-orders', JSON.stringify([order]))
    const api = stubApi({ 'DELETE /profile/*': 500 })
    renderAccount()
    fireEvent.click(screen.getByRole('button', { name: 'Borrar mis datos' }))
    fireEvent.click(screen.getByRole('button', { name: 'Sí, borrar' }))
    expect(await screen.findByText(/No pude borrar tus datos/)).toBeTruthy()
    expect(deletes(api)).toHaveLength(1)
    expect(userId()).toBe(before)
    expect(localStorage.getItem('rappi-proto-orders')).not.toBeNull()
    expect(screen.getByTestId('orders').textContent).toBe('1')
    expect(reloadToHome).not.toHaveBeenCalled()
  })
})

describe('forgetAll', () => {
  test('vacía la cola de eventos antes de cualquier espera', () => {
    stubApi({ 'DELETE /profile/*': {} })
    const events = { clear: vi.fn(), settled: vi.fn().mockResolvedValue(undefined) }
    forgetAll({ events, settle: () => new Promise(() => {}) }) // la espera previa nunca termina
    expect(events.clear).toHaveBeenCalledTimes(1)
    expect(events.settled).not.toHaveBeenCalled()
  })

  test('recarga solo si el servidor borró, y después de borrar lo local', async () => {
    stubApi({ 'DELETE /profile/*': {} })
    localStorage.setItem('rappi-proto-cart', '{}')
    const before = userId()
    const reload = vi.fn(() => {
      expect(localStorage.getItem('rappi-proto-cart')).toBeNull() // ya se borró lo local
      expect(userId()).not.toBe(before)
    })
    await forgetAll({ events: { clear: vi.fn(), settled: vi.fn().mockResolvedValue(undefined) }, reload })
    expect(reload).toHaveBeenCalledTimes(1)
  })

  test('forgetAll pide una sesión nueva', async () => {
    localStorage.setItem('rappi-proto-user', 'proto-1111111111111111')
    localStorage.setItem('rappi-proto-token', 'proto-1111111111111111.firma')
    const api = stubApi({
      'DELETE /profile/*': {},
      'POST /session': (req) => {
        // Sin el id ni el token de antes: la persona nueva no hereda nada
        expect(req.body).toEqual({ legacy_user_id: null })
        return { user_id: 'proto-2222222222222222', token: 'proto-2222222222222222.firma' }
      },
    })
    const reload = vi.fn()
    await forgetAll({ events: { clear: vi.fn(), settled: vi.fn().mockResolvedValue(undefined) }, reload })
    const calls = api.mock.calls.map(([url, init]) => `${init?.method} ${new URL(url).pathname}`)
    expect(calls).toEqual(['DELETE /profile/proto-1111111111111111', 'POST /session'])
    expect(api.mock.calls[1][1].headers['X-User-Token']).toBeUndefined()
    expect(userId()).toBe('proto-2222222222222222')
    expect(localStorage.getItem('rappi-proto-token')).toBe('proto-2222222222222222.firma')
    expect(reload).toHaveBeenCalledTimes(1)
  })

  test('si la sesión nueva falla, igual recarga sin el id viejo (la app la pide al abrir)', async () => {
    localStorage.setItem('rappi-proto-user', 'proto-1111111111111111')
    localStorage.setItem('rappi-proto-token', 'proto-1111111111111111.firma')
    stubApi({ 'DELETE /profile/*': {}, 'POST /session': 'offline' })
    const reload = vi.fn()
    await forgetAll({ events: { clear: vi.fn(), settled: vi.fn().mockResolvedValue(undefined) }, reload })
    expect(localStorage.getItem('rappi-proto-token')).toBeNull()
    expect(localStorage.getItem('rappi-proto-user')).not.toBe('proto-1111111111111111')
    expect(reload).toHaveBeenCalledTimes(1)
  })

  test('si el DELETE falla, no recarga y no cambia el id', async () => {
    stubApi({ 'DELETE /profile/*': 500 })
    const before = userId()
    const events = { clear: vi.fn(), settled: vi.fn().mockResolvedValue(undefined) }
    const reload = vi.fn()
    await expect(forgetAll({ events, reload })).rejects.toThrow()
    expect(reload).not.toHaveBeenCalled()
    expect(userId()).toBe(before)
  })
})
