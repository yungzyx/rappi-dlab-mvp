import { describe, expect, test } from 'vitest'
import { thinAssortment } from './demand.js'

const row = (concepto, usuarios_por_item, items_en_catalogo) => ({ concepto, usuarios_por_item, items_en_catalogo })

describe('thinAssortment', () => {
  test('most people per item first, only where more people search than there are items', () => {
    const rows = [row('A', 1.2, 10), row('B', 9.5, 2), row('C', 30, 0), row('D', 4.2, 5), row('E', 0.4, 50)]

    expect(thinAssortment(rows).map((item) => item.concepto)).toEqual(['B', 'D', 'A'])
    expect(thinAssortment(rows, 1).map((item) => item.concepto)).toEqual(['B'])
  })
})
