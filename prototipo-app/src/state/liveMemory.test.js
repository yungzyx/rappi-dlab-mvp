import { afterEach, describe, expect, test, vi } from 'vitest'

// Recargar la página es volver a cargar el módulo con lo que quedó en la pestaña (sessionStorage).
const reload = async () => {
  vi.resetModules()
  return import('./liveMemory')
}

const ADDED = {
  id: 'cat-94001',
  name: 'Doritos (prueba)',
  vertical: 'express',
  entityType: 'catalog_item',
  entityId: '94001',
}
const MOVE = { key: 1, vertical: 'farmacia', from: 2, to: 1, reason: 'Porque pediste en Farmacia.', resets: 0 }

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('lo pendiente de Mochi en la Home sobrevive a recargar la página', () => {
  test('lo agregado por comentar y el cambio de orden por explicar vuelven al recargar; lo olvidado, no', async () => {
    const before = await reload()
    before.rememberAdded(ADDED)
    before.rememberMove(MOVE)
    const after = await reload()
    expect(after.session.lastAdded).toEqual(ADDED)
    expect(after.session.pendingMove).toEqual(MOVE)

    after.forgetAdded()
    after.rememberMove(null)
    const again = await reload()
    expect(again.session.lastAdded).toBeNull()
    expect(again.session.pendingMove).toBeNull()
  })

  test('"Repetir escena" lo borra, y "Olvidar" también (sus claves son `rappi-proto-*`)', async () => {
    const before = await reload()
    before.rememberAdded(ADDED)
    expect(Object.keys(sessionStorage).every((key) => key.startsWith('rappi-proto-'))).toBe(true)
    before.resetLive()
    expect((await reload()).session.lastAdded).toBeNull()
  })

  test('sin almacenamiento, lo pendiente sigue en memoria', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('bloqueado')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('bloqueado')
    })
    const memory = await reload()
    expect(memory.session.lastAdded).toBeNull()
    memory.rememberAdded(ADDED)
    expect(memory.session.lastAdded).toEqual(ADDED)
  })
})
