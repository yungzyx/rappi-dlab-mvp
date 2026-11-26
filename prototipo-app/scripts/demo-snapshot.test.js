// @vitest-environment node
import { describe, expect, test } from 'vitest'
import { intern } from './demo-snapshot.mjs'
import { decodeSnapshot } from '../src/api/offline/snapshot.js'
import { toPrototypeProduct } from '../src/api/client.js'

const product = (fields) => ({
  id: 'cat-1',
  entity_type: 'catalog_item',
  entity_id: '1',
  name: 'Café (prueba)',
  vertical: 'supermercado',
  price: '$1.000',
  price_value: 1000,
  store: 'Súper de prueba',
  store_id: 9,
  ...fields,
})

describe('la muestra guarda lo que la app lee de un producto', () => {
  test('un producto agotado en su tienda sigue agotado sin conexión ("Agotado")', () => {
    const raw = intern({ list: [product({ available: false, stock: 0 }), product({ entity_id: '2' })] })
    const { list } = decodeSnapshot(JSON.parse(JSON.stringify(raw)))
    expect(list.map((p) => Boolean(toPrototypeProduct(p).soldOut))).toEqual([true, false])
  })
})
