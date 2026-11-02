// @vitest-environment node
import { readFileSync } from 'node:fs'
import { describe, expect, test } from 'vitest'
import { alcoholInName, babyInName, GUARDS } from './guards'

// La copia a mano de GUARDS tiene que ser la de offers/guards.py: se lee el archivo del backend, sin Python.
const GUARDS_PY = readFileSync(new URL('../../../../rappi-ia/src/rappi_ia/offers/guards.py', import.meta.url), 'utf8')

/** Las palabras entre comillas de `NAME = frozenset(…)` en guards.py. */
function frozenset(name) {
  // En una línea (`frozenset({"bebe", "guagua"})`) o en varias, hasta el `)` que cierra al comienzo de una línea.
  const block =
    GUARDS_PY.match(new RegExp(`^${name} = frozenset\\((.+)\\)$`, 'm')) ??
    GUARDS_PY.match(new RegExp(`^${name} = frozenset\\(\n([\\s\\S]*?)^\\)`, 'm'))
  if (!block) throw new Error(`No encontré ${name} en guards.py`)
  return [...block[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]).sort()
}

/** _MENU_FOOD_SENSES de guards.py: palabra → [frases, conceptos]. */
function foodSenses() {
  const block = GUARDS_PY.match(/^_MENU_FOOD_SENSES[^=]*= \{([\s\S]*?)^\}/m)[1]
  const strings = (text) => [...text.matchAll(/"([^"]+)"/g)].map((m) => m[1])
  return Object.fromEntries(
    [...block.matchAll(/"([^"]+)":\s*\(\s*\(([^)]*)\),\s*\(([^)]*)\),?\s*\)/g)].map(([, word, phrases, concepts]) => [
      word,
      [strings(phrases), strings(concepts)],
    ]),
  )
}

describe('la copia de offers/guards.py', () => {
  test('tiene las mismas palabras que guards.py', () => {
    expect([...GUARDS.catalog_alcohol].sort()).toEqual(frozenset('ALCOHOL_NAME_WORDS'))
    expect([...GUARDS.menu_alcohol].sort()).toEqual(frozenset('MENU_ALCOHOL_NAME_WORDS'))
    expect([...GUARDS.baby].sort()).toEqual(frozenset('BABY_NAME_WORDS'))
    expect(GUARDS.menu_food_senses).toEqual(foodSenses())
    expect(Object.keys(foodSenses())).toHaveLength(10)
  })
})

describe('alcohol y bebé en un nombre (alcohol_in_name, baby_in_name)', () => {
  test('el catálogo usa su lista: "sake" es alcohol; los tragos de un menú, no', () => {
    expect(alcoholInName(null, 'catalog_item', 'Sake Gekkeikan 750 ml')).toBe(true)
    expect(alcoholInName(null, 'catalog_item', 'Cervezas artesanales')).toBe(true) // con su plural
    expect(alcoholInName(null, 'catalog_item', 'Galletas Ronda ginger')).toBe(false) // palabra entera
    expect(alcoholInName(null, 'catalog_item', 'Mix para michelada')).toBe(false)
    expect(alcoholInName(null, 'catalog_item', 'Absolute New York delineador')).toBe(false)
  })

  test('un menú usa la suya: "sake" es salmón, y los tragos, cepas y marcas de cerveza son alcohol', () => {
    expect(alcoholInName(null, 'menu_item', 'Sake Roll', 'sushi')).toBe(false)
    for (const name of ['Chelada', 'Whiskey sour', 'Borgoña', 'Champaña', 'Piña colada', 'Cabernet Sauvignon'])
      expect(alcoholInName(null, 'menu_item', name, 'gaseosas')).toBe(true)
    expect(alcoholInName(null, 'menu_item', 'Churrasco Kunstmann', 'sandwiches')).toBe(true)
  })

  test('una palabra de trago que también es comida se libra por la frase o por el concepto', () => {
    expect(alcoholInName(null, 'menu_item', 'Pizza Margarita', 'galletas')).toBe(false) // por la frase
    expect(alcoholInName(null, 'menu_item', 'Margarita Familiar', 'pizza')).toBe(false) // por el concepto
    expect(alcoholInName(null, 'menu_item', 'Margarita de frutilla', 'jugos')).toBe(true)
    expect(alcoholInName(null, 'menu_item', 'Papas Sour Cream', 'papas-fritas')).toBe(false)
    expect(alcoholInName(null, 'menu_item', 'Pisco sour', 'papas-fritas')).toBe(true) // pisco
    expect(alcoholInName(null, 'menu_item', 'Piña colada sin alcohol', 'gaseosas')).toBe(false)
    expect(alcoholInName(null, 'menu_item', 'Combo Eros Ramazzotti', 'sandwiches')).toBe(false)
  })

  test('bebé solo en el catálogo', () => {
    expect(babyInName(null, 'catalog_item', 'Juguete para Bebés')).toBe(true)
    expect(babyInName(null, 'menu_item', 'Menú guagua')).toBe(false)
  })

  test('con las palabras que grabó la muestra (`meta.guards`), usa esas', () => {
    const recorded = { ...GUARDS, catalog_alcohol: ['hidromiel'] }
    expect(alcoholInName(recorded, 'catalog_item', 'Hidromiel artesanal')).toBe(true)
    expect(alcoholInName(recorded, 'catalog_item', 'Cerveza lata')).toBe(false)
  })
})
