import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, test, vi } from 'vitest'
import ErrorBoundary from './ErrorBoundary'

afterEach(cleanup)

function Broken({ fail }) {
  if (fail) throw new Error('boom')
  return <p>Pantalla sana</p>
}

describe('ErrorBoundary', () => {
  test('una pantalla rota muestra el aviso y «Volver al inicio» llama a onReset y limpia el error', () => {
    const silence = vi.spyOn(console, 'error').mockImplementation(() => {})
    const onReset = vi.fn()
    let fail = true
    const { rerender } = render(
      <ErrorBoundary onReset={onReset}>
        <Broken fail={fail} />
      </ErrorBoundary>,
    )
    expect(screen.getByRole('alert').textContent).toContain('Algo salió mal')

    // Mientras hay error, los hijos nuevos no se renderizan; al volver al inicio sí (y ya no fallan).
    fail = false
    rerender(
      <ErrorBoundary onReset={onReset}>
        <Broken fail={fail} />
      </ErrorBoundary>,
    )
    expect(screen.queryByText('Pantalla sana')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Volver al inicio' }))
    expect(onReset).toHaveBeenCalledTimes(1)
    expect(screen.getByText('Pantalla sana')).toBeTruthy()
    silence.mockRestore()
  })

  test('una pantalla rota también ofrece «Recargar»', () => {
    const silence = vi.spyOn(console, 'error').mockImplementation(() => {})
    const onReload = vi.fn()
    render(
      <ErrorBoundary onReload={onReload}>
        <Broken fail />
      </ErrorBoundary>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Recargar' }))
    expect(onReload).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: 'Volver al inicio' })).toBeTruthy()
    silence.mockRestore()
  })

  test('un error de render fuera de una pantalla muestra «Recargar» (variante raíz)', () => {
    const silence = vi.spyOn(console, 'error').mockImplementation(() => {})
    const onReload = vi.fn()
    render(
      <ErrorBoundary variant="root" onReload={onReload}>
        <Broken fail />
      </ErrorBoundary>,
    )
    expect(screen.getByRole('alert').textContent).toContain('Algo salió mal')
    expect(screen.queryByRole('button', { name: 'Volver al inicio' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Recargar' }))
    expect(onReload).toHaveBeenCalledTimes(1)
    silence.mockRestore()
  })
})
