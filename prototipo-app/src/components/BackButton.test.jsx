import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import BackButton from './BackButton'

afterEach(cleanup)

test('se llama «Volver», conserva la clase de la pantalla y llama a onClick', () => {
  const onClick = vi.fn()
  render(<BackButton className="store-round" onClick={onClick} />)
  const button = screen.getByRole('button', { name: 'Volver' })
  expect(button.className).toBe('back-button store-round tap')
  expect(button.querySelector('svg')).toBeTruthy()
  fireEvent.click(button)
  expect(onClick).toHaveBeenCalledTimes(1)
})

test('sin ícono (zona sobre una captura) sigue siendo un botón «Volver»', () => {
  render(<BackButton className="travel-hit" icon={false} onClick={() => {}} />)
  expect(screen.getByRole('button', { name: 'Volver' }).querySelector('svg')).toBeNull()
})
