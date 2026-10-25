import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { DemoProvider } from '../state/DemoContext'
import DemoToggle from './DemoToggle'

afterEach(() => {
  cleanup()
  vi.unstubAllEnvs()
})

const renderToggle = () =>
  render(
    <DemoProvider>
      <DemoToggle />
    </DemoProvider>,
  )

describe('DemoToggle', () => {
  test('en desarrollo muestra los dos modos', () => {
    renderToggle()
    expect(screen.getByRole('radiogroup', { name: 'Modo de la demo' })).toBeTruthy()
  })

  test('sin VITE_DEMO no se dibuja', () => {
    vi.stubEnv('DEV', false)
    vi.stubEnv('VITE_DEMO', '')
    const { container } = renderToggle()
    expect(container.innerHTML).toBe('')
  })

  test('con VITE_DEMO=1 se dibuja aunque no sea desarrollo', () => {
    vi.stubEnv('DEV', false)
    vi.stubEnv('VITE_DEMO', '1')
    renderToggle()
    expect(screen.getByRole('radiogroup', { name: 'Modo de la demo' })).toBeTruthy()
  })
})
