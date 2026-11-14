import { describe, expect, test } from 'vitest'
import {
  HELP_ACTIONS,
  HELP_EXAMPLES,
  ask,
  detectConcepts,
  helpReply,
  matchProducts,
  namesQuery,
  search,
} from './search'
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
const HELP = { text: 'Puedo buscarte lo que quieras: prueba con "sushi" o "algo para la once".', products: [] }
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

  test('el nombre dice lo pedido con palabras enteras y la ñ: "pañales" no es "panal"', () => {
    expect(namesQuery(META, 'Galletas de café', 'galleta')).toBe(true)
    expect(namesQuery(META, 'Panal de miel', 'pañales')).toBe(false)
    expect(namesQuery(META, 'Harina con polvos de hornear', 'harina sin polvos de hornear')).toBe(false)
    expect(namesQuery(META, 'Harina sin polvos de hornear', 'harina sin polvos de hornear')).toBe(true)
  })
})

describe('el foco de la búsqueda (agent/tools.py: _focus)', () => {
  test('donde la vertical tiene el concepto, solo el concepto; donde no, lo que lo dice en el nombre', () => {
    const found = matchProducts(snapshot, 'café')
    expect(found).toContain(coffee)
    expect(found).not.toContain(coffeeCookies) // el súper vende café: unas galletas "sabor café" no son café
    expect(found).toContain(expressCookies) // Express no tiene café: muestra lo que dice "café"
  })

  test('un remedio nombrado: solo lo que lo nombra o nombra su principio activo', () => {
    const medicine = (id, name) => product(id, { name, concept: 'medicamentos', vertical: 'farmacia' })
    const aspirin = medicine(11, 'Aspirina 100mg 42 Comprimidos')
    const statin = medicine(12, 'Rumada (10/10 mg)')
    const acid = medicine(13, 'Acido Acetilsalicílico (100 Mg)')
    const medicines = [aspirin, statin, acid]
    const meta = {
      ...META,
      concepts: { ...META.concepts, medicamentos: { name: 'Medicamentos', keywords: ['aspirina', 'remedios'] } },
    }
    const pharmacy = { ...snapshot, meta, pool: medicines }
    expect(matchProducts(pharmacy, 'aspirina')).toEqual([aspirin, acid])
    expect(matchProducts(pharmacy, 'remedios')).toEqual(medicines)
  })

  test('"pañales" no trae el postre con "panal"', () => {
    expect(matchProducts(snapshot, 'pañales')).not.toContain(honey)
    expect(search(snapshot, new URLSearchParams('q=pañales')).groups).toEqual([])
  })
})

