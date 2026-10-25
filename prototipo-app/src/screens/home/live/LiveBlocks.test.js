import { describe, expect, test, vi } from 'vitest'
import { openItem } from './LiveBlocks'

describe('openItem', () => {
  test('un producto de la API abre su tienda por id, con la vertical del prototipo', () => {
    const push = vi.fn()
    const product = { id: 'cat-1', name: 'Cerveza', store: 'Botillería de prueba', storeId: 9401, vertical: 'liquor' }
    openItem(product, push)
    expect(push).toHaveBeenCalledWith('store', {
      store: { id: 9401, name: 'Botillería de prueba', vertical: 'liquor' },
      item: product,
    })
  })

  test('un plato de la API abre el menú de su restaurante', () => {
    const push = vi.fn()
    const product = { id: 'menu-5', name: 'Pizza', store: 'Pizzería de prueba', storeId: 9801, vertical: 'restaurants' }
    openItem(product, push)
    expect(push.mock.calls[0][1].store).toEqual({ id: 9801, name: 'Pizzería de prueba', vertical: 'restaurants' })
  })

  test('un producto sin storeId abre su tienda con el nombre y el logo que trae (nada del catálogo local)', () => {
    const push = vi.fn()
    const product = { id: 'x', name: 'Papas', store: 'Tienda de prueba', img: 'x.webp' }
    openItem(product, push)
    const [, { store }] = push.mock.calls[0]
    expect(store).toEqual({ name: 'Tienda de prueba', img: 'x.webp', logo: true })
    expect(Number.isInteger(store.id)).toBe(false) // nada de la API: no se abre por id
  })
})
