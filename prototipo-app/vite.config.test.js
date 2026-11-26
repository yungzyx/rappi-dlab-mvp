// @vitest-environment node
import { describe, expect, test } from 'vitest'
import config from './vite.config.js'

const OFFLINE = 'import.meta.env.VITE_OFFLINE_DEMO'

describe('la API simulada solo entra al build de la demo', () => {
  test('un VITE_OFFLINE_DEMO=1 heredado del entorno no la mete en un build normal', () => {
    for (const mode of ['production', 'development']) {
      const { define } = config({ command: 'build', mode })
      expect(define[OFFLINE]).toBe(JSON.stringify(''))
    }
  })

  test('el servidor de desarrollo tampoco la usa', () => {
    expect(config({ command: 'serve', mode: 'development' }).define[OFFLINE]).toBe(JSON.stringify(''))
  })

  test('el build de la demo sí la lleva', () => {
    expect(config({ command: 'build', mode: 'demo' }).define[OFFLINE]).toBe(JSON.stringify('1'))
  })
})
