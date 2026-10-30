// Seguir la conversación con Mochi sin conexión: copia corta de agent/understand.py (_follow_up) y de
// agent/rappi_agent.py (_conversation y lo que va "sin", el orden por precio y "otra opción"). Primero, el seguimiento
// grabado de la API real (los de eval/frases_usuarios/conversaciones.txt, `npm run demo:snapshot`); si no hay, se arma
// sobre los productos de la muestra. Lo que no puede (remedios, o nada en la muestra que cumpla lo pedido) lo dice.
import { namesQuery } from './search'
import { followKey, normalize } from './text'

export { followKey }

const MAX_SHOWN = 6
const MAX_SHOWN_IDS = 48 // rappi_agent.py: MAX_SHOWN_IDS (lo que acepta la API en `previous`)
const MIN_NAMED = 3 // rappi_agent.py: MIN_SHOWN (con menos que digan lo pedido, todo lo del concepto)
const AGE_NOTICE = ' Recuerda: estos productos se venden solo a mayores de 18.'
const NO_REMEDIES =
  'Esta demo sin conexión no busca remedios. Pregúntale al químico farmacéutico qué te sirve para eso.'
const NUMBERS = { dos: 2, tres: 3, cuatro: 4, cinco: 5, seis: 6, siete: 7, ocho: 8, nueve: 9, diez: 10 }
const NUMBERS_TOO = { doce: 12, quince: 15, veinte: 20, treinta: 30 }
const HOW_MANY = `(\\d{1,2}|${Object.keys({ ...NUMBERS, ...NUMBERS_TOO }).join('|')})`
const MAX_PEOPLE = 40
// understand.py: VERTICAL_MENTIONS, las que sirven para "en el súper mejor" o "y en la farmacia?".
const MENTIONS = [
  [/\b(?:super|supermercado|lider|jumbo|unimarc|tottus)\b/g, 'supermercado'],
  [/\bfarmacias?\b/g, 'farmacia'],
  [/\b(?:botilleria|licoreria|licores)\b/g, 'licores'],
  [/\b(?:express|minimarket|oxxo)\b/g, 'conveniencia'],
  [/\brestaurant(?:e|es)?\b/g, 'restaurantes'],
  [/\bturbo\b/g, 'turbo'],
  [/\bchocolateria\b/g, 'chocolateria'],
  [/\ben el mall\b/g, 'mall'],
]
// Lo que acompaña un seguimiento sin decir nada más (understand.py: FOLLOW_UP_FILLER y lo que va con "otra opción").
const FILLER = new Set([
  'y',
  'mejor',
  'entonces',
  'ahora',
  'tambien',
  'pero',
  'algo',
  'uno',
  'una',
  'el',
  'la',
  'los',
  'las',
  'de',
  'en',
])
for (const word of ['al', 'del', 'porfa', 'por', 'favor', 'opcion', 'opciones', 'marca', 'mas', 'menos', 'no', 'mochi'])
  FILLER.add(word)
// rappi_agent.py: DIETS y DIET_NAMES. Un régimen se cumple si el nombre lo dice; un ingrediente, si no lo nombra.
const DIETS = new Set(['carne', 'lactosa', 'gluten', 'azucar', 'alcohol', 'sal', 'grasa', 'cafeina', 'sodio'])
const DIET_NAMES = { carne: 'vegetarian[oa]s?|vegan[oa]s?|veggies?|vegetal(?:es)?', lactosa: 'deslactosad[oa]s?' }
const ACCENTS = { azucar: 'azúcar', cafeina: 'cafeína', pina: 'piña', jamon: 'jamón', limon: 'limón', mani: 'maní' }

const stem = (word) =>
  word.length > 4 && word.endsWith('es') && 'nrldzj'.includes(word.at(-3))
    ? word.slice(0, -2)
    : word.length > 3 && word.endsWith('s')
      ? word.slice(0, -1)
      : word

/**
 * Lo que dice un seguimiento: `{ order, priceMax, people, without, vertical, other }`, o null si el mensaje nombra algo
 * más (un tema nuevo, que se responde como siempre). "más barato", "menos de 10 lucas", "para 10 personas", "somos 8",
 * "sin carne", "en el súper mejor", "otra opción".
 */
