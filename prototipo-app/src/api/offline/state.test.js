import { afterEach, expect, test, vi } from 'vitest'
import { addEvents, readState, writeState } from './state'

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

test('si el navegador rechaza guardar (cuota llena), lo último escrito sigue valiendo en esta pestaña', () => {
  writeState({ userId: 'proto-1', events: [], orders: [], preferences: [] })
  const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new DOMException('QuotaExceededError', 'QuotaExceededError')
  })
  addEvents([{ type: 'vertical_open', vertical: 'farmacia', ts: 1 }])
  expect(readState().events).toHaveLength(1) // no la copia anterior que quedó en localStorage

  setItem.mockRestore() // con espacio otra vez, se guarda y se lee de ahí
  addEvents([{ type: 'vertical_open', vertical: 'licores', ts: 2 }])
  expect(JSON.parse(localStorage.getItem('rappi-proto-offline-api')).events).toHaveLength(2)
  expect(readState().events).toHaveLength(2)
})