describe('"X para Y" pide X (concepts/need.py: read_need)', () => {
  const meta = {
    ...META,
    concepts: {
      ...META.concepts,
      gaseosas: { name: 'Bebidas gaseosas', group: 'bebidas', offerable: true, keywords: ['bebida', 'tonica'] },
      pisco: { name: 'Pisco', group: 'alcohol', age_restricted: true, keywords: ['pisco'] },
    },
    complements: { 'pisco|gaseosas': 0.9, 'gaseosas|pisco': 0.9 },
  }
  const liquor = (id, name, concept, extra = {}) => product(id, { name, concept, vertical: 'licores', ...extra })
  const cola = liquor(41, 'Coca-Cola Bebida 1.5 L', 'gaseosas')
  const tonic = liquor(42, 'Agua Tónica Bebida', 'gaseosas', { age_restricted: true }) // la tienda la marca +18
  const pisco = liquor(43, 'Pisco Mistral 35°', 'pisco', { age_restricted: true })
  const pack = liquor(44, 'Pisco con Bebida 1.5 L', 'pisco', { age_restricted: true })
  const store = { ...snapshot, meta, pool: [cola, tonic, pisco, pack] }

  test('se buscan las bebidas, sin el pisco ni nada +18', () => {
    expect(matchProducts(store, 'bebida para mezclar con pisco')).toEqual([cola])
  })

  test('quien pide el pisco lo recibe', () => {
    expect(matchProducts(store, 'pisco con bebida')).toEqual(expect.arrayContaining([pisco, pack]))
    expect(matchProducts(store, 'pisco con bebida')).not.toContain(cola)
  })

  test('con una muestra grabada sin las aristas, como siempre', () => {
    const old = { ...store, meta: { ...meta, complements: undefined } }
    expect(matchProducts(old, 'bebida para mezclar con pisco')).toEqual(expect.arrayContaining([pisco, pack]))
  })

  // Pedir y refinar dos veces con los chips: el para qué viaja en `conversation.context`.
  const turns = (...messages) => {
    const replies = []
    for (const message of messages)
      replies.push(ask(store, { message, previous: replies.at(-1)?.conversation, mode: 'propuesta' }))
    return replies
  }

  test('"más barato" y "otra opción" tras "bebida para mezclar con pisco": nada +18 en ningún turno', () => {
    const replies = turns('bebida para mezclar con pisco', 'más barato', 'otra opción')
    expect(replies[0].conversation.context).toEqual(['pisco'])
    for (const reply of replies) {
      expect(reply.products.filter((p) => p.age_restricted)).toEqual([])
      expect(reply.age_notice).toBe(false)
    }
    expect(replies[1].products).toEqual([cola])
    expect(replies[1].conversation.context).toEqual(['pisco'])
  })

  test('"pisco con bebida" y "más barato" sigue con el pisco y su aviso +18', () => {
    const [, cheaper] = turns('pisco con bebida', 'más barato')
    expect(cheaper.products).toEqual(expect.arrayContaining([pisco, pack]))
    expect(cheaper.age_notice).toBe(true)
  })
})

describe('Licores no encabeza lo que no es +18 (agent/verticals.py: liquor_last)', () => {
  const liquor = (id, name, concept, extra = {}) => product(id, { name, concept, vertical: 'licores', ...extra })
  const pool = [
    liquor(31, 'Galletas de agua', 'galletas'),
    liquor(32, 'Galletas de soda', 'galletas'),
    liquor(33, 'Cerveza rubia', 'cerveza', { age_restricted: true }),
    liquor(34, 'Cerveza negra', 'cerveza', { age_restricted: true }),
    product(35, { name: 'Galletas de avena', concept: 'galletas' }),
    product(36, { name: 'Cerveza de trigo', concept: 'cerveza', age_restricted: true }),
  ]
  const store = { ...snapshot, pool }
  const order = (params) => search(store, new URLSearchParams(params)).groups.map((g) => g.vertical)

  test('con más galletas en la botillería, el súper va primero y Licores al final', () => {
    expect(order('q=galletas')).toEqual(['supermercado', 'licores'])
  })

  test('la cerveza y lo que se busca desde Licores, como siempre', () => {
    expect(order('q=cerveza')).toEqual(['licores', 'supermercado'])
    expect(order('q=galletas&current=liquor')).toEqual(['licores', 'supermercado'])
  })

  test('con una muestra sin `age_restricted` (grabada antes), el grupo del concepto dice si es +18', () => {
    const { age_restricted: _flag, ...beerWithoutFlag } = META.concepts.cerveza
    const old = { ...store, meta: { ...META, concepts: { ...META.concepts, cerveza: beerWithoutFlag } } }
    const oldOrder = (q) => search(old, new URLSearchParams(`q=${q}`)).groups.map((g) => g.vertical)
    expect(oldOrder('cerveza')).toEqual(['licores', 'supermercado'])
    expect(oldOrder('chela')).toEqual(['licores', 'supermercado'])
    expect(oldOrder('galletas')).toEqual(['supermercado', 'licores'])
  })

  test('Mochi tampoco responde desde Licores lo que no es +18', () => {
    const reply = ask(store, { message: '¿tienen galletas?', mode: 'propuesta' })
    expect(reply.vertical).toBe('supermercado')
  })
})

