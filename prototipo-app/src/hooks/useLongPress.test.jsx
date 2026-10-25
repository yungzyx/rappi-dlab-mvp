import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { useLongPress } from './useLongPress'

function Hold({ onLongPress }) {
  const { handlers } = useLongPress(onLongPress)
  return (
    <button type="button" {...handlers}>
      mantener
    </button>
  )
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

test('500 ms quieto dispara; moverse 10 px no; soltar antes no', () => {
  const onLongPress = vi.fn()
  render(<Hold onLongPress={onLongPress} />)
  const button = screen.getByRole('button')

  fireEvent.pointerDown(button, { clientX: 0, clientY: 0 })
  act(() => vi.advanceTimersByTime(500))
  expect(onLongPress).toHaveBeenCalledTimes(1)
  fireEvent.pointerUp(button)

  fireEvent.pointerDown(button, { clientX: 0, clientY: 0 })
  fireEvent.pointerMove(button, { clientX: 0, clientY: 12 }) // es scroll
  act(() => vi.advanceTimersByTime(600))
  expect(onLongPress).toHaveBeenCalledTimes(1)
  fireEvent.pointerUp(button)

  fireEvent.pointerDown(button, { clientX: 0, clientY: 0 })
  act(() => vi.advanceTimersByTime(300))
  fireEvent.pointerUp(button)
  act(() => vi.advanceTimersByTime(600))
  expect(onLongPress).toHaveBeenCalledTimes(1)
})
