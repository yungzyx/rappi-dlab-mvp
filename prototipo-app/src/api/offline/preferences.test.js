import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeEach, describe, expect, test } from 'vitest'
import { route } from './index'
import { CUISINES, FOOD_GROUPS, RULES, applied, readCommand } from './preferences'
import { readState } from './state'
import { normalize } from './text'
import { META, product } from '../../test/offlineMeta'

// Las opciones de verdad (rappi-ia): la copia de aquí tiene que decir lo mismo.
// Los tests corren desde prototipo-app/ (en jsdom, import.meta.url no es un archivo).
const TOML = readFileSync(join(process.cwd(), '../rappi-ia/src/rappi_ia/offers/preferencias.toml'), 'utf8')
const list = (text, key) =>
  [...(text.match(new RegExp(`^${key} = \\[([^\\]]*)\\]`, 'm'))?.[1].matchAll(/"([^"]+)"/g) ?? [])].map((m) => m[1])
const tomlRules = TOML.split('[[preferencia]]')
  .slice(1)
  .map((block) => ({
    id: block.match(/^id = "([^"]+)"/m)[1],
    tipo: block.match(/^tipo = "([^"]+)"/m)[1],
    frases: list(block, 'frases'),
    conceptos: list(block, 'conceptos'),
    palabras: list(block, 'palabras').map(normalize),
  }))

describe('la copia de offers/preferencias.toml', () => {
  test('las mismas opciones, frases, conceptos y palabras', () => {
    expect(RULES.map((r) => r.id)).toEqual(tomlRules.map((r) => r.id))
    for (const rule of tomlRules) {
      const copy = RULES.find((r) => r.id === rule.id)
      expect(copy.tipo).toBe(rule.tipo)
      expect(copy.frases).toEqual(rule.frases)
      expect(copy.conceptos).toEqual(rule.conceptos)
      expect(copy.palabras).toEqual(rule.palabras)
    }
    expect(FOOD_GROUPS).toEqual(list(TOML.split('[[preferencia]]')[0], 'grupos_comida'))
  })

  test('las mismas cocinas', () => {
    const cuisines = TOML.match(/^cocinas = \[([^\]]*)\]/m)[1]
    expect(CUISINES).toEqual([...cuisines.matchAll(/"([^"]+)"/g)].map((m) => m[1]))
  })
})

describe('lo que se dice por chat (offers/preferences.py: read_command)', () => {
  test.each([
    ['Soy vegetariana y alérgica al maní', 'agregar', ['vegetariano', 'mani']],
    ['ya no soy vegano', 'quitar', ['vegano']],
    ['ya no como carne', 'agregar', ['vegetariano']],
    ['muéstrame mis preferencias', 'mostrar', []],
    ['olvida mis preferencias', 'olvidar', []],
  ])('«%s»', (message, action, ids) => {
    const command = readCommand(message)
    expect(command.action).toBe(action)
    expect(command.items.map((p) => p.valor)).toEqual(ids)
  })

  test('un pedido con «sin» no es una alergia; una tienda y una cocina se leen aparte', () => {
    expect(readCommand('sushi sin maní')).toBeNull()
    expect(readCommand('mi tienda favorita es el Jumbo').store).toBe('jumbo')
    expect(readCommand('mi comida favorita es el sushi').cuisineText).toBe('el sushi')
  })
})

describe('qué sacan y qué ordenan', () => {
  const meta = { ...META, concepts: { ...META.concepts, pizza: { name: 'Pizza', emoji: '🍕', group: 'comida' } } }
  const pepperoni = product(1, { name: 'Pizza pepperoni', concept: 'pizza', entity_type: 'menu_item' })
  const margarita = product(2, { name: 'Pizza margarita', concept: 'pizza', entity_type: 'menu_item' })
  const peluche = product(3, { name: 'Peluche pollo', concept: 'juguetes', store: 'Jumbo Centro' })

  test('la dieta saca solo comida y lo dice; las favoritas ponen primero sin sacar nada', () => {
    const mine = applied(meta, [
      { tipo: 'dieta', valor: 'vegetariano' },
      { tipo: 'tienda', valor: 'Jumbo' },
    ])
    expect(mine.products([pepperoni, margarita, peluche])).toEqual([peluche, margarita])
    expect(mine.notice([margarita])).toBe(
      'Por tus preferencias, saqué lo que dice tener carne; revisa los ingredientes en la tienda.',
    )
    expect(mine.notice([peluche])).toBeNull()
  })
})

describe('la API simulada', () => {
  const pizzas = [
    product(1, { name: 'Pizza pepperoni', concept: 'cafe', vertical: 'supermercado' }),
    product(2, { name: 'Café molido', concept: 'cafe', vertical: 'supermercado' }),
  ]
  const snapshot = {
    meta: META,
    pool: pizzas,
    byEntity: new Map(pizzas.map((p) => [`${p.entity_type}:${p.entity_id}`, p])),
    search: {},
    ask: {},
    followUps: {},
    complements: {},
    help: null,
    catalog: { home: {}, restaurants: { rating: [] }, deals: {}, verticalStores: {}, stores: {}, menus: {} },
    recommendations: { rows: [] },
  }
  const call = (method, path, body) => route(snapshot, { method, path, query: new URLSearchParams(), body })
  const say = (message, mode = 'propuesta') => call('POST', '/agent/ask', { message, mode }).body

  beforeEach(() => localStorage.clear())

  test('por chat se guardan, filtran lo que muestra Mochi y se olvidan; en «Rappi hoy» no', () => {
    expect(say('soy vegetariano', 'actual').text).toMatch(/Rappi hoy/)
    expect(readState().preferences).toEqual([])

    const saved = say('soy vegetariano')
    expect(saved.intent.kind).toBe('preferencia')
    expect(saved.preferences).toEqual([{ tipo: 'dieta', valor: 'vegetariano', nombre: 'Vegetariano' }])
    expect(saved.actions).toEqual([{ label: 'Ver mis preferencias', panel: 'preferencias' }])

    const shown = say('café')
    expect(shown.products.map((p) => p.name)).not.toContain('Pizza pepperoni')
    expect(shown.text).toMatch(/saqué lo que dice tener carne/)

    expect(say('mis preferencias').text).toMatch(/Vegetariano/)
    say('olvida mis preferencias')
    expect(readState().preferences).toEqual([])
  })

  test('el panel las lee y las reemplaza; una tienda que no está en la muestra no queda', () => {
    const empty = call('GET', '/profile/p/preferencias').body
    expect(empty.preferencias).toEqual([])
    expect(empty.opciones.some((o) => o.valor === 'mani')).toBe(true)
    const put = call('PUT', '/profile/p/preferencias', {
      preferencias: [
        { tipo: 'alergia', valor: 'mani' },
        { tipo: 'tienda', valor: 'No existe' },
        { tipo: 'tienda', valor: 'Tienda de prueba' },
      ],
    }).body
    expect(put.preferencias.map((p) => p.valor)).toEqual(['mani', 'Tienda de prueba'])
    call('DELETE', '/profile/p') // «Olvidar»: también las preferencias
    expect(readState().preferences).toEqual([])
  })
})
