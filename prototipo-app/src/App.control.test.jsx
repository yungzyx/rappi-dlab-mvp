import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, test, vi } from 'vitest'
import { fixture, stubApi } from './test/api'
import { P1_TEXT } from './components/survey/FoundItCard'
import App from './App'

vi.mock('./api/client', async (importOriginal) => ({
  ...(await importOriginal()),
  health: vi.fn().mockResolvedValue(null),
}))

// El 204 de una oferta retenida al grupo de control (api/agent.py).
const withheld = () => new Response(null, { status: 204, headers: { 'X-Offer-Withheld': '1' } })
let api

beforeAll(() => {
  Element.prototype.scrollTo = () => {} // jsdom no lo implementa
  Element.prototype.animate = () => ({ cancel() {} })
})
afterAll(() => {
  delete Element.prototype.scrollTo
  delete Element.prototype.animate
})
beforeEach(() => {
  api = stubApi({
    '/search': fixture('search-grouped'),
    '/catalog/home': fixture('catalog-home'),
    '/agent/plans': fixture('agent-plans'),
    '/recommendations': fixture('recommendations'),
    'POST /agent/offer': withheld,
    'POST /events': { guardados: 1 },
  })
  localStorage.setItem('rappi-proto-demo-mode', 'final')
  localStorage.setItem('rappi-proto-privacy-seen', '1')
  localStorage.setItem('rappi-proto-guia-vista', '1')
  localStorage.setItem('rappi-proto-mochi-activo', '0') // lo que dijo la API con la sesión: el grupo de control
  window.history.replaceState(null, '', '/')
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('Mochi apagado (el grupo de control, `agent_enabled` falso)', () => {
  test('con Mochi (tratamiento, o el control apagado) la Home tiene su buscador y su mascota', async () => {
    localStorage.removeItem('rappi-proto-mochi-activo')
    const { container } = render(<App />)
    await screen.findByLabelText('Buscar')
    expect(container.querySelector('.smart-bar')).toBeTruthy()
    expect(container.querySelector('.live-agent')).toBeTruthy()
  })

  test('la app no muestra a Mochi, busca con el buscador de siempre y la pregunta de la H3 sale igual', async () => {
    const { container } = render(<App />)
    await screen.findByLabelText('Buscar')
    expect(container.querySelector('.live-agent, .agent-presence, .smart-bar')).toBeNull()
    expect(screen.queryByRole('button', { name: /Mochi/ })).toBeNull()

    fireEvent.click(screen.getByLabelText('Buscar'))
    const input = await screen.findByPlaceholderText('¿Qué quieres hoy?')
    expect(container.querySelector('.agent-search')).toBeNull() // no es el buscador con Mochi
    await screen.findByRole('heading', { name: 'Para ti' }) // "Para ti" (/recommendations) lo conserva
    fireEvent.change(input, { target: { value: 'cerveza' } })
    await screen.findByText('Cerveza negra botella 330 cc (prueba)')
    fireEvent.keyDown(input, { key: 'Enter' })
    fireEvent.click(within(document.querySelector('.search-header')).getByRole('button', { name: /Volver/ }))

    expect(await screen.findByRole('heading', { name: P1_TEXT }, { timeout: 4000 })).toBeTruthy()
    expect(container.querySelector('.live-agent, .agent-presence')).toBeNull()
    // Ninguna pregunta a Mochi: su buscador no estuvo.
    expect(api.mock.calls.some(([url]) => url.endsWith('/agent/ask'))).toBe(false)
  })
})
