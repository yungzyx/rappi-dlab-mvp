import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, test } from 'vitest'
import { ToastProvider } from '../../components/Toast'
import TravelScreen from './TravelScreen'

afterEach(cleanup)

test('el buscador de destinos tiene nombre para un lector de pantalla (no solo el placeholder)', () => {
  render(
    <ToastProvider>
      <TravelScreen back={() => {}} />
    </ToastProvider>,
  )
  const field = screen.getByPlaceholderText('¿A dónde te llevamos hoy?')
  expect(field.getAttribute('aria-label')).toBe('¿A dónde te llevamos hoy?')
})