describe('un error de tipeo grabado (demo-snapshot.mjs: eval/typos.json)', () => {
  const corrected = {
    query: 'cervesa',
    groups: [{ vertical: 'licores', prototype_vertical: 'liquor', products: [beer] }],
    unmet: false,
    unmet_reason: null,
    corrected_query: 'cerveza',
  }
  const typed = { ...snapshot, search: { cervesa: corrected } }

  test('sale tal cual lo corrigió la API, también en la vertical', () => {
    expect(search(typed, new URLSearchParams('q=cervesa'))).toBe(corrected)
    const inLiquor = search(typed, new URLSearchParams('q=cervesa&vertical=liquor'))
    expect(inLiquor.products).toEqual([beer])
    expect(inLiquor.corrected_query).toBe('cerveza')
  })

  test('desde una pantalla (`current`) sale la corrección, con la vertical de la pantalla primero', () => {
    const fruit = product(8, { name: 'Cerveza de fruta', concept: 'cerveza', vertical: 'supermercado' })
    const both = {
      ...corrected,
      groups: [...corrected.groups, { vertical: 'supermercado', prototype_vertical: 'grocery', products: [fruit] }],
    }
    const reply = search({ ...snapshot, search: { cervesa: both } }, new URLSearchParams('q=cervesa&current=grocery'))
    expect(reply.corrected_query).toBe('cerveza')
    expect(reply.groups.map((g) => g.vertical)).toEqual(['supermercado', 'licores'])
  })

  test('"Buscar tal cual" (correct=false) no repite la corrección: busca lo escrito en la muestra', () => {
    const exact = search(typed, new URLSearchParams('q=cervesa&correct=false'))
    expect(exact.corrected_query).toBeNull()
    expect(exact.unmet).toBe(true)
    expect(exact.unmet_reason).toBe('sin coincidencias en la muestra de la demo sin conexión')
  })
})

describe('"qué me recomiendas" (rappi_agent.py: _recommend)', () => {
  const recommend = (interests, body = {}) =>
    ask(snapshot, { message: '¿Qué me recomiendas?', mode: 'propuesta', ...body }, { interests, userId: 'proto-1' })

  test('busca su interés en la vertical más típica y lo dice', () => {
    const reply = recommend(['cafe'])
    expect(reply.text).toBe('Por tu interés en ☕ café 😉 Mira lo que encontré de "café" en el súper.')
    expect(reply.products).toEqual([coffee])
    expect(reply.vertical).toBe('supermercado')
  })

  test('desde Farmacia no busca ahí: va a una vertical que Mochi propone', () => {
    const reply = recommend(['galletas'], { vertical: 'pharmacy' })
    expect(reply.vertical).not.toBe('farmacia')
    expect(reply.products).not.toContain(pharmacyCookies)
  })

  test('si nombra algo, busca eso: "¿me recomiendas un café?" no es "qué me recomiendas"', () => {
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
    expect(reply(['a', 'b', 'c', 'cafe'])).toEqual({ ...HELP, text: helpReply().text, actions: HELP_ACTIONS })
  })

  test('sin productos que Mochi pueda ofrecer de un interés prueba el siguiente; sin nada, los ejemplos', () => {
    expect(recommend(['cerveza', 'juguetes']).text).toBe(
      'Por tu interés en 🧸 juguetes 😉 Mira lo que encontré de "juguetes" en Rappi Mall.',
    )
    // La ayuda grabada, con el texto y los atajos de hoy: lo que Mochi sabe hacer y, en "Rappi hoy", solo ejemplos.
    const today = helpReply('actual').text
    expect(recommend(['cerveza'])).toEqual({ ...HELP, text: helpReply().text, actions: HELP_ACTIONS })
    expect(recommend([])).toEqual({ ...HELP, text: helpReply().text, actions: HELP_ACTIONS })
    expect(recommend(['cafe'], { mode: 'actual' })).toEqual({ ...HELP, text: today, actions: HELP_EXAMPLES })
    // Mochi no tiene chat: la ayuda no pide que le escriban.
    for (const text of [helpReply().text, today]) expect(text).not.toMatch(/Pídeme|dime|escríbeme|cuéntame/i)
  })
})

