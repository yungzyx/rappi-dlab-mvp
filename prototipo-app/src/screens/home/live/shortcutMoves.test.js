import { renderHook } from '@testing-library/react'
import { afterEach, describe, expect, test } from 'vitest'
import { SEEN_KEY, biggestRise, moveText, readSeen, useShortcutMove } from './shortcutMoves'

afterEach(() => localStorage.clear())

describe('qué acceso se movió', () => {
  test('el que más lugares subió; a igual subida, el que quedó más adelante', () => {
    expect(biggestRise(['a', 'b', 'c', 'd'], ['c', 'a', 'b', 'd'])).toEqual({ vertical: 'c', from: 2, to: 0 })
    expect(biggestRise(['a', 'b', 'c', 'd'], ['b', 'a', 'd', 'c'])).toEqual({ vertical: 'b', from: 1, to: 0 })
    expect(biggestRise(['a', 'b'], ['a', 'b'])).toBeNull()
  })
})

describe('lo que dice Mochi', () => {
  test('con la razón de la API la dice, sin el "Porque"', () => {
    const reason = { text: 'Porque entras seguido a Rappi Mall.', basis: [] }
    expect(moveText({ vertical: 'mall', to: 0, reason })).toBe(
      'Moví Rappi Mall al primer lugar: entras seguido a Rappi Mall.',
    )
    expect(moveText({ vertical: 'supermercado', to: 0, reason: { text: 'Porque pides seguido en el súper.' } })).toBe(
      'Moví Súper al primer lugar: pides seguido en el súper.',
    )
  })

  test('sin razón (solo el primero la trae) no inventa una: el orden sigue lo que más usa', () => {
    expect(moveText({ vertical: 'licores', to: 2, reason: null })).toBe(
      'Moví Licores más adelante, según lo que más usas.',
    )
  })
})

describe('el último orden visto', () => {
  test('es de cada persona: el de otra no cuenta', () => {
    localStorage.setItem(SEEN_KEY, JSON.stringify({ user: 'u-1', order: ['mall'] }))
    expect(readSeen('u-1')).toEqual(['mall'])
    expect(readSeen('u-2')).toBeNull()
  })

  test('sin nada guardado (o roto), no hay orden anterior', () => {
    expect(readSeen('u-1')).toBeNull()
    localStorage.setItem(SEEN_KEY, '{roto')
    expect(readSeen('u-1')).toBeNull()
  })
})

describe('el cambio de orden y "Olvidar"', () => {
  test('el cambio lleva la generación en que nació; tras "Olvidar" no vuelve el de antes', () => {
    localStorage.setItem('rappi-proto-user', 'proto-olvida')
    localStorage.setItem(SEEN_KEY, JSON.stringify({ user: 'proto-olvida', order: ['a', 'b'] }))
    const { result, rerender } = renderHook(
      ({ resets }) => useShortcutMove({ order: ['b', 'a'], entries: [], requestId: 'r' }, { active: true, resets }),
      { initialProps: { resets: 0 } },
    )
    expect(result.current.move).toMatchObject({ vertical: 'b', from: 1, to: 0, resets: 0 })
    rerender({ resets: 1 }) // "Olvidar" sin recargar (el borrado falló): el mismo orden ya no es un cambio
    expect(result.current.move).toBeNull()
  })

  test('dos cambios separados por un "Olvidar" tienen keys distintas (los accesos se vuelven a deslizar)', () => {
    localStorage.setItem('rappi-proto-user', 'proto-olvida')
    localStorage.setItem(SEEN_KEY, JSON.stringify({ user: 'proto-olvida', order: ['a', 'b', 'c'] }))
    const { result, rerender } = renderHook(
      ({ order, resets }) => useShortcutMove({ order, entries: [], requestId: 'r' }, { active: true, resets }),
      { initialProps: { order: ['b', 'a', 'c'], resets: 0 } },
    )
    const first = result.current.move.key
    rerender({ order: ['b', 'a', 'c'], resets: 1 }) // "Olvidar" sin recargar
    expect(result.current.move).toBeNull()
    rerender({ order: ['c', 'b', 'a'], resets: 1 }) // otro cambio, ya en la generación nueva
    expect(result.current.move).toMatchObject({ vertical: 'c', resets: 1 })
    expect(result.current.move.key).not.toBe(first)
  })
})
