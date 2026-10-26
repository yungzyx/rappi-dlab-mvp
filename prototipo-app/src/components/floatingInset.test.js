import { describe, expect, test } from 'vitest'
import { FLOATING_GAP, floatingInset } from './floatingInset'

// Elementos de mentira: jsdom no calcula el layout, así que la geometría va a mano (alto del teléfono 874).
const phone = { clientHeight: 874 }
const at = (offsetTop, offsetHeight, offsetParent = phone) => ({ isConnected: true, offsetTop, offsetHeight, offsetParent })

describe('relleno de lo que flota abajo', () => {
  test('sin nada flotando no hay relleno', () => {
    expect(floatingInset(phone, [])).toBe(0)
  })

  test('cuenta lo más alto: Mochi sobre el carro y «Pedido en curso»', () => {
    const cart = at(874 - 28 - 52, 52) // «Ver carro», 28 px sobre el borde
    const order = at(874 - 88 - 48, 48) // «Pedido en curso» sobre el carro
    const presence = at(874 - 92 - 68, 68) // el contenedor de Mochi sobre el carro
    const mochi = at(0, 68, presence) // Mochi dentro de su contenedor
    expect(floatingInset(phone, [cart, order, mochi])).toBe(92 + 68 + FLOATING_GAP)
  })

  test('lo que no se ve o ya salió del documento no cuenta', () => {
    const cart = at(874 - 80, 52)
    expect(floatingInset(phone, [cart, { ...at(100, 0) }, { ...at(100, 40), isConnected: false }])).toBe(
      80 + FLOATING_GAP,
    )
  })
})
