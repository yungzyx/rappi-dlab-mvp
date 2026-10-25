import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { pressable } from './pressable'

function Card({ onPress, onInner }) {
  return (
    <div {...pressable(onPress)} data-testid="card">
      <button type="button" onClick={onInner}>
        interno
      </button>
    </div>
  )
}

describe('pressable', () => {
  afterEach(cleanup)

  test('se enfoca y responde a clic, Enter y Espacio', () => {
    const onPress = vi.fn()
    render(<Card onPress={onPress} onInner={() => {}} />)
    const card = screen.getByTestId('card')
    expect(card.getAttribute('role')).toBe('button')
    expect(card.tabIndex).toBe(0)
    fireEvent.click(card)
    fireEvent.keyDown(card, { key: 'Enter' })
    fireEvent.keyDown(card, { key: ' ' })
    fireEvent.keyDown(card, { key: 'a' })
    expect(onPress).toHaveBeenCalledTimes(3)
  })

  test('las teclas en un botón interno no activan la tarjeta', () => {
    const onPress = vi.fn()
    render(<Card onPress={onPress} onInner={() => {}} />)
    fireEvent.keyDown(screen.getByText('interno'), { key: 'Enter' })
    expect(onPress).not.toHaveBeenCalled()
  })
})