export function readRefinement(message) {
  let said = ` ${normalize(message)} `
  const found = {}
  const take = (pattern, use) => {
    said = said.replace(pattern, (...match) => {
      use(match)
      return ' '
    })
  }
  take(
    /\b(?:menos de|hasta|bajo|maximo|por menos de|con)\s+(\d+(?:\s\d{3})*)\s*(mil|lucas|luca|k)?\b(?:\s+pesos)?/g,
    ([, digits, thousands]) => {
      const value = Number(digits.replace(/\s/g, '')) * (thousands ? 1000 : 1)
      if (thousands || value >= 100) found.priceMax = value
    },
  )
  take(new RegExp(`\\b(?:somos|seremos|para)\\s+(?:unas?\\s+)?${HOW_MANY}\\b(?:\\s+personas?)?`, 'g'), ([, n]) => {
    const people = /^\d+$/.test(n) ? Number(n) : { ...NUMBERS, ...NUMBERS_TOO }[n]
    if (people >= 2 && people <= MAX_PEOPLE) found.people = people
  })
  take(/\b(?:mas |menos |no tan )?(?:barat[oa]s?|economic[oa]s?)\b|\b(?:menos|no tan) car[oa]s?\b/g, () => {
    found.order = 'barato'
  })
  take(/\b(?:uno |una )?mas car[oa]s?\b|\bpremium\b/g, () => {
    found.order = 'caro'
  })
  take(/\b(?:otr[oa]s?|distint[oa]s?|diferentes?|ningun[oa])\b/g, () => {
    found.other = true
  })
  take(/\bsin\s+(?:el |la |los |las )?([a-z]{3,})\b/g, ([, word]) => {
    found.without = [...(found.without ?? []), word]
  })
  for (const [pattern, vertical] of MENTIONS)
    take(pattern, () => {
      found.vertical = vertical
    })
  const rest = said.split(' ').filter((w) => w && !FILLER.has(w))
  return rest.length || !Object.keys(found).length ? null : found
}

/** Lo que va "sin" en una consulta ("pizza sin carne"): las palabras tras "sin". */
const withoutIn = (query) => [...` ${normalize(query)} `.matchAll(/ sin ([a-z]{3,})(?= )/g)].map((m) => m[1])

/** Si el nombre dice el régimen ("sin lactosa", "vegetariana"). */
function saysFreeFrom(name, word) {
  const other = DIET_NAMES[word] ? `|${DIET_NAMES[word]}` : ''
  return new RegExp(`\\b(?:(?:sin|libre de|cero|0)\\s+${stem(word)}(?:es|s)?${other})\\b`).test(normalize(name))
}

/** Si el producto cumple lo que va "sin" (rappi_agent.py: _keeps). "Sin alcohol" no pide nada a lo que no tiene. */
function keeps(product, without) {
  return without.every((word) => {
    if (word === 'alcohol' && !product.age_restricted) return true
    if (DIETS.has(word)) return saysFreeFrom(product.name, word)
    return !new RegExp(`\\b${stem(word)}(?:es|s)?\\b`).test(normalize(product.name)) || saysFreeFrom(product.name, word)
  })
}

