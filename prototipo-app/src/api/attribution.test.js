import { beforeEach, describe, expect, test, vi } from 'vitest'

let envelope
let placeList
let placementFields
let noteRecommendationClick
let noteItemView

describe('el sobre de los eventos (attribution.js)', () => {
  beforeEach(async () => {
    vi.resetModules() // lo ya clicado vive en el módulo (lo que dura la pestaña)
    ;({ envelope, placeList, placementFields, noteRecommendationClick, noteItemView } = await import('./attribution'))
  })

  test('envelope arma solo los campos que la API acepta', () => {
    expect(envelope({ surface: 'home', origin: 'accesos', position: 2, requestId: 'abc123' })).toEqual({
      surface: 'home',
      origin: 'accesos',
      position: 2,
      request_id: 'abc123',
    })
    // Una pantalla desconocida, un origen con mayúsculas, una posición negativa o un id con espacios no se mandan:
    // harían rechazar el lote entero.
    expect(envelope({ surface: 'otra', origin: 'Con Mayúsculas', position: -1, requestId: 'con espacios' })).toEqual({})
    expect(envelope()).toEqual({})
  })

  test('placeList marca cada elemento con su lista y su posición, desde `start`', () => {
    const placed = placeList([{ id: 'a' }, { id: 'b' }], {
      surface: 'search',
      origin: 'resultados',
      requestId: 'r1',
      start: 3,
    })
    expect(placed.map(placementFields)).toEqual([
      { surface: 'search', origin: 'resultados', position: 3, request_id: 'r1' },
      { surface: 'search', origin: 'resultados', position: 4, request_id: 'r1' },
    ])
    expect(placeList(undefined, { surface: 'home' })).toEqual([])
    expect(placementFields({ id: 'sin lugar' })).toEqual({})
  })

  test('abrir una recomendación es un recommendation_click, una sola vez; lo demás no', () => {
    const track = vi.fn()
    const [juice] = placeList([{ id: 'j' }], { surface: 'agent', origin: 'para-ti', requestId: 'r2' })
    const fields = { entity_type: 'catalog_item', entity_id: '91001', concept_id: 'jugos' }
    expect(noteRecommendationClick(track, juice, fields)).toBe(true)
    expect(noteRecommendationClick(track, juice, fields)).toBe(false) // la hoja y después su tienda: uno
    expect(track).toHaveBeenCalledExactlyOnceWith('recommendation_click', {
      ...fields,
      surface: 'agent',
      origin: 'para-ti',
      position: 0,
      request_id: 'r2',
    })
    const [offer] = placeList([{ id: 'o' }], { surface: 'home', origin: 'agent-recompra' })
    expect(noteRecommendationClick(track, offer, { ...fields, entity_id: '91004' })).toBe(true)
    const [result] = placeList([{ id: 'r' }], { surface: 'search', origin: 'resultados' })
    expect(noteRecommendationClick(track, result, fields)).toBe(false) // un resultado de búsqueda no es recomendación
    expect(noteRecommendationClick(track, { id: 'x' }, fields)).toBe(false)
  })

  test('ver un producto en la hoja y después en su tienda ("Ver tienda") es una sola vista', () => {
    const track = vi.fn()
    const fields = { entity_type: 'catalog_item', entity_id: '91001' }
    const [card] = placeList([{ id: 'p' }], { surface: 'deals', origin: 'bajaron-supermercado' })
    expect(noteItemView(track, card, fields, { fromSheet: true })).toBe(true)
    expect(noteItemView(track, card, fields)).toBe(false) // la tienda, con el mismo producto y lugar
    expect(noteItemView(track, card, fields)).toBe(true) // volver a la tienda después sí cuenta
    expect(track.mock.calls.map(([type]) => type)).toEqual(['view_item', 'view_item'])
    // Otro lugar u otro producto no se confunden; sin entidad no hay vista.
    noteItemView(track, card, fields, { fromSheet: true })
    expect(noteItemView(track, { ...card, placement: { ...card.placement, position: 3 } }, fields)).toBe(true)
    expect(noteItemView(track, { id: 'sin-entidad' }, {})).toBe(false)
  })
})