describe('la ayuda, el resumen y el último pedido (rappi_agent.py: _small_talk)', () => {
  const said = (message, mode = 'propuesta') => ask(snapshot, { message, mode })

  test('"¿qué puedes hacer?" muestra lo que Mochi sabe hacer, sin ningún ejemplo de salud', () => {
    const help = said('¿qué puedes hacer?')
    expect(help.intent.kind).toBe('ayuda')
    expect(help.actions).toEqual(HELP_ACTIONS)
    expect(said('¿qué puedes hacer?', 'actual').actions).toEqual(HELP_EXAMPLES)
    for (const reply of [help, said('ayuda', 'actual')])
      expect(JSON.stringify(reply).toLowerCase()).not.toMatch(/fiebre|remedio/)
  })

  test('"quiero pagar" es el resumen antes de pagar y lleva al checkout; "¿dónde viene mi pedido?", a Mis pedidos', () => {
    const summary = said('quiero pagar')
    expect(summary.intent.kind).toBe('resumen')
    expect(summary.actions).toEqual([{ label: 'Revisar y pagar', route: ['checkout'] }])
    expect(said('hacer el pedido').intent.kind).toBe('resumen')
    const order = said('¿dónde viene mi pedido?')
    expect(order.intent.kind).toBe('pedido')
    expect(order.actions).toEqual([{ label: 'Ver mis pedidos', route: ['orders'] }])
    // Los textos fijos de hoy: "Pedir por mí" sí pide, y el seguimiento cancela (ya no "el chat de soporte").
    expect(summary.text).toMatch(/si no me diste permiso con "Pedir por mí"/)
    expect(order.text).toMatch(/lo cancelas antes de que salga/)
    expect(order.text).not.toMatch(/chat/)
  })

  test('el saludo, el "gracias", el fuera de tema y una risa tienen su respuesta, con ideas para tocar', () => {
    const hello = said('hola')
    expect(hello).toMatchObject({ intent: { kind: 'saludo' }, actions: HELP_ACTIONS })
    expect(hello.text).toMatch(/^¡Hola! Soy .+ Toca una idea/)
    expect(said('holaaaa', 'actual').actions).toEqual(HELP_EXAMPLES)
    expect(said('ok gracias')).toMatchObject({ intent: { kind: 'gracias' } })
    expect(said('ok gracias').actions ?? []).toEqual([])
    expect(said('cuéntame un chiste')).toMatchObject({ intent: { kind: 'fuera' }, actions: HELP_ACTIONS })
    const laugh = said('jajaja')
    expect(laugh).toMatchObject({ intent: { kind: 'vacio' }, actions: HELP_ACTIONS })
    expect(laugh.unmet).toBeFalsy()
  })

  test('la cuenta, el pago o hablar con alguien no son una búsqueda (understand.py: APP_QUESTIONS)', () => {
    for (const message of ['hablar con una persona', 'servicio al cliente'])
      expect(said(message).intent.kind).toBe('pedido')
    for (const message of ['pagar con tarjeta', 'olvidé mi contraseña', 'quiero ser repartidor', 'eres un bot?'])
      expect(said(message).intent.kind).toBe('fuera')
  })

  test('gana la frase con más palabras, y una ocasión se busca', () => {
    expect(said('ayuda con mi pedido').intent.kind).toBe('pedido')
    expect(said('ayuda para el asado').intent.kind).not.toBe('ayuda')
  })
})

describe('preguntas que la muestra no grabó (agent/understand.py y rappi_agent.py, en corto)', () => {
  const said = (message) => ask(snapshot, { message, mode: 'propuesta' }, { interests: [], userId: 'proto-1' })

  test('lo grabado de la API real va primero', () => {
    const recorded = { text: 'Para 6 personas…', products: [coffee] }
    const withRecord = { ...snapshot, ask: { 'que llevo para un asado de 6': recorded } }
    // Con el estado para seguir la conversación (una muestra grabada con una API anterior no lo trae)
    expect(ask(withRecord, { message: '¿Qué llevo para un asado de 6?' })).toMatchObject({
      ...recorded,
      conversation: { vertical: null, product_ids: ['1'] },
    })
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
    expect(said('café').text).toBe('Mira lo que encontré de "café" en el súper.')
  })
})
