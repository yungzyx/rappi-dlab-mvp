import { afterEach, expect, test } from 'vitest'
import { isHushed, isQuiet, noteDismissed, noteEngaged, quietToday, resetQuiet, wake } from './agentQuiet'

afterEach(() => {
  resetQuiet()
  localStorage.clear()
})

test('silenciado hoy, mañana vuelve', () => {
  quietToday('2026-10-09')
  expect(isQuiet('2026-10-09')).toBe(true)
  expect(isQuiet('2026-10-10')).toBe(false)
})

test('despertarlo le quita el silencio de hoy', () => {
  quietToday('2026-10-09')
  wake()
  expect(isQuiet('2026-10-09')).toBe(false)
})

test('dos cierres seguidos lo callan; tocar algo entre medio no', () => {
  noteDismissed()
  noteEngaged()
  noteDismissed()
  expect(isHushed()).toBe(false)
  noteDismissed()
  expect(isHushed()).toBe(true)
})

test('resetQuiet lo despierta', () => {
  quietToday('2026-10-09')
  noteDismissed()
  noteDismissed()
  resetQuiet()
  expect(isQuiet('2026-10-09')).toBe(false)
  expect(isHushed()).toBe(false)
})
