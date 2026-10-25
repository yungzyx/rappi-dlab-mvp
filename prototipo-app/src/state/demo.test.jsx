import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DemoProvider, MODE_LABELS, useDemo } from './DemoContext'

const wrapper = ({ children }) => <DemoProvider>{children}</DemoProvider>

describe('modos de la demo: «Rappi hoy» y «Prototipo final»', () => {
  beforeEach(() => localStorage.clear())

  it('son dos: lo que hay hoy y el prototipo final, que arranca por defecto', () => {
    const { result } = renderHook(() => useDemo(), { wrapper })
    expect(result.current.mode).toBe('final')
    expect(result.current.isFinal).toBe(true)
    expect(Object.keys(MODE_LABELS)).toEqual(['final', 'actual'])
    expect(MODE_LABELS).toEqual({ final: 'Prototipo final ✨', actual: 'Rappi hoy' })
  })

  it('«Rappi hoy» guardado se respeta', () => {
    localStorage.setItem('rappi-proto-demo-mode', 'actual')
    const { result } = renderHook(() => useDemo(), { wrapper })
    expect(result.current.mode).toBe('actual')
    expect(result.current.isFinal).toBe(false)
  })

  it.each(['propuesta', 'vivo', 'otra-cosa'])('un modo viejo guardado («%s») entra al prototipo final', (saved) => {
    localStorage.setItem('rappi-proto-demo-mode', saved)
    const { result } = renderHook(() => useDemo(), { wrapper })
    expect(result.current.mode).toBe('final')
  })

  it('la tecla D y «toggle» alternan entre los dos', () => {
    const { result } = renderHook(() => useDemo(), { wrapper })
    const seen = [result.current.mode]
    for (let i = 0; i < 2; i += 1) {
      act(() => result.current.toggle())
      seen.push(result.current.mode)
    }
    expect(seen).toEqual(['final', 'actual', 'final'])
  })
})

describe('la tecla D y el interruptor solo en desarrollo o con VITE_DEMO=1', () => {
  const pressD = () => act(() => void window.dispatchEvent(new KeyboardEvent('keydown', { key: 'd' })))

  beforeEach(() => {
    cleanup() // los árboles de las pruebas de arriba siguen escuchando el teclado
    localStorage.clear()
  })
  afterEach(() => {
    cleanup()
    vi.unstubAllEnvs()
  })

  it('en desarrollo la tecla D cambia de modo, también en mayúscula', () => {
    const { result } = renderHook(() => useDemo(), { wrapper })
    pressD()
    expect(result.current.mode).toBe('actual')
    act(() => void window.dispatchEvent(new KeyboardEvent('keydown', { key: 'D' })))
    expect(result.current.mode).toBe('final')
  })

  it('sin VITE_DEMO la tecla D no hace nada', () => {
    vi.stubEnv('DEV', false)
    vi.stubEnv('VITE_DEMO', '')
    const { result } = renderHook(() => useDemo(), { wrapper })
    pressD()
    expect(result.current.mode).toBe('final')
    expect(localStorage.getItem('rappi-proto-demo-mode')).toBeNull()
  })

  it('sin VITE_DEMO, un «Rappi hoy» guardado no se aplica: es solo de la demo', () => {
    localStorage.setItem('rappi-proto-demo-mode', 'actual')
    vi.stubEnv('DEV', false)
    vi.stubEnv('VITE_DEMO', '')
    const { result } = renderHook(() => useDemo(), { wrapper })
    expect(result.current.mode).toBe('final')
  })

  it('con VITE_DEMO=1 la tecla D funciona aunque no sea desarrollo', () => {
    vi.stubEnv('DEV', false)
    vi.stubEnv('VITE_DEMO', '1')
    const { result } = renderHook(() => useDemo(), { wrapper })
    pressD()
    expect(result.current.mode).toBe('actual')
  })

  it('keydown sin key no lanza (Chrome lo dispara al autocompletar)', () => {
    const { result } = renderHook(() => useDemo(), { wrapper })
    expect(() => act(() => void window.dispatchEvent(new Event('keydown')))).not.toThrow()
    expect(result.current.mode).toBe('final')
  })
})
