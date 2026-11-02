import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { placeList } from './attribution'
import {
  FLUSH_MS,
  MAX_ITEMS,
  flushImpressions,
  impressionRef,
  productItem,
  resetImpressions,
  setImpressionSink,
  storeItem,
  verticalItem,
} from './impressions'

// Un IntersectionObserver de mentira: `show(node, ratio)` hace visible el nodo.
let observers = []
class FakeObserver {
  constructor(callback, options) {
    this.callback = callback
    this.options = options
    this.nodes = new Set()
    observers.push(this)
  }
  observe(node) {
    this.nodes.add(node)
  }
  unobserve(node) {
    this.nodes.delete(node)
  }
  disconnect() {
    this.nodes.clear()
  }
}
const show = (node, ratio = 1) => {
  for (const observer of observers)
    if (observer.nodes.has(node))
      observer.callback([{ target: node, isIntersecting: ratio > 0, intersectionRatio: ratio }])
}

const products = (n, start = 0) =>
  Array.from({ length: n }, (_, i) => ({
    id: `p${start + i}`,
    entityType: 'catalog_item',
    entityId: String(1000 + start + i),
    concept: 'cerveza',
    vertical: 'liquor',
  }))

/** Monta cada elemento en un nodo con su ref, como hace React. */
const mount = (items, fields = productItem) =>
  items.map((item) => {
    const node = document.createElement('div')
    impressionRef(item, fields(item))?.(node)
    return node
  })

describe('impresiones de listas', () => {
  let track
  beforeEach(() => {
    vi.useFakeTimers()
    observers = []
    vi.stubGlobal('IntersectionObserver', FakeObserver)
    track = vi.fn()
    setImpressionSink(track)
  })
  afterEach(() => {
    resetImpressions()
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('junta lo visto de una lista en un list_view con su lugar y la mayor posición vista', () => {
    const list = placeList(products(5), { surface: 'search', origin: 'resultados', requestId: 'req-1' })
    const nodes = mount(list)
    show(nodes[0])
    show(nodes[2])
    expect(track).not.toHaveBeenCalled() // espera el lote
    vi.advanceTimersByTime(FLUSH_MS)
    expect(track).toHaveBeenCalledTimes(1)
    expect(track).toHaveBeenCalledWith('list_view', {
      surface: 'search',
      origin: 'resultados',
      position: 2,
      request_id: 'req-1',
      items: [
        { position: 0, entity_type: 'catalog_item', entity_id: '1000', concept_id: 'cerveza', vertical: 'liquor' },
        { position: 2, entity_type: 'catalog_item', entity_id: '1002', concept_id: 'cerveza', vertical: 'liquor' },
      ],
    })
    // Lo que se ve después en la misma lista sigue subiendo la mayor posición.
    show(nodes[1])
    vi.advanceTimersByTime(FLUSH_MS)
    expect(track.mock.calls[1][1]).toMatchObject({ position: 2, items: [{ position: 1 }] })
  })

  it('el mismo elemento en el mismo lugar recibe el mismo ref en cada render (no se suelta ni se vuelve a observar)', () => {
    const [item] = placeList(products(1), { surface: 'store', origin: 'pasillo' })
    const ref = impressionRef(item, productItem(item))
    expect(impressionRef({ ...item }, productItem(item))).toBe(ref) // otro render, la misma fila
    const [moved] = placeList(products(1), { surface: 'store', origin: 'pasillo', start: 3 })
    expect(impressionRef(moved, productItem(moved))).not.toBe(ref) // otro lugar, otro ref
    const node = document.createElement('div')
    ref(node)
    show(node)
    vi.advanceTimersByTime(FLUSH_MS)
    expect(track).toHaveBeenCalledTimes(1)
  })

  it('cuenta solo lo que se ve al menos a la mitad, una vez por pestaña', () => {
    const [node] = mount(placeList(products(1), { surface: 'turbo', origin: 'pasillo' }))
    show(node, 0.3)
    vi.advanceTimersByTime(FLUSH_MS)
    expect(track).not.toHaveBeenCalled()
    show(node, 0.6)
    vi.advanceTimersByTime(FLUSH_MS)
    expect(track).toHaveBeenCalledTimes(1)
    // La misma lista montada otra vez (volver a la pantalla) ya no observa ese elemento.
    const [again] = mount(placeList(products(1), { surface: 'turbo', origin: 'pasillo' }))
    show(again)
    vi.advanceTimersByTime(FLUSH_MS)
    expect(track).toHaveBeenCalledTimes(1)
  })

  it('separa las listas y parte una lista larga en eventos de hasta MAX_ITEMS', () => {
    const long = mount(placeList(products(MAX_ITEMS + 3), { surface: 'store', origin: 'pasillo' }))
    const stores = mount(
      placeList([{ id: 7, vertical: 'supermercado' }], { surface: 'home', origin: 'cerca-de-ti', requestId: 'r' }),
      storeItem,
    )
    for (const node of [...long, ...stores]) show(node)
    flushImpressions()
    const sizes = track.mock.calls.map(([, event]) => [event.origin, event.items.length])
    expect(sizes).toEqual([
      ['pasillo', MAX_ITEMS],
      ['pasillo', 3],
      ['cerca-de-ti', 1],
    ])
    expect(track.mock.calls[2][1].items[0]).toEqual({
      position: 0,
      entity_type: 'store',
      entity_id: '7',
      vertical: 'supermercado',
    })
  })

  it('dos elementos en el mismo lugar de una lista (productos y sugerencia del agente) van en eventos distintos', () => {
    const placement = { surface: 'agent', origin: 'agent-ask', requestId: 'a1' }
    const nodes = mount([...placeList(products(2), placement), ...placeList(products(1, 5), placement)])
    for (const node of nodes) show(node)
    flushImpressions()
    expect(track.mock.calls.map(([, event]) => event.items.map((item) => item.position))).toEqual([[0, 1], [0]])
  })

  it('ignora lo que no tiene lugar o id, y sin IntersectionObserver no hace nada', () => {
    expect(impressionRef(products(1)[0], productItem(products(1)[0]))).toBeUndefined() // sin placement
    const [noId] = placeList([{ id: 'x' }], { surface: 'home', origin: 'accesos' })
    expect(impressionRef(noId, verticalItem(undefined))).toBeUndefined()
    vi.stubGlobal('IntersectionObserver', undefined)
    resetImpressions()
    setImpressionSink(track)
    const nodes = mount(placeList(products(2), { surface: 'search', origin: 'resultados' }))
    expect(nodes).toHaveLength(2)
    flushImpressions()
    expect(track).not.toHaveBeenCalled()
  })

  it('al ocultar la página manda lo pendiente sin esperar', () => {
    const [node] = mount(placeList(products(1), { surface: 'agent', origin: 'agent-carrito', requestId: 'o1' }))
    show(node)
    Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true })
    document.dispatchEvent(new Event('visibilitychange'))
    expect(track).toHaveBeenCalledWith('list_view', expect.objectContaining({ origin: 'agent-carrito' }))
    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
  })
})
