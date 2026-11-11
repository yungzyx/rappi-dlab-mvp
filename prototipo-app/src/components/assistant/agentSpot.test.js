import { afterEach, beforeEach, describe, expect, test } from 'vitest'
import { coversControl } from './agentSpot'

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
    offsetHeight: { value: 68 },
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
