import { describe, expect, test } from 'vitest'
import { followKey, readRefinement } from './conversation'
import { ask } from './search'
import { META, product } from '../../test/offlineMeta'

const pizza = (id, name, price) =>
  product(id, { name, concept: 'pizza', vertical: 'restaurantes', price_value: price, entity_type: 'menu_item' })
const pool = [
  pizza(1, 'Pizza pepperoni familiar', 12990),
  pizza(2, 'Pizza vegetariana familiar', 11990),
  pizza(3, 'Pizza Carnivori familiar', 14990),
  pizza(4, 'Pizza veggie mediana', 8990),
  product(5, { name: 'Pizza congelada margarita', concept: 'pizza', price_value: 3990 }),
  product(6, { name: 'Hielo 2 kg', concept: 'hielo', vertical: 'conveniencia', price_value: 1490 }),
  product(7, { name: 'Bebida cola 1,5 L', concept: 'gaseosas', vertical: 'conveniencia', price_value: 1590 }),
]
const meta = {
  ...META,
  concepts: {
    ...META.concepts,
    pizza: { name: 'Pizza', emoji: '🍕', group: 'comida', offerable: true, keywords: ['pizza'] },
    gaseosas: { name: 'Bebidas gaseosas', emoji: '🥤', group: 'bebidas', offerable: true, keywords: ['bebida'] },
  },
  occasions: {
    carrete: { name: 'Carrete', emoji: '🎉', concepts: ['cerveza', 'gaseosas', 'hielo'], portion: null },
  },
}
const snapshot = { meta, pool, byEntity: new Map(), search: {}, ask: {}, complements: {}, help: null }

const PIZZA = {
  query: 'pizza',
  concepts: ['pizza'],
  occasion: null,
  vertical: 'restaurantes',
  price_max: null,
  people: null,
  order: null,
  symptom: false,
  product_ids: ['1', '2'],
}
const then = (message, previous = PIZZA, recorded = {}) =>
  ask({ ...snapshot, followUps: recorded }, { message, previous, mode: 'propuesta' })
const names = (reply) => reply.products.map((p) => p.name)

describe('qué dice un seguimiento (agent/understand.py: _follow_up, en corto)', () => {
  test('el orden, el tope, las personas, lo que no va, la vertical y "otra opción"', () => {
    expect(readRefinement('¿y algo más barato?')).toEqual({ order: 'barato' })
    expect(readRefinement('uno más caro')).toEqual({ order: 'caro' })
    expect(readRefinement('menos de 10 lucas')).toEqual({ priceMax: 10000 })
    expect(readRefinement('para 10 personas')).toEqual({ people: 10 })
    expect(readRefinement('somos ocho')).toEqual({ people: 8 })
    expect(readRefinement('sin carne')).toEqual({ without: ['carne'] })
    expect(readRefinement('en el súper mejor')).toEqual({ vertical: 'supermercado' })
    expect(readRefinement('otra opción')).toEqual({ other: true })
  })

  test('lo que nombra otra cosa es un tema nuevo', () => {
    for (const message of ['pañales talla G', '¿y para tomar?', 'tengo dolor de cabeza', 'hola'])
      expect(readRefinement(message), message).toBeNull()
  })
})

describe('el seguimiento sobre la muestra (agent/rappi_agent.py, en corto)', () => {
  test('"sin carne": solo lo que el nombre dice que no tiene (vegetariana, veggie), no la "Carnivori"', () => {
    const reply = then('sin carne')
    expect(names(reply).sort()).toEqual(['Pizza vegetariana familiar', 'Pizza veggie mediana'])
    expect(reply.text).toBe('Mira estas opciones de 🍕 pizza sin carne en restaurantes.')
    expect(reply.conversation).toMatchObject({
      query: 'pizza sin carne',
      concepts: ['pizza'],
      vertical: 'restaurantes',
    })
    expect(reply.intent.follow_up).toBe(true)
  })

  test('"más barato" ordena y queda para los turnos siguientes; "otra opción" salta lo ya mostrado', () => {
    const cheaper = then('más barato')
    expect(names(cheaper)[0]).toBe('Pizza veggie mediana')
    expect(cheaper.text).toMatch(/^Lo más barato de 🍕 pizza en restaurantes/)
    const other = then('otra opción', cheaper.conversation)
    expect(other.products).toEqual([])
    expect(other.text).toBe('En la muestra de esta demo no encontré otras opciones de 🍕 pizza en restaurantes.')
    const someOther = then('otra opción')
    expect(someOther.products.map((p) => p.entity_id).sort()).toEqual(['3', '4'])
    expect(someOther.conversation.product_ids).toEqual(['1', '2', ...someOther.products.map((p) => p.entity_id)])
  })

  test('el tope, la cantidad de personas y la vertical', () => {
    expect(names(then('menos de 10 lucas'))).toEqual(['Pizza veggie mediana'])
    expect(then('para 4 personas').text).toContain('Para 4 personas: revisa para cuántos alcanza cada producto.')
    const grocery = then('en el súper mejor')
    expect(grocery.vertical).toBe('supermercado')
    expect(names(grocery)).toEqual(['Pizza congelada margarita'])
  })

  test('una ocasión sigue siendo la ocasión, sin lo que Mochi no propone (alcohol)', () => {
    const party = {
      ...PIZZA,
      query: 'algo para el carrete',
      concepts: [],
      occasion: 'carrete',
      vertical: 'conveniencia',
    }
    const reply = then('más barato', party)
    expect(names(reply)).toEqual(['Hielo 2 kg', 'Bebida cola 1,5 L'])
    expect(reply.text).toMatch(/^Lo más barato de carrete 🎉 en Express/)
  })

  test('los remedios no los busca: lo dice', () => {
    const cold = { ...PIZZA, query: 'algo para el resfrio', concepts: [], vertical: 'farmacia', symptom: true }
    const reply = then('más barato', cold)
    expect(reply.products).toEqual([])
    expect(reply.text).toMatch(/^Esta demo sin conexión no busca remedios/)
    expect(reply.intent.symptom).toBe(true)
  })

  test('el seguimiento grabado de la API real va primero', () => {
    const recorded = { text: 'Grabado', products: [], conversation: null }
    expect(then('sin carne', PIZZA, { [followKey(PIZZA, 'sin carne')]: recorded })).toBe(recorded)
  })

  test('"¿y…?" con algo nuevo es otro pedido para la misma gente', () => {
    const recorded = { text: 'Mira estas bebidas.', products: [pool[6]], vertical: 'conveniencia', intent: {} }
    const asado = { ...PIZZA, people: 6 }
    const reply = ask(
      { ...snapshot, ask: { 'y para tomar': recorded } },
      { message: '¿y para tomar?', previous: asado },
    )
    expect(reply.text).toBe('Mira estas bebidas. Para 6 personas: revisa para cuántos alcanza cada producto.')
    expect(reply.conversation).toMatchObject({ people: 6, product_ids: ['7'] })
  })
})
