import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, test } from 'vitest'
import { useNavigation } from './useNavigation'

const names = (result) => result.current.stack.map((entry) => entry.name)

describe('useNavigation', () => {
  beforeEach(() => window.history.replaceState(null, '', '/'))

  test('push agrega pantalla, entrada de historial y ruta legible', () => {
    const { result } = renderHook(() => useNavigation())
    const before = window.history.length
    act(() => result.current.push('vertical', { id: 'pet' }))
    expect(names(result)).toEqual(['home', 'vertical'])
    expect(window.history.length).toBe(before + 1)
    expect(window.location.hash).toBe('#/vertical')
    expect(window.history.state.nav.stack[1].params).toEqual({ id: 'pet' })
  })

  test('replace no crea entrada de historial pero sí apila la pantalla', () => {
    const { result } = renderHook(() => useNavigation())
    const before = window.history.length
    act(() => result.current.push('store', {}, { replace: true }))
    expect(names(result)).toEqual(['home', 'store'])
    expect(window.history.length).toBe(before)
  })

  test('swap cambia la pantalla actual por otra (checkout → seguimiento)', () => {
    const { result } = renderHook(() => useNavigation())
    act(() => result.current.push('checkout'))
    const before = window.history.length
    act(() => result.current.push('tracking', { orderId: 'x' }, { swap: true }))
    expect(names(result)).toEqual(['home', 'tracking'])
    expect(window.history.length).toBe(before)
    expect(window.location.hash).toBe('#/tracking')
  })

  test('cambiar de pestaña no crea historial', () => {
    const { result } = renderHook(() => useNavigation())
    const before = window.history.length
    act(() => result.current.setHomeTab('offers'))
    expect(result.current.homeTab).toBe('offers')
    expect(window.history.length).toBe(before)
    expect(window.location.hash).toBe('#/offers')
  })
})

describe('volver al inicio y enlaces escritos a mano', () => {
  test('reset deja solo la Home sin crear historial', () => {
    const { result } = renderHook(() => useNavigation())
    act(() => result.current.push('checkout'))
    act(() => result.current.push('tracking', { orderId: 'x' }, { swap: true }))
    const before = window.history.length
    act(() => result.current.reset())
    expect(names(result)).toEqual(['home'])
    expect(result.current.direction).toBe('pop')
    expect(window.history.length).toBe(before)
    expect(window.location.hash).toBe('#/home')
  })

  test('un hash escrito a mano (popstate sin estado) navega a esa pantalla o pestaña', () => {
    const { result } = renderHook(() => useNavigation())
    window.location.hash = '#/restaurants'
    act(() => window.dispatchEvent(new PopStateEvent('popstate', { state: null })))
    expect(names(result)).toEqual(['home', 'restaurants'])
    expect(window.history.state.nav.stack[1]).toEqual({ name: 'restaurants', params: {} })

    window.location.hash = '#/offers'
    act(() => window.dispatchEvent(new PopStateEvent('popstate', { state: null })))
    expect(names(result)).toEqual(['home'])
    expect(result.current.homeTab).toBe('offers')
  })

  test('al cargar con un hash y sin estado se lee la ruta; lo que necesita parámetros se ignora', () => {
    window.location.hash = '#/store'
    const { result } = renderHook(() => useNavigation())
    expect(names(result)).toEqual(['home'])
    window.history.replaceState(null, '', '/')
  })

  test('#/game ya no existe: abre la Home', () => {
    window.location.hash = '#/game'
    const { result } = renderHook(() => useNavigation())
    expect(names(result)).toEqual(['home'])
    window.history.replaceState(null, '', '/')
  })
})