/** Lo pedido sin lo que no va, sin el orden ni la cantidad de personas (rappi_agent.py: _core_query). */
const core = (query) =>
  normalize(query)
    .replace(/\bsin [a-z]+\b/g, ' ')
    .replace(/\b(?:mas |menos )?(?:barat[oa]s?|economic[oa]s?|car[oa]s?)\b/g, ' ')
    .replace(new RegExp(`\\b(?:para|somos|de)\\s+${HOW_MANY}(?:\\s+personas?)?\\b`, 'g'), ' ')
    .replace(/\b(?:talla|sabor|marca|tipo)\b/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()

/** "Para 6 personas, calcula unos 2,1 kg de carne." (compose.py: _for_people). */
function forPeople(people, occasion) {
  if (!people) return ''
  if (!occasion?.portion) return ` Para ${people} personas: revisa para cuántos alcanza cada producto.`
  const total = occasion.portion.grams * people
  const amount = total >= 1000 ? `${String(Math.round(total / 100) / 10).replace('.', ',')} kg` : `${total} g`
  return ` Para ${people} personas, calcula unos ${amount} de ${occasion.portion.of}.`
}

const money = (value) => `$${Math.round(value).toLocaleString('es-CL')}`

/** Cómo se nombra lo pedido en el texto: la ocasión, el concepto o lo dicho. */
function nameOf(meta, previous, occasion) {
  if (occasion) return `${occasion.name.toLowerCase()} ${occasion.emoji}`
  const concept = meta.concepts[previous.concepts?.[0]]
  return concept ? `${concept.emoji} ${concept.name.toLowerCase()}` : `"${previous.query}"`
}

/** El estado de la conversación que la app devuelve como `previous` (rappi_agent.py: _conversation). */
const state = (fields) => ({
  query: '',
  concepts: [],
  occasion: null,
  vertical: null,
  price_max: null,
  people: null,
  order: null,
  symptom: false,
  product_ids: [],
  ...fields,
})

/**
 * La respuesta a un seguimiento sobre la muestra: los productos de lo pedido antes (sus conceptos o, en una ocasión, los
 * suyos que Mochi propone) en la vertical, con lo que va "sin", el tope, sin lo ya mostrado si se pide "otra opción" y
 * por precio si se pide. Si nada de la muestra cumple, lo dice; los remedios no los busca.
 */
export function followUp(snapshot, body, refinement) {
  const { meta } = snapshot
  const previous = body.previous
  if (previous.symptom)
    return reply(NO_REMEDIES, [], null, { kind: 'buscar', symptom: true, follow_up: true }, previous)
  const occasion = meta.occasions?.[previous.occasion] ?? null
  const vertical = refinement.vertical ?? previous.vertical
  const concepts = previous.concepts?.length
    ? previous.concepts
    : (occasion?.concepts ?? []).filter((c) => meta.concepts[c]?.offerable)
  const without = [...new Set([...withoutIn(previous.query), ...(refinement.without ?? [])])]
  const query = [previous.query, ...(refinement.without ?? []).map((w) => `sin ${w}`)].join(' ')
  const priceMax = refinement.priceMax ?? previous.price_max ?? null
  const people = refinement.people ?? previous.people ?? null
  const order = refinement.order ?? previous.order ?? null
  const seen = refinement.other ? new Set(previous.product_ids ?? []) : new Set()

  const unique = new Map()
  for (const p of snapshot.pool)
    if (p.vertical === vertical && (concepts.length ? concepts.includes(p.concept) : namesQuery(meta, p.name, query)))
      unique.set(p.id, p)
  let found = [...unique.values()].filter(
    (p) => keeps(p, without) && (priceMax == null || (p.price_value ?? Infinity) <= priceMax) && !seen.has(p.entity_id),
  )
  const named = core(query) ? found.filter((p) => namesQuery(meta, p.name, core(query))) : []
  if (named.length >= MIN_NAMED) found = named
  if (order)
    found.sort((a, b) => ((a.price_value ?? Infinity) - (b.price_value ?? Infinity)) * (order === 'caro' ? -1 : 1))
  const products = found.slice(0, MAX_SHOWN)

  const label = meta.vertical_labels[vertical] ?? vertical
  const what =
    nameOf(meta, previous, occasion) +
    (without.length ? ` sin ${without.map((w) => ACCENTS[w] ?? w).join(' ni ')}` : '') +
    (priceMax != null ? ` bajo ${money(priceMax)}` : '')
  const ageNotice = products.some((p) => p.age_restricted)
  const text = products.length
    ? `${refinement.other ? 'Otras opciones de' : order === 'barato' ? 'Lo más barato de' : 'Mira estas opciones de'} ${what} en ${label}.${forPeople(people, occasion)}${ageNotice ? AGE_NOTICE : ''}`
    : `En la muestra de esta demo no encontré ${refinement.other ? 'otras opciones de ' : ''}${what} en ${label}.`
  const shown = products.map((p) => p.entity_id)
  const conversation = state({
    query,
    concepts: previous.concepts ?? [],
    occasion: previous.occasion ?? null,
    vertical,
    price_max: priceMax,
    people,
    order,
    product_ids: (refinement.other ? [...seen, ...shown] : shown).slice(-MAX_SHOWN_IDS),
  })
  const intent = { kind: occasion ? 'ocasion' : 'buscar', query, concepts, occasion: previous.occasion ?? null }
  return reply(text, products, vertical, { ...intent, price_max: priceMax, follow_up: true }, conversation, {
    snapshot,
    ageNotice,
  })
}

function reply(text, products, vertical, intent, conversation, { snapshot, ageNotice = false } = {}) {
  return {
    text,
    products,
    vertical,
    prototype_vertical: vertical ? (snapshot?.meta.screen_verticals[vertical] ?? null) : null,
    intent: { confidence: 0.8, vertical, concepts: [], occasion: null, price_max: null, symptom: false, ...intent },
    reason: null,
    suggestion: null,
    actions: [],
    tags: intent.concepts ?? [],
    stores: [],
    unmet: false,
    unmet_reason: null,
    age_notice: ageNotice,
    conversation,
  }
}

/**
 * El estado de una respuesta que no lo trae (las grabadas con una API anterior y las que arma la demo): lo pedido, sus
 * conceptos (vacío en una ocasión), la vertical y lo mostrado; null si no se sigue (un saludo, un consejo, sin nada).
 * "¿y para tomar?" después de un asado de 6 conserva las 6 personas, como la API.
 */
export function withConversation(answer, body) {
  const previous = body?.previous
  const and = normalize(body?.message).startsWith('y ')
  let conversation = answer.conversation
  if (conversation === undefined) {
    const intent = answer.intent ?? {}
    const followable = answer.products?.length && !['consejo', 'aclarar', 'servicio'].includes(intent.kind)
    conversation = followable
      ? state({
          query: intent.query ?? '',
          concepts: intent.occasion ? [] : (intent.concepts ?? []),
          occasion: intent.occasion ?? null,
          vertical: answer.vertical ?? null,
          price_max: intent.price_max ?? null,
          symptom: Boolean(intent.symptom),
          product_ids: answer.products.map((p) => p.entity_id),
        })
      : null
  }
  if (!conversation) return answer // sin `conversation`, la app no cambia el turno anterior (como con null)
  if (!(and && previous?.people && !conversation.people)) return { ...answer, conversation }
  const people = ` Para ${previous.people} personas: revisa para cuántos alcanza cada producto.`
  return { ...answer, text: answer.text + people, conversation: { ...conversation, people: previous.people } }
}
