import { beforeEach, describe, expect, test, vi } from 'vitest'

let firstShowing
let noteShown
let noteAccepted
let noteOfferShown
let noteDismissal
let noteOfferDismissal

const PAPAS = { id: 'cat-1', name: 'Papas', concept: 'snacks-salados', vertical: 'express' }

describe('sugerencias de Mochi', () => {
  beforeEach(async () => {
    vi.resetModules() // lo ya mostrado vive en el módulo (lo que dura la pestaña)
    ;({ firstShowing, noteShown, noteAccepted, noteOfferShown, noteDismissal, noteOfferDismissal } =
      await import('./suggestions'))
  })

  test('firstShowing cuenta igual la vertical del backend que la del prototipo', () => {
    const row = { concept: 'snacks-salados', vertical: 'conveniencia', origin: 'agent-carrito', generation: 0 }
    expect(firstShowing(row)).toBe(true)
    expect(firstShowing({ ...row, vertical: 'express' })).toBe(false)
    expect(firstShowing({ ...row, generation: 1 })).toBe(true)
    expect(firstShowing({ ...row, origin: 'agent-ask' })).toBe(true)
  })

  test('noteShown registra suggestion_shown con su origen, una sola vez', () => {
    const track = vi.fn()
    const fields = { origin: 'agent-carrito', concept: 'snacks-salados', vertical: 'conveniencia' }
    expect(noteShown(track, [], fields)).toBe(true)
    expect(noteShown(track, [], fields)).toBe(false)
    expect(track).toHaveBeenCalledTimes(1)
    expect(track).toHaveBeenCalledWith('suggestion_shown', {
      concept_id: 'snacks-salados',
      vertical: 'conveniencia',
      origin: 'agent-carrito',
    })
  })

  test('noteShown toma el concepto y la vertical del primer producto si no se dan', () => {
    const track = vi.fn()
    noteShown(track, [PAPAS], { origin: 'agent-carrito' })
    expect(track).toHaveBeenCalledWith('suggestion_shown', {
      concept_id: 'snacks-salados',
      vertical: 'express',
      origin: 'agent-carrito',
    })
  })

  test('noteShown suma de qué sale el "¿Por qué?" (los tipos de su basis), nunca su texto ni sus ids', () => {
    const track = vi.fn()
    const reason = {
      text: 'Porque buscaste "pizza hawaiana" y aquí sí hay.',
      concept: 'pizza',
      basis: [
        { id: 'pizza hawaiana', kind: 'busqueda', source: 'contexto' },
        { id: 'otra', kind: 'busqueda', source: 'contexto' },
        { id: 'pizza', kind: 'concepto', source: 'eventos' },
      ],
    }
    noteShown(track, [], { origin: 'agent-sin_resultado', concept: 'pizza', vertical: 'restaurantes', reason })
    noteShown(track, [], { origin: 'para-ti', concept: 'pizza', vertical: 'restaurantes', kind: 'lo_mas_pedido' })
    noteShown(track, [], { origin: 'agent-carrito', concept: 'pizza', vertical: 'restaurantes', reason: { basis: [] } })
    expect(track.mock.calls.map(([, fields]) => fields.payload)).toEqual([
      { basis: ['busqueda', 'concepto'] },
      { kind: 'lo_mas_pedido' },
      undefined,
    ])
  })

  test('noteOfferShown registra una oferta con el origen de su momento, el concepto de su razón y su basis', () => {
    const track = vi.fn()
    const made = {
      moment: 'volver',
      products: [PAPAS, { ...PAPAS, id: 'cat-2' }],
      reason: { concept: 'snacks-salados', basis: [{ kind: 'vuelta', id: 'express', source: 'pedidos' }] },
    }
    expect(noteOfferShown(track, made, { generation: 2, kind: 'vuelta' })).toBe(true)
    expect(noteOfferShown(track, made, { generation: 2, products: [PAPAS] })).toBe(false) // ya contada
    expect(track).toHaveBeenCalledTimes(1)
    expect(track).toHaveBeenCalledWith('suggestion_shown', {
      concept_id: 'snacks-salados',
      vertical: 'express',
      origin: 'agent-volver',
      payload: { kind: 'vuelta', basis: ['vuelta'] },
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
      origin: 'agent-carrito',
    })

    // Otro clic en lo mismo no es otra aceptación; tras "Olvidar" (otra generación) sí.
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
      origin: 'agent-carrito',
    })
    expect(noteAccepted(track, [loose], { origin: 'agent-carrito' })).toBe(0)
  })

  test('noteOfferDismissal registra el rechazo con el concepto y el origen de la mostrada, una vez por pestaña', () => {
    const track = vi.fn()
    const made = { moment: 'recompra', products: [PAPAS], reason: { concept: 'snacks-salados' } }
    expect(noteOfferDismissal(track, made, { generation: 0 })).toBe(true)
    expect(noteOfferDismissal(track, made, { generation: 0 })).toBe(false)
    expect(noteOfferDismissal(track, made, { generation: 1 })).toBe(true) // tras "Olvidar" vuelve a contar
    expect(track).toHaveBeenCalledTimes(2)
    expect(track).toHaveBeenCalledWith('suggestion_dismissed', {
      concept_id: 'snacks-salados',
      vertical: 'express',
      origin: 'agent-recompra',
    })
  })

  test('noteDismissal toma el concepto del primer producto y sin concepto no registra nada', () => {
    const track = vi.fn()
    noteDismissal(track, [PAPAS], { origin: 'agent-vertical_por_probar' })
    expect(track).toHaveBeenCalledWith('suggestion_dismissed', {
      concept_id: 'snacks-salados',
      vertical: 'express',
      origin: 'agent-vertical_por_probar',
    })
    track.mockClear()
    expect(noteDismissal(track, [], { origin: 'agent-vertical_por_probar' })).toBe(false)
    expect(track).not.toHaveBeenCalled()
  })

  test('la oferta que se fue sola lleva payload.kind expirada y se cuenta aparte del rechazo', () => {
    const track = vi.fn()
    const made = { moment: 'carrito', products: [PAPAS], reason: { concept: 'snacks-salados' } }
    expect(noteOfferDismissal(track, made, { kind: 'expirada' })).toBe(true)
    expect(noteOfferDismissal(track, made, { kind: 'expirada' })).toBe(false) // una vez por pestaña, como el rechazo
    expect(track).toHaveBeenCalledWith('suggestion_dismissed', {
      concept_id: 'snacks-salados',
      vertical: 'express',
      origin: 'agent-carrito',
      payload: { kind: 'expirada' },
    })
    // Que se haya ido sola no impide registrar el "Ahora no" de la misma oferta cuando vuelve.
    expect(noteOfferDismissal(track, made)).toBe(true)
    expect(track).toHaveBeenLastCalledWith('suggestion_dismissed', {
      concept_id: 'snacks-salados',
      vertical: 'express',
      origin: 'agent-carrito',
    })
  })
})
