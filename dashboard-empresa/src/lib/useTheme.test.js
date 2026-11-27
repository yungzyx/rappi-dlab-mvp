import { afterEach, describe, expect, it } from 'vitest'
import { storedTheme } from './useTheme.js'

const KEY = 'panel-empresa:tema'

afterEach(() => {
  localStorage.clear()
  window.history.replaceState(null, '', '/')
})

describe('storedTheme', () => {
  it('sin elección ni parámetro sigue al sistema', () => {
    expect(storedTheme()).toBeNull()
  })

  it('?tema=claro fija el tema claro y lo guarda, aunque antes se eligiera oscuro', () => {
    localStorage.setItem(KEY, 'dark')
    window.history.replaceState(null, '', '/?tema=claro')
    expect(storedTheme()).toBe('light')
    expect(localStorage.getItem(KEY)).toBe('light')
  })

  it('?tema=oscuro fija el oscuro; un valor desconocido no cambia nada', () => {
    window.history.replaceState(null, '', '/?tema=oscuro')
    expect(storedTheme()).toBe('dark')
    window.history.replaceState(null, '', '/?tema=rosado')
    expect(storedTheme()).toBe('dark')
  })
})
