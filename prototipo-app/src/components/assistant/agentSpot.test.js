import { afterEach, beforeEach, describe, expect, test } from 'vitest'
import { coversControl, tuckLift } from './agentSpot'

// jsdom no calcula el layout: la geometría va a mano. Mochi (68 × 68) en x 310–378, y 700–768, como a la derecha.
const rect = (left, top, width, height) => ({ left, top, width, height, right: left + width, bottom: top + height })
let host
let body
let shapes // [elemento, rect], de arriba hacia abajo

const place = (el, box) => {
  el.getBoundingClientRect = () => box
  shapes.push([el, box])
  return el
}
const control = (box) => place(Object.assign(document.createElement('button'), { type: 'button' }), box)

beforeEach(() => {
  shapes = []
  host = document.createElement('div')
  body = document.createElement('button')
  host.append(body)
  document.body.append(host)
  host.getBoundingClientRect = () => rect(310, 700, 68, 68)
  Object.defineProperties(body, {
    offsetParent: { value: host },
    offsetLeft: { value: 0 },
    offsetTop: { value: 0 },
    offsetWidth: { value: 68 },
    offsetHeight: { value: 68, configurable: true },
  })
  // Lo que hay en cada punto, de arriba hacia abajo: Mochi siempre primero, como en la pantalla.
  document.elementsFromPoint = (x, y) => [
    body,
    ...shapes.filter(([, b]) => x >= b.left && x <= b.right && y >= b.top && y <= b.bottom).map(([el]) => el),
    document.body,
  ]
})
afterEach(() => {
  delete document.elementsFromPoint
  document.body.innerHTML = ''
})

describe('Mochi mira qué tiene debajo', () => {
  test('el "+" de un producto bajo Mochi cuenta', () => {
    document.body.append(control(rect(338, 718, 32, 32)))
    expect(coversControl(body)).toBe(true)
  })

  test('un "+" que asoma justo al lado también (un dedo no es un punto)', () => {
    document.body.append(control(rect(338, 756, 32, 32))) // centro en y 772, 4 px bajo Mochi
    expect(coversControl(body)).toBe(true)
  })

  test('también el que solo asoma bajo el borde de Mochi (centro a 16 px), pero no uno más allá', () => {
    const plus = control(rect(338, 766, 32, 32)) // centro en y 782
    document.body.append(plus)
    expect(coversControl(body)).toBe(true)
    plus.getBoundingClientRect = () => rect(338, 780, 32, 32) // centro en y 796, 28 px bajo Mochi
    shapes[shapes.length - 1][1] = rect(338, 780, 32, 32)
    expect(coversControl(body)).toBe(false)
  })

  test('una fila entera no: se puede tocar en otra parte', () => {
    document.body.append(control(rect(0, 660, 390, 140)))
    expect(coversControl(body)).toBe(false)
  })

  test('lo que tapa otra cosa (una hoja encima) no cuenta', () => {
    const sheet = place(document.createElement('div'), rect(0, 400, 390, 444)) // primero: arriba del "+"
    const plus = control(rect(338, 718, 32, 32))
    document.body.append(plus, sheet)
    expect(coversControl(body)).toBe(false)
  })

  test('sin nada debajo, o sin Mochi en la página, no cuenta', () => {
    expect(coversControl(body)).toBe(false)
    expect(coversControl(null)).toBe(false)
  })
})

describe('Mochi apartado no pisa un "+" con lo que asoma', () => {
  // Apartado asoma desde x 365,2 (310 + 68 − 40,8 + 28) hasta el borde del teléfono (390), con 40,8 px de alto.
  beforeEach(() => {
    const phone = document.createElement('div')
    phone.className = 'phone'
    phone.getBoundingClientRect = () => rect(0, 0, 390, 844)
    phone.append(host)
    document.body.append(phone)
  })

  test('sin nada cerca se queda donde está', () => {
    expect(tuckLift(body)).toBe(0)
  })

  test('si pisaría el borde de un "+" (6 px de su lado derecho), sube de a 24 px hasta que no lo toca', () => {
    // Apartado mide 40,8 × 49 (Mochi es más alto que ancho): a 0 px va de y 719 a 768; a 24, de 695 a 744; a 48, de
    // 671 a 720, sobre el "+" (desde 735)
    Object.defineProperty(body, 'offsetHeight', { value: 82 })
    host.getBoundingClientRect = () => rect(310, 686, 68, 82)
    document.body.append(control(rect(336, 735, 35, 35)))
    expect(tuckLift(body)).toBe(48)
  })

  test('una tarjeta que llega al borde no lo mueve: lo que asoma le tapa muy poco', () => {
    document.body.append(control(rect(200, 600, 190, 240)))
    expect(tuckLift(body)).toBe(0)
  })
})
