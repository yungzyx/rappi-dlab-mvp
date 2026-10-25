import { describe, expect, test } from 'vitest'
import { ask, detectConcepts, matchProducts, namesQuery, search } from './search'
import { META, product } from '../../test/offlineMeta'

const coffee = product(1, { name: 'Café molido 250 g' })
const coffeeCookies = product(2, { name: 'Galletas sabor café', concept: 'galletas' })
const expressCookies = product(3, { name: 'Galletas de café', concept: 'galletas', vertical: 'conveniencia' })
const honey = product(4, {
  name: 'Panal de miel',
  concept: null,
  entity_type: 'menu_item',
  vertical: 'restaurantes',
})
const beer = product(5, { name: 'Cerveza lata', concept: 'cerveza', vertical: 'licores', age_restricted: true })
const pharmacyCookies = product(6, { name: 'Galletas sin azúcar', concept: 'galletas', vertical: 'farmacia' })
const teddy = product(7, { name: 'Peluche oso', concept: 'juguetes', vertical: 'mall' })
const pool = [coffee, coffeeCookies, expressCookies, honey, beer, pharmacyCookies, teddy]
const HELP = { text: 'Puedo buscarte lo que quieras: prueba con «sushi» o «algo para la once».', products: [] }
const snapshot = {
  meta: META,
  pool,
  byEntity: new Map(pool.map((p) => [`${p.entity_type}:${p.entity_id}`, p])),
  search: {},
  ask: {},
  complements: {},
  help: HELP,
}

describe('los conceptos de una consulta (concepts/matcher.py)', () => {
  test('por sus keywords, en singular o plural, sin las que lo impiden', () => {
    expect(detectConcepts(META, 'Quiero un café')).toEqual(['cafe'])
    expect(detectConcepts(META, 'una galleta')).toEqual(['galletas'])
    expect(detectConcepts(META, 'taza para café')).toEqual([])
  })

  test('una palabra que solo sirve para pedir algo cuenta si es todo el pedido', () => {
    expect(detectConcepts(META, 'hola, chela')).toEqual(['cerveza'])
    expect(detectConcepts(META, 'chela helada')).toEqual([])
  })

  test('el nombre dice lo pedido con palabras enteras y la ñ: «pañales» no es «panal»', () => {
    expect(namesQuery(META, 'Galletas de café', 'galleta')).toBe(true)
    expect(namesQuery(META, 'Panal de miel', 'pañales')).toBe(false)
  })
})

describe('el foco de la búsqueda (agent/tools.py: _focus)', () => {
  test('donde la vertical tiene el concepto, solo el concepto; donde no, lo que lo dice en el nombre', () => {
    const found = matchProducts(snapshot, 'café')
    expect(found).toContain(coffee)
    expect(found).not.toContain(coffeeCookies) // el súper vende café: unas galletas «sabor café» no son café
    expect(found).toContain(expressCookies) // Express no tiene café: muestra lo que dice «café»
  })

  test('«pañales» no trae el postre con «panal»', () => {
    expect(matchProducts(snapshot, 'pañales')).not.toContain(honey)
    expect(search(snapshot, new URLSearchParams('q=pañales')).groups).toEqual([])
  })
})

