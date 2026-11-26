// @vitest-environment node
import { describe, expect, test } from 'vitest'
import { DEFAULT_API, unsafeApi } from './screenshots.mjs'

describe('las capturas no escriben en la API del MVP', () => {
  test('por defecto apuntan a una API propia en otro puerto de este equipo', () => {
    expect(new URL(DEFAULT_API).port).not.toBe('8000')
    expect(unsafeApi(DEFAULT_API, {})).toBeNull()
  })

  test('se niegan al puerto 8000 (make mvp, sobre `rappi`) y a un host que no es de este equipo', () => {
    expect(unsafeApi('http://localhost:8000', {})).toMatch(/8000/)
    expect(unsafeApi('http://127.0.0.1:8000', {})).toMatch(/8000/)
    expect(unsafeApi('https://dlab-mvp.com/api', {})).toMatch(/este equipo/)
  })

  test('SCREENSHOTS_ALLOW_MAIN_API=1 lo permite (una copia en el 8000)', () => {
    expect(unsafeApi('http://localhost:8000', { SCREENSHOTS_ALLOW_MAIN_API: '1' })).toBeNull()
  })
})
