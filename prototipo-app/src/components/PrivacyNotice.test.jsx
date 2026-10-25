import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import PrivacyNotice from './PrivacyNotice'

const KEY = 'rappi-proto-privacy-seen'

beforeEach(() => localStorage.clear())
afterEach(cleanup)

describe('aviso de privacidad', () => {
  test('la primera visita muestra el aviso y no vuelve', () => {
    const first = render(<PrivacyNotice onOpenAccount={() => {}} />)
    expect(
      screen.getByText(
        'Para recomendarte mejor guardamos tus búsquedas y lo que haces en la app con un identificador anónimo. Puedes borrarlo en Cuenta → Borrar mis datos.',
      ),
    ).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Entendido' }))
    expect(screen.queryByText(/guardamos tus búsquedas/)).toBeNull()
    expect(localStorage.getItem(KEY)).not.toBeNull()

    first.unmount()
    render(<PrivacyNotice onOpenAccount={() => {}} />)
    expect(screen.queryByText(/guardamos tus búsquedas/)).toBeNull()
  })

  test('el enlace lleva a Cuenta y también cierra el aviso para siempre', () => {
    const onOpenAccount = vi.fn()
    render(<PrivacyNotice onOpenAccount={onOpenAccount} />)
    fireEvent.click(screen.getByRole('button', { name: 'Ir a Cuenta' }))
    expect(onOpenAccount).toHaveBeenCalledTimes(1)
    expect(screen.queryByText(/guardamos tus búsquedas/)).toBeNull()
    expect(localStorage.getItem(KEY)).not.toBeNull()
  })

  test('sin almacenamiento el aviso se muestra y se cierra para esta visita', () => {
    const set = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('bloqueado')
    })
    render(<PrivacyNotice onOpenAccount={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: 'Entendido' }))
    expect(screen.queryByText(/guardamos tus búsquedas/)).toBeNull()
    set.mockRestore()
  })
})