describe('«qué me recomiendas» (rappi_agent.py: _recommend)', () => {
  const recommend = (interests, body = {}) =>
    ask(snapshot, { message: '¿Qué me recomiendas?', mode: 'propuesta', ...body }, { interests, userId: 'proto-1' })

  test('busca su interés en la vertical más típica y lo dice', () => {
    const reply = recommend(['cafe'])
    expect(reply.text).toBe('Por tu interés en ☕ café 😉 Mira lo que encontré de «café» en el súper.')
    expect(reply.products).toEqual([coffee])
    expect(reply.vertical).toBe('supermercado')
  })

  test('desde Farmacia no busca ahí: va a una vertical que Mochi propone', () => {
    const reply = recommend(['galletas'], { vertical: 'pharmacy' })
    expect(reply.vertical).not.toBe('farmacia')
    expect(reply.products).not.toContain(pharmacyCookies)
  })

  test('si nombra algo, busca eso: «¿me recomiendas un café?» no es «qué me recomiendas»', () => {
    const reply = recommend(['juguetes'], { message: '¿Me recomiendas un café?' })
    expect(reply.text).toBe(
      'Esta demo sin conexión no entiende preguntas nuevas, solo busca palabras: esto encontré en el súper.',
    )
    expect(reply.products).toEqual([coffee])
  })

  test('prueba hasta tres intereses', () => {
    // Tres intereses que se pueden ofrecer pero no tienen productos en la muestra: el cuarto ya no se prueba.
    const empty = Object.fromEntries(['a', 'b', 'c'].map((id) => [id, { name: id, emoji: '·', offerable: true }]))
    const wider = { ...snapshot, meta: { ...META, concepts: { ...META.concepts, ...empty } } }
    const reply = (interests) =>
      ask(wider, { message: 'qué me recomiendas', mode: 'propuesta' }, { interests, userId: 'proto-1' })
    expect(reply(['a', 'b', 'cafe']).products).toEqual([coffee])
    expect(reply(['a', 'b', 'c', 'cafe'])).toBe(HELP)
  })

  test('sin productos que Mochi pueda ofrecer de un interés prueba el siguiente; sin nada, los ejemplos', () => {
    expect(recommend(['cerveza', 'juguetes']).text).toBe(
      'Por tu interés en 🧸 juguetes 😉 Mira lo que encontré de «juguetes» en Rappi Mall.',
    )
    expect(recommend(['cerveza'])).toBe(HELP)
    expect(recommend([])).toBe(HELP)
    expect(recommend(['cafe'], { mode: 'actual' })).toBe(HELP)
  })
})

describe('preguntas que la muestra no grabó (agent/understand.py y rappi_agent.py, en corto)', () => {
  const said = (message) => ask(snapshot, { message, mode: 'propuesta' }, { interests: [], userId: 'proto-1' })

  test('lo grabado de la API real va primero', () => {
    const recorded = { text: 'Para 6 personas…', products: [coffee] }
    const withRecord = { ...snapshot, ask: { 'que llevo para un asado de 6': recorded } }
    expect(ask(withRecord, { message: '¿Qué llevo para un asado de 6?' })).toBe(recorded)
  })

  test('consejo médico: no lo da, como la API, y deja ir a Farmacia', () => {
    const reply = said('mi hijo tiene fiebre, ¿qué le doy?')
    expect(reply.text).toMatch(/^No puedo decirte qué remedio tomar o dar/)
    expect(reply.text).toContain('pediatra')
    expect(reply.products).toEqual([])
    expect(reply.actions).toEqual([{ label: 'Ir a Farmacia', vertical: 'farmacia' }])
    expect(reply.intent).toMatchObject({ kind: 'consejo', symptom: true })
    expect(said('algo para la fiebre de mi hijo').intent.kind).toBe('consejo') // un niño: tampoco se elige remedio
  })

  test('un síntoma: sin conexión no busca remedios y lo dice, sin anotarlo como demanda', () => {
    const reply = said('tengo tos')
    expect(reply.text).toBe(
      'Esta demo sin conexión no busca remedios. Pregúntale al químico farmacéutico qué te sirve para eso.',
    )
    expect(reply.products).toEqual([])
    expect(reply.unmet).toBe(false)
  })

  test('una pregunta nueva sin nada que calce lo dice con honestidad', () => {
    const reply = said('¿qué es una kombucha?')
    expect(reply.text).toBe(
      'Esta demo sin conexión no entiende preguntas nuevas. Prueba con una de las ideas o escribe un producto.',
    )
    expect(reply.products).toEqual([])
  })

  test('un producto suelto se sigue buscando como siempre', () => {
    expect(said('café').text).toBe('Mira lo que encontré de «café» en el súper.')
  })
})
