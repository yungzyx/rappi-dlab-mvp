import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, test, vi } from 'vitest'
import { fixture, stubApi } from './test/api'
import App from './App'

vi.mock('./api/client', async (importOriginal) => ({
  ...(await importOriginal()),
  health: vi.fn().mockResolvedValue(null),
}))

beforeAll(() => {
  Element.prototype.scrollTo = () => {}
})
afterAll(() => {
  delete Element.prototype.scrollTo
})
beforeEach(() => {
  localStorage.setItem('rappi-proto-demo-mode', 'actual')
  localStorage.setItem('rappi-proto-privacy-seen', '1')
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('aviso de privacidad en la app', () => {
  test('la primera visita lo muestra y «Ir a Cuenta» abre Cuenta con «Borrar mis datos»', async () => {
    localStorage.removeItem('rappi-proto-privacy-seen')
    stubApi({ '/search': fixture('search-grouped'), '/catalog/home': fixture('catalog-home') })
    window.history.replaceState(null, '', '/')
    render(<App />)
    expect(await screen.findByText(/guardamos tus búsquedas/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Ir a Cuenta' }))
    expect(screen.queryByText(/guardamos tus búsquedas/)).toBeNull()
    expect(screen.getByRole('button', { name: 'Borrar mis datos' })).toBeTruthy()
  })
})
