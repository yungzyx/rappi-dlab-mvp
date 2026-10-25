import { cleanup, render } from '@testing-library/react'
import { afterEach, expect, test } from 'vitest'
import TrackingMap from './TrackingMap'

afterEach(cleanup)

const rider = (delivered) =>
  render(<TrackingMap progress={0.5} delivered={delivered} />).container.querySelector('.tracking-rider')

// Safari dibuja mal el HTML animado dentro de un foreignObject: en el mapa, Mochi es SVG puro.
test('Mochi va por la ruta dibujado en SVG, con su pose de la imagen de poses', () => {
  const el = rider(false)
  expect(el.querySelector('foreignObject')).toBeNull()
  const pose = el.querySelector('image')
  expect(pose.getAttribute('href')).toMatch(/mochi-poses/)
  expect(pose.getAttribute('x')).toBe('0') // frontal
})

test('al entregar, Mochi pone su pose feliz', () => {
  expect(rider(true).querySelector('image').getAttribute('x')).toBe('-1')
})

const pose = (props) => {
  const { container } = render(<TrackingMap {...props} />)
  const image = container.querySelector('.tracking-rider image')
  return { x: image.getAttribute('x'), y: image.getAttribute('y'), almost: container.textContent.includes('¡Ya casi!') }
}

test('preparando, Mochi está tímido', () => {
  expect(pose({ progress: 0, step: 1, delivered: false })).toEqual({ x: '0', y: '-1', almost: false })
})

test('al final de la ruta, Mochi está feliz y dice «¡Ya casi!»', () => {
  expect(pose({ progress: 0.9, step: 2, delivered: false })).toEqual({ x: '-1', y: '0', almost: true })
})

test('entregado, feliz y sin «¡Ya casi!»', () => {
  expect(pose({ progress: 1, step: 3, delivered: true })).toEqual({ x: '-1', y: '0', almost: false })
})
