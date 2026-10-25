import { beforeEach, describe, expect, test, vi } from 'vitest'

let firstShowing
let noteShown
let noteAccepted

const PAPAS = { id: 'cat-1', name: 'Papas', concept: 'snacks-salados', vertical: 'express' }

describe('sugerencias de Mochi', () => {
  beforeEach(async () => {
    vi.resetModules() // lo ya mostrado vive en el módulo (lo que dura la pestaña)
    ;({ firstShowing, noteShown, noteAccepted } = await import('./suggestions'))
  })

  test('firstShowing cuenta igual la vertical del backend que la del prototipo', () => {
    const row = { concept: 'snacks-salados', vertical: 'conveniencia', origin: 'agent-carrito', generation: 0 }
    expect(firstShowing(row)).toBe(true)
    expect(firstShowing({ ...row, vertical: 'express' })).toBe(false)
    expect(firstShowing({ ...row, generation: 1 })).toBe(true)
    expect(firstShowing({ ...row, origin: 'agent-ask' })).toBe(true)
  })

  test('noteShown registra suggestion_shown con el origen en el payload, una sola vez', () => {
    const track = vi.fn()
    const fields = { origin: 'agent-carrito', concept: 'snacks-salados', vertical: 'conveniencia' }
    expect(noteShown(track, [], fields)).toBe(true)
    expect(noteShown(track, [], fields)).toBe(false)
    expect(track).toHaveBeenCalledTimes(1)
    expect(track).toHaveBeenCalledWith('suggestion_shown', {
      concept_id: 'snacks-salados',
      vertical: 'conveniencia',
      payload: { origen: 'agent-carrito' },
    })
  })

  test('noteShown toma el concepto y la vertical del primer producto si no se dan', () => {
    const track = vi.fn()
    noteShown(track, [PAPAS], { origin: 'agent-carrito' })
    expect(track).toHaveBeenCalledWith('suggestion_shown', {
      concept_id: 'snacks-salados',
      vertical: 'express',
      payload: { origen: 'agent-carrito' },
    })
  })

  test('noteAccepted registra la mostrada que falte y luego suggestion_accepted, una vez por sugerencia', () => {
    const track = vi.fn()
    const options = { origin: 'agent-carrito', generation: 0 }
    expect(noteAccepted(track, [PAPAS], options)).toBe(1)
    expect(track.mock.calls.map(([type]) => type)).toEqual(['suggestion_shown', 'suggestion_accepted'])
    expect(track.mock.calls[1][1]).toEqual({
      concept_id: 'snacks-salados',
      vertical: 'express',
      payload: { origen: 'agent-carrito' },
    })

    // Otro clic en lo mismo no es otra aceptación; tras «Olvidar» (otra generación) sí.
    track.mockClear()
    expect(noteAccepted(track, [PAPAS], options)).toBe(0)
    expect(track).not.toHaveBeenCalled()
    expect(noteAccepted(track, [PAPAS], { ...options, generation: 1 })).toBe(1)
  })

  test('agregar el kit completo registra una aceptación por producto', () => {
    const track = vi.fn()
    const kit = [PAPAS, { ...PAPAS, id: 'cat-2', concept: 'cerveza', vertical: 'liquor' }, PAPAS]
    expect(noteAccepted(track, kit, { origin: 'agent-plan', generation: 0 })).toBe(2)
    expect(track.mock.calls.filter(([type]) => type === 'suggestion_accepted')).toHaveLength(2)
  })

  test('sin concepto no registra la mostrada, pero la aceptada sí (sin concept_id), una vez por producto', () => {
    const track = vi.fn()
    noteShown(track, [], { origin: 'agent-carrito', vertical: 'express' })
    expect(track).not.toHaveBeenCalled()

    const loose = { id: 'x', name: 'Algo', vertical: 'express', entityId: '77' }
    expect(noteAccepted(track, [loose, { ...loose, id: 'y', entityId: '78' }], { origin: 'agent-carrito' })).toBe(2)
    expect(track.mock.calls.map(([type]) => type)).toEqual(['suggestion_accepted', 'suggestion_accepted'])
    expect(track).toHaveBeenCalledWith('suggestion_accepted', {
      concept_id: undefined,
      vertical: 'express',
      payload: { origen: 'agent-carrito' },
    })
    expect(noteAccepted(track, [loose], { origin: 'agent-carrito' })).toBe(0)
  })
})
