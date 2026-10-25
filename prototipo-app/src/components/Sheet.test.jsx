import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import Sheet from './Sheet'

test('la hoja recibe el foco al abrirse y se cierra con Escape', () => {
  const onClose = vi.fn()
  render(
    <Sheet open onClose={onClose} title="Tu dirección">
      <button type="button">Casa</button>
    </Sheet>,
  )

  expect(screen.getByRole('dialog').contains(document.activeElement)).toBe(true)
  fireEvent.keyDown(document.activeElement, { key: 'Escape' })
  expect(onClose).toHaveBeenCalledTimes(1)
})
