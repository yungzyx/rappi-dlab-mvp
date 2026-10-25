import { afterEach, describe, expect, test, vi } from 'vitest'
import { typedEnd } from './typed'

describe('typedEnd: hasta dónde se ve un texto escrito letra por letra', () => {
  test('sin emojis, lo pedido', () => {
    expect(typedEnd('Hola', 0)).toBe(0)
    expect(typedEnd('Hola', 2)).toBe(2)
    expect(typedEnd('Hola', 9)).toBe(4)
  })

  test('nunca parte un emoji (🧡 son dos unidades de UTF-16): queda antes hasta que entra entero', () => {
    const text = 'Hola 🧡 chao'
    expect(typedEnd(text, 6)).toBe(5)
    expect(typedEnd(text, 7)).toBe(7)
  })

  test('tampoco un emoji con variante o de varias piezas', () => {
    expect(typedEnd('a❤️b', 2)).toBe(1) // ❤ + selector de variante
    expect(typedEnd('a👩‍🍳b', 3)).toBe(1) // cocinera: mujer + unión + sartén
    expect(typedEnd('a👩‍🍳b', 6)).toBe(6)
  })

  describe('sin Intl.Segmenter (navegadores viejos, como Firefox antes de la 125)', () => {
    afterEach(() => {
      vi.unstubAllGlobals()
      vi.resetModules()
    })

    test('la app no se cae y tampoco parte un emoji simple', async () => {
      vi.stubGlobal('Intl', { ...Intl, Segmenter: undefined })
      vi.resetModules()
      const { typedEnd: withoutSegmenter } = await import('./typed')
      expect(withoutSegmenter('Hola 🧡 chao', 6)).toBe(5)
      expect(withoutSegmenter('Hola 🧡 chao', 7)).toBe(7)
      expect(withoutSegmenter('Hola', 9)).toBe(4)
    })
  })
})
