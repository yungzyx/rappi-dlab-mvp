import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, test } from 'vitest'
import { CartProvider, formatPrice, lineKey, parsePrice, useCart } from './CartContext'
import { ProfileProvider, useProfile } from './ProfileContext'

const BEER = { id: 'beer', name: 'Cerveza Heineken', price: '$6.690' }
const CHIPS = { id: 'chips', name: 'Papas fritas', price: '$2.690' }

describe('precios', () => {
  test('parsePrice y formatPrice usan el formato chileno', () => {
    expect(parsePrice('$10.990')).toBe(10990)
    expect(parsePrice(undefined)).toBe(0)
    expect(formatPrice(10990)).toBe('$10.990')
  })
})

describe('CartContext', () => {
  const setup = () => renderHook(() => useCart(), { wrapper: CartProvider })
  afterEach(() => localStorage.clear())

  test('el carro sobrevive a una recarga (líneas, id y notas)', () => {
    const first = setup()
    act(() => first.result.current.add(BEER))
    act(() => first.result.current.add(BEER))
    act(() => first.result.current.setNote(BEER, 'bien fría'))
    const id = first.result.current.id
    first.unmount()

    const second = setup()
    expect(second.result.current.id).toBe(id)
    expect(second.result.current.qtyOf(BEER)).toBe(2)
    expect(second.result.current.noteOf(BEER)).toBe('bien fría')
  })

  test('si lo guardado está corrupto, parte de cero', () => {
    localStorage.setItem('rappi-proto-cart', '{"lines": "no"')
    expect(setup().result.current.count).toBe(0)
    localStorage.setItem('rappi-proto-cart', JSON.stringify({ id: 'c-1', lines: { x: { qty: -1 } } }))
    expect(setup().result.current.count).toBe(0)
  })

  test('suma cantidades y total', () => {
    const { result } = setup()
    act(() => result.current.add(BEER))
    act(() => result.current.add(BEER))
    act(() => result.current.add(CHIPS))
    expect(result.current.qtyOf(BEER)).toBe(2)
    expect(result.current.count).toBe(3)
    expect(result.current.total).toBe(6690 * 2 + 2690)
  })

  test('quitar la última unidad saca el producto; vaciar deja el carrito en cero', () => {
    const { result } = setup()
    act(() => result.current.add(BEER))
    act(() => result.current.remove(BEER))
    expect(result.current.items).toEqual([])
    act(() => result.current.add(CHIPS))
    act(() => result.current.clear())
    expect(result.current.count).toBe(0)
  })

  // Productos de la API: el mismo "cat-<id>" del catálogo se vende en varias tiendas y verticales.
  const OFFER_A = { id: 'cat-200', name: 'Cerveza Escudo', price: '$1.290', vertical: 'licores', store: 'Botillería' }
  const OFFER_B = { ...OFFER_A, price: '$1.390', vertical: 'supermercado', store: 'Unimarc' }

  test('cada oferta es su propia línea (mismo producto en otra tienda o vertical)', () => {
    const { result } = setup()
    act(() => result.current.add(OFFER_A))
    act(() => result.current.add(OFFER_B))
    act(() => result.current.add(OFFER_A))
    expect(result.current.items).toHaveLength(2)
    expect(result.current.qtyOf(OFFER_A)).toBe(2)
    expect(result.current.qtyOf(OFFER_B)).toBe(1)
    expect(result.current.total).toBe(1290 * 2 + 1390)
    act(() => result.current.remove(OFFER_B))
    expect(result.current.items.map((line) => line.product.store)).toEqual(['Botillería'])
  })

  // La vertical depende de la pantalla: Lider Big se lista en Súper (`grocery`) pero su página dice conveniencia (`express`).
  const BIG_FROM_DEAL = {
    id: 'cat-300',
    name: 'Leche entera 1 L',
    price: '$1.090',
    vertical: 'grocery',
    store: 'Lider Big',
    storeId: 4401,
  }
  const BIG_FROM_STORE = { ...BIG_FROM_DEAL, vertical: 'express' }

  test('el mismo producto de la misma tienda es una sola línea aunque llegue con otra vertical', () => {
    const { result } = setup()
    act(() => result.current.add(BIG_FROM_DEAL))
    act(() => result.current.add(BIG_FROM_STORE))
    expect(result.current.items).toHaveLength(1)
    expect(result.current.qtyOf(BIG_FROM_DEAL)).toBe(2)
    expect(result.current.qtyOf(BIG_FROM_STORE)).toBe(2)
    expect(lineKey(BIG_FROM_DEAL)).toBe('cat-300|4401')
    // Otra tienda (otro storeId) sigue siendo otra oferta, aunque se llame igual.
    act(() => result.current.add({ ...BIG_FROM_DEAL, storeId: 4402 }))
    expect(result.current.items).toHaveLength(2)
    act(() => result.current.remove(BIG_FROM_STORE))
    expect(result.current.qtyOf(BIG_FROM_DEAL)).toBe(1)
  })

  test('sin storeId la oferta sigue siendo producto + vertical + tienda', () => {
    expect(lineKey(OFFER_A)).toBe('cat-200|licores|Botillería')
    expect(lineKey({ id: 'x', price: '$1' })).toBe('x||')
  })

  test('un carrito guardado con las claves de antes sigue cargando y sus líneas repetidas se suman', () => {
    const old = (product, qty, extra = {}) => ({ product, qty, fromSuggestion: false, ...extra })
    localStorage.setItem(
      'rappi-proto-cart',
      JSON.stringify({
        id: 'c-viejo',
        lines: {
          'cat-300|grocery|Lider Big': old(BIG_FROM_DEAL, 1, { note: 'bien fría' }),
          'cat-300|express|Lider Big': old(BIG_FROM_STORE, 2, { fromSuggestion: true }),
          'cat-200|licores|Botillería': old(OFFER_A, 1),
        },
      }),
    )
    const { result } = setup()
    expect(result.current.id).toBe('c-viejo')
    expect(result.current.items).toHaveLength(2)
    expect(result.current.count).toBe(4)
    expect(result.current.qtyOf(BIG_FROM_STORE)).toBe(3)
    expect(result.current.noteOf(BIG_FROM_DEAL)).toBe('bien fría')
    expect(result.current.total).toBe(1090 * 3 + 1290)
    // Agregar desde cualquier pantalla suma a esa línea en vez de abrir otra.
    act(() => result.current.add(BIG_FROM_DEAL))
    expect(result.current.items).toHaveLength(2)
    expect(result.current.qtyOf(BIG_FROM_DEAL)).toBe(4)
  })

  test('la línea recuerda que vino de una sugerencia aunque después se sume desde otra tarjeta', () => {
    const { result } = setup()
    act(() => result.current.add({ ...OFFER_A, fromSuggestion: true }))
    act(() => result.current.add(OFFER_A))
    act(() => result.current.add(OFFER_B))
    const lineOf = (offer) => result.current.items.find((line) => line.product.store === offer.store)
    expect(lineOf(OFFER_A).fromSuggestion).toBe(true)
    expect(lineOf(OFFER_B).fromSuggestion).toBe(false)
  })
})

describe('ProfileContext', () => {
  test('la generación empieza en 0 y sube con cada «Olvidar»', () => {
    const { result } = renderHook(() => useProfile(), { wrapper: ProfileProvider })
    expect(result.current.resets).toBe(0)
    act(() => result.current.reset())
    act(() => result.current.reset())
    expect(result.current.resets).toBe(2)
  })
})
