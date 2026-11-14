import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { GoalValue } from './GoalValue.jsx'

const STORAGE_KEY = 'panel-empresa:valor-meta'

// Números redondos inventados (no son de Rappi): margen por pedido = 10 × 10 % = 1.
const type = (label, value) => fireEvent.change(screen.getByLabelText(label), { target: { value } })
function fillInvented() {
  type('Usuarios activos al mes', '100.000')
  type('Retención base', '50')
  type('Pedidos por usuario activo al mes', '2')
  type('Valor promedio del pedido', '10')
  type('Margen por pedido', '10')
  type('Clientes de Restaurantes al mes', '100.000')
  type('De ellos, compran hoy en Turbo', '20')
}
const summary = () => document.querySelector('.goal-summary').textContent

describe('GoalValue', () => {
  beforeEach(() => sessionStorage.clear())
  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    sessionStorage.clear()
  })

  test('starts empty, with the pilot goals and full coverage, and says what is missing', () => {
    render(<GoalValue />)
    expect(screen.getByLabelText('Usuarios activos al mes')).toHaveProperty('value', '')
    expect(screen.getByLabelText('Valor promedio del pedido')).toHaveProperty('value', '')
    expect(screen.getByLabelText('Meta H1: retención')).toHaveProperty('value', '2')
    expect(screen.getByLabelText('Meta H2: Restaurantes → Turbo')).toHaveProperty('value', '10')
    expect(screen.getByLabelText('Cobertura: a quiénes llega')).toHaveProperty('value', '100')
    expect(summary()).toMatch(/^Escribe tus supuestos/)
    expect(screen.getAllByText('Faltan supuestos:')).toHaveLength(2)
  })

  test('inputs are labelled, numeric on the phone and carry their unit', () => {
    render(<GoalValue />)
    const users = screen.getByLabelText('Usuarios activos al mes')
    expect(users.getAttribute('inputmode')).toBe('numeric')
    expect(screen.getByLabelText('Valor promedio del pedido').getAttribute('inputmode')).toBe('decimal')
    expect(document.getElementById(users.getAttribute('aria-describedby')).textContent).toBe('usuarios')
  })

  test('with invented numbers: the summary, both readings and the H2', () => {
    render(<GoalValue />)
    fillInvented()
    expect(summary()).toBe(
      'Con tus supuestos, +2 puntos de retención dejan entre 88.002 y 312.000 de margen el primer año; ' +
        '+10 % en Restaurantes → Turbo deja 24.000.',
    )
    const rows = screen.getAllByRole('row').map((row) => row.textContent)
    expect(rows).toContain('Techonadie se va24.000312.000')
    expect(rows.some((row) => row.startsWith('Prudentese va el 50% al mes'))).toBe(true)
    expect(screen.getByText('Clientes nuevos en Turbo').closest('div').textContent).toContain('2.000')
    expect(screen.queryByText('Recupera la inversión')).toBeNull()
  })

  test('with costs: the payback month in each reading', () => {
    render(<GoalValue />)
    fillInvented()
    type('Costo de implementación (una vez)', '50.000')
    type('Costo de operar, al mes', '1.000')
    const rows = screen.getAllByRole('row').map((row) => row.textContent)
    expect(rows).toContain('Techonadie se va24.000312.000Mes 5')
    expect(rows.some((row) => row.endsWith('Mes 9'))).toBe(true)
    expect(screen.getByText(/^Recupera la inversión: no se recupera en 36 meses/)).toBeTruthy()
  })

  test('a bad value is flagged next to its field and the hypothesis waits for it', () => {
    render(<GoalValue />)
    fillInvented()
    type('Retención base', '99')
    const goal = screen.getByLabelText('Meta H1: retención')
    expect(goal.getAttribute('aria-invalid')).toBe('true')
    expect(screen.getByText('Con la retención base pasa de 100 %')).toBeTruthy()
    expect(summary()).toBe('Con tus supuestos, +10 % en Restaurantes → Turbo deja 24.000 de margen el primer año.')
  })

  test('keeps what was typed in this tab, and "Borrar" clears it', () => {
    const { unmount } = render(<GoalValue />)
    type('Valor promedio del pedido', '10')
    expect(JSON.parse(sessionStorage.getItem(STORAGE_KEY)).valor).toBe('10')
    unmount()
    render(<GoalValue />)
    expect(screen.getByLabelText('Valor promedio del pedido')).toHaveProperty('value', '10')
    fireEvent.click(screen.getByRole('button', { name: 'Borrar' }))
    expect(screen.getByLabelText('Valor promedio del pedido')).toHaveProperty('value', '')
    expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull()
  })

  test('with storage blocked it still works', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('bloqueado')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('bloqueado')
    })
    render(<GoalValue />)
    fillInvented()
    expect(summary()).toMatch(/312\.000/)
  })

  test('nothing leaves the browser: no network calls', () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    render(<GoalValue />)
    fillInvented()
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})
