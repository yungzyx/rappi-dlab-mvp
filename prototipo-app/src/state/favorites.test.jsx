import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, test } from 'vitest'
import { FavoritesProvider, useFavorites } from './FavoritesContext'

afterEach(() => localStorage.clear())

const favorites = () => renderHook(() => useFavorites(), { wrapper: FavoritesProvider })

describe('favoritos por tienda', () => {
  test('dos tiendas con el mismo nombre y distinto id se marcan por separado', () => {
    const { result } = favorites()
    const centro = { id: 9101, name: 'Unimarc', vertical: 'grocery' }
    const norte = { id: 9102, name: 'Unimarc', vertical: 'grocery' }

    act(() => result.current.toggle(centro))
    expect(result.current.isFavorite(centro)).toBe(true)
    expect(result.current.isFavorite(norte)).toBe(false)

    act(() => result.current.toggle(norte))
    expect(result.current.stores.map((store) => store.id)).toEqual([9102, 9101])

    act(() => result.current.toggle(centro)) // quitar una no quita la otra
    expect(result.current.isFavorite(centro)).toBe(false)
    expect(result.current.isFavorite(norte)).toBe(true)
  })

  test('los favoritos guardados antes con tiendas locales (sin id numérico) se descartan al cargar: ya no existen', () => {
    const saved = [{ id: 9101, name: 'Unimarc' }]
    localStorage.setItem(
      'rappi-proto-favorites',
      JSON.stringify([{ name: 'Délice', img: 'x.webp' }, { id: 'delice', name: 'Délice 2' }, ...saved]),
    )
    const { result } = favorites()
    expect(result.current.stores).toEqual(saved)
    expect(result.current.isFavorite({ name: 'Délice' })).toBe(false)
    // Lo guardado también queda limpio.
    expect(JSON.parse(localStorage.getItem('rappi-proto-favorites'))).toEqual(saved)
  })

  test('una tienda con id no se confunde con otra que se llama igual pero ya trae su propio id', () => {
    localStorage.setItem('rappi-proto-favorites', JSON.stringify([{ id: 9101, name: 'Unimarc' }]))
    const { result } = favorites()
    expect(result.current.isFavorite({ id: 9101, name: 'Unimarc' })).toBe(true)
    expect(result.current.isFavorite({ id: 9102, name: 'Unimarc' })).toBe(false)
  })
})
