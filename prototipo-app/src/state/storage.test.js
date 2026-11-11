import { afterEach, describe, expect, test } from 'vitest'
import { sessionId } from './EventsContext'
import { tabStore } from './storage'

const original = Object.getOwnPropertyDescriptor(globalThis, 'sessionStorage')
afterEach(() => {
  tabStore.clear() // la memoria, con el almacenamiento todavía cambiado
  Object.defineProperty(globalThis, 'sessionStorage', original)
})

/** Un sessionStorage que acepta `accepts` escrituras y después lanza QuotaExceededError. */
function fillsUpAfter(accepts) {
  const data = new Map()
  let writes = 0
  const fake = {
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => {
      if (++writes > accepts) throw new DOMException('Cuota llena', 'QuotaExceededError')
      data.set(key, String(value))
    },
    removeItem: (key) => data.delete(key),
    key: (i) => [...data.keys()][i] ?? null,
    get length() {
      return data.size
    },
  }
  Object.defineProperty(globalThis, 'sessionStorage', { configurable: true, value: fake })
  return data
}

describe('almacenamiento con respaldo en memoria', () => {
  test('si el navegador aceptó un valor y rechaza el siguiente (cuota llena), se lee el más nuevo', () => {
    const data = fillsUpAfter(1)
    expect(tabStore.set('rappi-proto-x', 'v1')).toBe(true)
    expect(tabStore.set('rappi-proto-x', 'v2')).toBe(false)
    expect(data.get('rappi-proto-x')).toBe('v1') // en el navegador quedó el viejo
    expect(tabStore.get('rappi-proto-x')).toBe('v2')
  })

  test('con la cuota llena la sesión sigue: mismo id y la actividad la alarga', () => {
    fillsUpAfter(1)
    const t0 = 1_000_000
    const id = sessionId(t0) // la primera escritura entra al navegador; las siguientes, a la memoria
    expect(sessionId(t0 + 20 * 60 * 1000)).toBe(id)
    expect(sessionId(t0 + 40 * 60 * 1000)).toBe(id) // 20 min después de la última actividad, no 40 de la primera
  })
})
