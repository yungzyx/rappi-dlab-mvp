// `GET /search` y `POST /agent/ask` sin conexión: primero la respuesta grabada de la API real (las ideas del buscador,
// los chips de Mochi y búsquedas comunes); si no hay, una búsqueda simple por palabras sobre los productos de la
// muestra, sin tildes ni ñ, con el foco de la búsqueda real en cada vertical (agent/tools.py: _focus; la búsqueda
// híbrida de verdad la hacen agent/grouped_search.py y agent/rappi_agent.py). "Qué me recomiendas" responde con los
// intereses de la persona (rappi_agent.py: _recommend).
import { AGENT_NAME } from '../../agent/name'
import { looksLikeQuestion } from '../../assistant/question'
import { followKey, followUp, readRefinement, withConversation } from './conversation'
import { OFFER_BLOCKED_VERTICALS } from './motor'
import { complementOf, offerableProduct } from './offers'
import { normalize } from './text'

const GROUPED_LIMIT = 6 // por grupo (api/app.py: GROUPED_SEARCH_LIMIT)
const VERTICAL_LIMIT = 10
const ASK_LIMIT = 6
const AGE_NOTICE = ' Recuerda: estos productos se venden solo a mayores de 18.'
const UNMET_REASON = 'sin coincidencias en la muestra de la demo sin conexión'
// Ids del prototipo → códigos del backend (api/deps.py: backend_vertical).
const FROM_PROTOTYPE = {
  grocery: 'supermercado',
  liquor: 'licores',
  pharmacy: 'farmacia',
  retail: 'mall',
  express: 'conveniencia',
  chocolates: 'chocolateria',
  restaurants: 'restaurantes',
}
const VERTICALS = [
  'restaurantes',
  'turbo',
  'supermercado',
  'farmacia',
  'mall',
  'licores',
  'conveniencia',
  'chocolateria',
]

/** El código del backend de una vertical (acepta el id del prototipo); null si no es del catálogo. */
export function backendVertical(vertical) {
  const code = FROM_PROTOTYPE[vertical] ?? vertical
  return VERTICALS.includes(code) ? code : null
}

// Una palabra de la consulta calza con una del nombre si es su comienzo (o el de su singular: "panales" → "panal").
const stem = (word) =>
  word.length > 4 && word.endsWith('es')
    ? word.slice(0, -2)
    : word.length > 3 && word.endsWith('s')
      ? word.slice(0, -1)
      : word
const STOP = new Set([
  'de',
  'del',
  'la',
  'el',
  'los',
  'las',
  'un',
  'una',
  'para',
  'con',
  'en',
  'y',
  'mi',
  'algo',
  'quiero',
])

// ── Los conceptos que nombra una consulta (concepts/matcher.py: KeywordMatcher; concepts/assign.py: QueryMatcher) ──

/** La palabra tal cual y su posible singular (galletas → galleta, panes → pan). */
const candidatesOf = (word) => [
  word,
  ...(word.length > 3 && word.endsWith('es') ? [word.slice(0, -2)] : []),
  ...(word.length > 2 && word.endsWith('s') ? [word.slice(0, -1)] : []),
]
const contains = (words, phrase) => ` ${words.join(' ')} `.includes(` ${phrase} `)

// Por meta: las keywords de los conceptos y de las ocasiones, por su primera palabra.
const indexes = new WeakMap()
function indexOf(meta) {
  if (indexes.has(meta)) return indexes.get(meta)
  const byFirst = (entries) => {
    const map = new Map()
    for (const [id, phrase] of entries) {
      const first = phrase.split(' ')[0]
      map.set(first, [...(map.get(first) ?? []), [id, phrase]])
    }
    return map
  }
  const concepts = Object.entries(meta.concepts)
  const index = {
    keywords: byFirst(concepts.flatMap(([id, c]) => (c.keywords ?? []).map((k) => [id, k]))),
    alone: byFirst(concepts.flatMap(([id, c]) => (c.alone ?? []).map((k) => [id, k]))),
    occasions: byFirst((meta.occasion_keywords ?? []).map((k) => ['ocasion', k])),
    avoid: Object.fromEntries(concepts.map(([id, c]) => [id, c.avoid ?? []])),
    filler: new Set(meta.filler_words ?? []),
  }
  indexes.set(meta, index)
  return index
}

/** Los ids que nombran `words`, el más largo primero y sin solapes ("papas fritas" le gana a "papas"). */
function keywordMatches(byFirst, words, avoid = {}) {
  const forms = new Set(words.flatMap(candidatesOf))
  const found = new Map()
  words.forEach((word, position) => {
    for (const candidate of candidatesOf(word))
      for (const [id, phrase] of byFirst.get(candidate) ?? []) {
        const size = phrase.split(' ').length
        if (size > 1 && words.slice(position, position + size).join(' ') !== phrase) continue
        const avoided = (avoid[id] ?? []).some((a) => (a.includes(' ') ? contains(words, a) : forms.has(a)))
        const best = found.get(id)
        if (!avoided && (!best || size > best.size || (size === best.size && position < best.position)))
          found.set(id, { id, size, position })
      }
  })
  const covered = new Set()
  const result = []
  for (const match of [...found.values()].sort((a, b) => b.size - a.size || a.position - b.position)) {
    const span = Array.from({ length: match.size }, (_, i) => match.position + i)
    if (span.some((i) => covered.has(i))) continue
    span.forEach((i) => covered.add(i))
    result.push(match.id)
  }
  return result
}

// Acompañan un pedido sin nombrar otra cosa (concepts/assign.py: _NOT_CONTENT, además de text.FILLER_WORDS).
const NOT_CONTENT = ['el', 'la', 'los', 'las', 'de', 'del', 'y', 'o', 'algo', 'algun', 'alguna', 'algunos', 'algunas']
const NOT_CONTENT_TOO = ['vende', 'venden', 'barato', 'barata', 'baratos', 'baratas']

/** Los conceptos que nombra la consulta (retrieval/hybrid.py: detect_concepts). Las palabras que solo sirven para pedir
 * un sensible ("medicamentos") cuentan solo si son todo el pedido. */
export function detectConcepts(meta, q) {
  const index = indexOf(meta)
  const words = normalize(q).split(' ').filter(Boolean)
  const found = keywordMatches(index.keywords, words, index.avoid)
  const content = words.filter((w) => !index.filler.has(w) && !NOT_CONTENT.includes(w) && !NOT_CONTENT_TOO.includes(w))
  if (found.length || content.length !== 1) return found
  return keywordMatches(index.alone, content).slice(0, 1)
}

/** Si la consulta nombra una ocasión ("algo para el carrete": retrieval/hybrid.py, named_occasion). */
const namesOccasion = (meta, q) => keywordMatches(indexOf(meta).occasions, normalize(q).split(' ')).length > 0

// Palabras que el nombre de un producto no necesita repetir (agent/tools.py: _NAME_SKIP). "sin" sí: "harina con polvos
// de hornear" no dice "harina sin polvos de hornear".
const NAME_SKIP = ['a', 'al', 'algo', 'con', 'de', 'del', 'el', 'en', 'la', 'las', 'lo', 'los', 'mi', 'para', 'que']
const NAME_SKIP_TOO = ['y']

/** Las palabras sin tildes pero con la ñ: "pañal" no es "panal" (agent/tools.py: _name_words). */
const nameWords = (text) =>
  (text ?? '')
    .toLowerCase()
    .normalize('NFC')
    .replace(/ñ/g, '\0')
    .normalize('NFD')
    .replace(/\p{M}/gu, '')
    .match(/[a-z0-9\0]+/g)
    ?.map((w) => w.replace(/\0/g, 'ñ')) ?? []

/** La palabra y sus singulares posibles: "limones" → limones, limone, limon. */
const formsOf = (word) => [
  word,
  ...(word.endsWith('s') && word.length > 3 ? [word.slice(0, -1)] : []),
  ...(word.endsWith('es') && word.length > 4 ? [word.slice(0, -2)] : []),
]

/** Si el nombre dice todas las palabras de la consulta, en singular o plural (agent/tools.py: _names_query). */
export function namesQuery(meta, name, q) {
  const skip = indexOf(meta).filler
  const inName = new Set(nameWords(name).flatMap(formsOf))
  const wanted = nameWords(q).filter((w) => {
    const plain = normalize(w)
    return !skip.has(plain) && !NAME_SKIP.includes(plain) && !NAME_SKIP_TOO.includes(plain)
  })
  return wanted.length > 0 && wanted.every((w) => formsOf(w).some((f) => inName.has(f)))
}

/**
 * El foco en cada vertical (agent/tools.py: _focus): si la consulta nombra conceptos, solo los productos de esos
 * conceptos; en una vertical sin ninguno, solo lo que dice lo pedido en su nombre ("pañales" no trae el postre con
 * "panal", ni "neumáticos aro 15" unos jugos de 15 g), salvo si pide una ocasión o un concepto amplio ("algo para el
 * asado", "picoteo").
 */
function focus(meta, q, concepts, found) {
  if (!concepts.length) return found
  const broad = namesOccasion(meta, q) || concepts.some((c) => meta.concepts[c]?.broad)
  const withConcept = new Set(found.filter((p) => concepts.includes(p.concept)).map((p) => p.vertical))
  return found.filter((p) =>
    withConcept.has(p.vertical) ? concepts.includes(p.concept) : broad || namesQuery(meta, p.name, q),
  )
}

/** Los productos de la muestra que calzan con `q`, del mejor al peor (cada uno una vez por vertical), con el foco. */
export function matchProducts(snapshot, q) {
  const words = normalize(q)
    .split(' ')
    .filter((w) => w && !STOP.has(w))
    .map(stem)
  if (!words.length) return []
  const concepts = detectConcepts(snapshot.meta, q)
  const scored = []
  const seen = new Set()
  for (const p of snapshot.pool) {
    const name = ` ${normalize(p.name)}`
    const inName = words.filter((w) => name.includes(` ${w}`)).length
    const byConcept = concepts.includes(p.concept)
    if (inName < words.length && !byConcept) continue
    const key = `${p.vertical}|${p.id}`
    if (seen.has(key)) continue
    seen.add(key)
    scored.push({ p, score: inName * 2 + (byConcept ? 1 : 0) + (name.startsWith(` ${words[0]}`) ? 1 : 0) })
  }
  const found = scored.sort((a, b) => b.score - a.score).map((s) => s.p)
  return focus(snapshot.meta, q, concepts, found)
}

/** Grupos por vertical: la de la pantalla primero, después las que más productos calzan (search_grouped). */
function groupsOf(snapshot, found, current, limit) {
  const byVertical = new Map()
  for (const p of found) byVertical.set(p.vertical, [...(byVertical.get(p.vertical) ?? []), p])
  const order = [...byVertical.keys()].sort(
    (a, b) => (b === current) - (a === current) || byVertical.get(b).length - byVertical.get(a).length,
  )
  return order.map((vertical) => ({
    vertical,
    prototype_vertical: snapshot.meta.screen_verticals[vertical] ?? null,
    products: byVertical.get(vertical).slice(0, limit),
  }))
}

/** `GET /search?q=&vertical=&current=&limit=`. */
export function search(snapshot, query) {
  const q = query.get('q') ?? ''
  const vertical = backendVertical(query.get('vertical'))
  const current = backendVertical(query.get('current'))
  const limit = Number(query.get('limit')) || null
  const recorded = snapshot.search[normalize(q)]
  if (query.get('vertical')) {
    const group = recorded?.groups.find((g) => g.vertical === vertical)
    const products = (group?.products ?? matchProducts(snapshot, q).filter((p) => p.vertical === vertical)).slice(
      0,
      limit ?? VERTICAL_LIMIT,
    )
    return {
      vertical,
      products,
      unmet: !products.length,
      unmet_reason: products.length ? null : UNMET_REASON,
      corrected_query: null,
    }
  }
  if (recorded && !current) return recorded
  const groups = groupsOf(snapshot, matchProducts(snapshot, q), current, limit ?? GROUPED_LIMIT)
  return {
    groups,
    query: q,
    unmet: !groups.length,
    unmet_reason: groups.length ? null : UNMET_REASON,
    corrected_query: null,
  }
}

/** El concepto más repetido entre los productos. */
function topConcept(products) {
  const counts = new Map()
  for (const p of products) if (p.concept) counts.set(p.concept, (counts.get(p.concept) ?? 0) + 1)
  return [...counts].sort((a, b) => b[1] - a[1])[0]?.[0] ?? null
}

/** La sugerencia cruzada de una respuesta (agent/tools.py: suggest_complement): el complemento grabado del concepto
 * para esta persona. */
function suggestionFor(snapshot, conceptId, userId) {
  const { concepts } = snapshot.meta
  const origin = concepts[conceptId]
  const recorded = complementOf(snapshot, conceptId, userId)
  if (!origin?.offerable || !recorded) return null
  const target = concepts[recorded.reason?.concept]
  const products = recorded.products.filter((p) => offerableProduct(p, concepts)).slice(0, 3)
  if (!target || !products.length) return null
  return {
    concept: recorded.reason.concept,
    vertical: recorded.vertical,
    prototype_vertical: recorded.prototype_vertical,
    question: `¿Te tinca sumar ${target.emoji} ${target.name.toLowerCase()}?`,
    reason: `Porque llevas ${origin.emoji} ${origin.name.toLowerCase()}`,
    products,
    basis: [],
  }
}

/** La respuesta de Mochi con los productos de un grupo (o "No encontré…" sin grupo). */
function replyWith(snapshot, message, group, { mode, userId }) {
  const { vertical_labels: labels, screen_verticals: screens } = snapshot.meta
  const products = group?.products ?? []
  const concept = topConcept(products)
  const ageNotice = products.some((p) => p.age_restricted)
  const suggestion = concept && mode !== 'actual' ? suggestionFor(snapshot, concept, userId) : null
  const text = group
    ? `Mira lo que encontré de "${message.trim()}" en ${labels[group.vertical] ?? group.vertical}.${ageNotice ? AGE_NOTICE : ''}`
    : `No encontré "${message.trim()}" en la muestra de esta demo. Prueba con otras palabras.`
  return {
    text,
    products,
    vertical: group?.vertical ?? null,
    prototype_vertical: group ? (screens[group.vertical] ?? null) : null,
    intent: {
      kind: 'buscar',
      query: message.trim(),
      concepts: concept ? [concept] : [],
      vertical: group?.vertical ?? null,
      confidence: 0.5,
      follow_up: false,
      occasion: null,
      price_max: null,
    },
    reason: suggestion?.reason ?? null,
    suggestion,
    actions: [],
    tags: concept ? [concept] : [],
    stores: [],
    unmet: !group,
    unmet_reason: group ? null : UNMET_REASON,
    age_notice: ageNotice,
  }
}

// agent/understand.py: las frases de la intención `recomendar`.
const RECOMMEND = [
  'me recomiendas',
  'que me recomiendas',
  'recomiendame',
  'que me sugieres',
  'sugiereme',
  'sorprendeme',
]
const RECOMMEND_INTERESTS = 3 // rappi_agent.py: los intereses que prueba antes de pasar a los ejemplos

// agent/understand.py (APP_QUESTIONS) y rappi_agent.py (_small_talk, HELP_ACTIONS, HELP_EXAMPLES) y compose.py, en corto:
// "¿qué puedes hacer?", el resumen antes de pagar (la app lo arma con su carro) y el último pedido (la app lo muestra).
// El resumen va antes que el pedido: "hacer el pedido" no pregunta por uno en camino.
const APP_QUESTIONS = [
  [
    'ayuda',
    ['ayuda', 'ayudame', 'quien eres', 'que eres', 'que puedes hacer', 'que haces', 'como funciona', 'como te uso'],
  ],
  [
    'resumen',
    [
      ...['resumen de mi pedido', 'resumen del pedido', 'resumen de mi carro', 'resumen del carro'],
      ...['resumen de mi carrito', 'resumen del carrito', 'resumen de la compra', 'resumen de mi compra'],
      ...['que llevo en el carro', 'que llevo en mi carro', 'que tengo en el carro', 'que tengo en mi carro'],
      ...['que hay en mi carro', 'ver mi carro', 'ver mi carrito', 'revisar mi carro', 'cuanto llevo'],
      ...['cuanto va mi carro', 'quiero pagar', 'ir a pagar', 'como pago', 'finalizar compra', 'finalizar la compra'],
      ...['finalizar pedido', 'terminar la compra', 'terminar el pedido', 'cerrar el pedido', 'confirmar pedido'],
      ...['confirmar el pedido', 'hacer el pedido', 'haz el pedido', 'pide por mi'],
    ],
  ],
  [
    'pedido',
    [
      ...['mi pedido', 'el pedido', 'cancelar', 'reclamo', 'reclamar', 'devolucion', 'reembolso', 'donde viene'],
      ...['no llega', 'no ha llegado', 'llego mal'],
    ],
  ],
  // Fuera de tema: se contesta y se vuelve a lo que Mochi sabe hacer (no es demanda no atendida).
  [
    'fuera',
    [
      ...['clima', 'chiste', 'capital de', 'te quiero', 'te amo', 'eres tonto', 'tonto', 'idiota', 'como estas'],
      ...['quien gano', 'noticias'],
    ],
  ],
]
// text.py: GREETING_WORDS y THANKS_WORDS; understand.py: LAUGHTER y LINK (un saludo, un "gracias", una risa o un link
// no piden nada).
const GREETING_WORDS = new Set(['hola', 'holi', 'buenas', 'buenos', 'dias', 'tardes', 'noches', 'hey', 'wena', 'alo'])
GREETING_WORDS.add('ola')
const THANKS_WORDS = new Set(['gracias', 'muchas', 'vale', 'listo', 'ok', 'okay', 'perfecto', 'genial', 'bacan'])
THANKS_WORDS.add('buenisimo')
const LAUGHTER = /^(?:(?:j[aeiou]){2,}j?|(?:[aeiou]?j){2,}|x+d+|lol|jsjs\w*)$/
const LINK = /https?:\/\/|www\./i
// rappi_agent.py: IDEA_KINDS, las respuestas que dejan ideas para tocar.
const IDEA_KINDS = new Set(['ayuda', 'saludo', 'vacio', 'fuera'])
export const HELP_ACTIONS = [
  { label: '🔁 Repite lo de siempre', capability: 'recompra' },
  { label: '🧺 Arma un kit', capability: 'plan' },
  { label: '✨ Algo para ti', capability: 'perfil' },
  { label: '🍣 Algo de sushi', query: 'sushi' },
]
export const HELP_EXAMPLES = [
  { label: '🍣 Algo de sushi', query: 'sushi' },
  { label: '🍽️ ¿Qué almuerzo hoy?', query: 'tengo hambre' },
  { label: '🎉 Arma un carrete', query: 'algo para el carrete' },
]
const HELP_TEXT =
  `Soy ${AGENT_NAME} 🧡, tu asistente en Rappi. Puedo repetir lo de siempre, armarte un kit o mostrarte algo para ti. ` +
  'Busca lo que necesites ("pañales talla G", "algo de sushi", "una once para 4") y te muestro lo que hay, aunque ' +
  'esté en otra vertical. Tu dieta y tus alergias las marcas en "Mis preferencias", y te llevo a RappiTravel o ' +
  'RappiFavor.'
const HELP_TODAY =
  `Soy ${AGENT_NAME} 🧡, tu asistente en Rappi. ` +
  'Busca lo que necesites ("pañales talla G", "algo de sushi", "una once para 4") y te muestro lo que hay, aunque ' +
  'esté en otra vertical.'
// El resumen y el pedido: los mismos textos que pone la app (components/assistant/AssistantPanel.jsx).
export const SUMMARY_TEXT =
  'Este es el resumen de tu pedido antes de pagar 🧾. Revísalo y paga en el checkout: si no me diste permiso con ' +
  '"Pedir por mí", el pedido lo haces tú.'
export const ORDER_TEXT =
  'Tu pedido lo sigues en "Mis pedidos" 🛵: ahí ves dónde viene, lo cancelas antes de que salga o pides ayuda si ' +
  'algo llegó mal.'
// compose.py: saludo, gracias, fuera y vacio.
const SMALL_TALK = {
  saludo: (interest) =>
    `¡Hola! Soy ${AGENT_NAME} 🧡.${interest ? ` Veo tu interés en ${interest}.` : ''} Toca una idea o busca lo que quieras.`,
  gracias: () => '¡De nada! Aquí estoy si necesitas algo más 🧡',
  fuera: () => 'De eso no sé mucho 🧡, lo mío es ayudarte a pedir: comida, súper, farmacia…',
  vacio: () =>
    'No entendí qué buscas. Toca una idea o busca un antojo (sushi, café…), un producto o una ocasión (asado, once…).',
}

/** La ayuda: lo que Mochi sabe hacer (la app resuelve cada `capability`); en "Rappi hoy", solo ejemplos. */
export const helpReply = (mode) =>
  textReply(mode === 'actual' ? HELP_TODAY : HELP_TEXT, 'ayuda', {
    actions: mode === 'actual' ? HELP_EXAMPLES : HELP_ACTIONS,
  })

/**
 * Un saludo, un "gracias", una risa o un link (understand.py, al principio de `understand`; rappi_agent.py:
 * _small_talk): la respuesta, con las ideas para tocar salvo en el "gracias", o null si no es uno de esos.
 */
function smallTalk(snapshot, message, mode, interests) {
  const normalized = normalize(message.replace(/([^\W\d_xw])\1{2,}/giu, '$1'))
  const words = normalized.split(' ').filter(Boolean)
  const names = new Set([normalize(AGENT_NAME)])
  let kind = null
  if (!/[a-z]/.test(normalized) || LINK.test(message) || words.every((w) => LAUGHTER.test(w))) kind = 'vacio'
  else if (words.every((w) => GREETING_WORDS.has(w) || names.has(w)) && words.some((w) => GREETING_WORDS.has(w)))
    kind = 'saludo'
  else if (
    words.every((w) => THANKS_WORDS.has(w) || GREETING_WORDS.has(w) || names.has(w)) &&
    words.some((w) => THANKS_WORDS.has(w))
  )
    kind = 'gracias'
  if (!kind) return null
  const interest = mode === 'actual' ? null : snapshot.meta.concepts[interests?.[0]]?.label?.toLowerCase()
  return smallTalkReply(kind, mode, interest)
}

const smallTalkReply = (kind, mode, interest = null) =>
  textReply(SMALL_TALK[kind](interest), kind, {
    ...(IDEA_KINDS.has(kind) ? { actions: mode === 'actual' ? HELP_EXAMPLES : HELP_ACTIONS } : {}),
  })

/**
 * "¿qué puedes hacer?", "quiero pagar", "¿dónde viene mi pedido?", "¿cómo está el clima?": la respuesta, o null si no
 * es una de esas. Como `KeywordMatcher.best`, gana la frase con más palabras ("ayuda con mi pedido" es del pedido), y
 * una ocasión nombrada ("ayuda para el asado") se busca, no se contesta.
 */
function appQuestion(snapshot, message, mode) {
  const said = ` ${normalize(message)} `
  if (detectConcepts(snapshot.meta, message).length || namesOccasion(snapshot.meta, message)) return null
  let kind = null
  let longest = 0
  for (const [candidate, phrases] of APP_QUESTIONS)
    for (const phrase of phrases) {
      const size = phrase.split(' ').length
      if (size > longest && said.includes(` ${phrase} `)) {
        kind = candidate
        longest = size
      }
    }
  if (kind === 'ayuda') return helpReply(mode)
  if (kind === 'fuera') return smallTalkReply('fuera', mode)
  if (kind === 'resumen')
    return textReply(SUMMARY_TEXT, 'resumen', { actions: [{ label: 'Revisar y pagar', route: ['checkout'] }] })
  if (kind === 'pedido')
    return textReply(ORDER_TEXT, 'pedido', { actions: [{ label: 'Ver mis pedidos', route: ['orders'] }] })
  return null
}
const asksRecommendation = (message) => RECOMMEND.some((phrase) => ` ${normalize(message)} `.includes(` ${phrase} `))

/** La vertical de la muestra con más productos del concepto entre las que Mochi propone (la de verdad la elige
 * agent/verticals.py: ranked_verticals, con el surtido de todo el catálogo). */
function typicalVertical(snapshot, concept) {
  const counts = new Map()
  for (const p of snapshot.pool)
    if (
      p.concept === concept &&
      !OFFER_BLOCKED_VERTICALS.includes(p.vertical) &&
      snapshot.meta.screen_verticals[p.vertical]
    )
      counts.set(p.vertical, (counts.get(p.vertical) ?? 0) + 1)
  return [...counts].sort((a, b) => b[1] - a[1])[0]?.[0] ?? null
}

/**
 * "Qué me recomiendas" (rappi_agent.py: _recommend): por cada interés que Mochi puede proponer, de mayor a menor (hasta
 * 3), busca su nombre en la pantalla actual si Mochi la propone; desde Farmacia, Licores o la Home, en la vertical más
 * típica del interés. Responde el primero que trae productos del interés; si ninguno, sin intereses o en "Rappi hoy",
 * los ejemplos de siempre (`snapshot.help`, grabado de la API real con una persona sin perfil). El backend prueba
 * además la primera keyword del interés; aquí no hace falta: el nombre ya trae todos los productos del concepto.
 */
function recommend(snapshot, body, { interests, userId }) {
  const { concepts, vertical_labels: labels } = snapshot.meta
  const mode = body?.mode
  const mine = mode === 'actual' ? [] : interests.filter((c) => concepts[c]?.offerable).slice(0, RECOMMEND_INTERESTS)
  const here = backendVertical(body?.vertical)
  for (const interest of mine) {
    const vertical = here && !OFFER_BLOCKED_VERTICALS.includes(here) ? here : typicalVertical(snapshot, interest)
    if (!vertical) continue
    const concept = concepts[interest]
    const products = matchProducts(snapshot, concept.name)
      .filter((p) => p.vertical === vertical && offerableProduct(p, concepts))
      .slice(0, ASK_LIMIT)
    if (!products.some((p) => p.concept === interest)) continue
    const reply = replyWith(snapshot, concept.name, { vertical, products }, { mode, userId })
    const name = concept.name.toLowerCase()
    reply.text = `Por tu interés en ${concept.emoji} ${name} 😉 Mira lo que encontré de "${name}" en ${labels[vertical] ?? vertical}.`
    return reply
  }
  // La ayuda grabada, con el texto y los atajos de hoy (una muestra de antes traía "Tengo fiebre" entre los ejemplos, y
  // otra invitaba a escribirle a Mochi).
  const help = helpReply(mode)
  return snapshot.help ? { ...snapshot.help, text: help.text, actions: help.actions } : help
}

// agent/understand.py (SYMPTOMS, MEDICINE_WORDS y ADVICE) y rappi_agent.py (ADVICE_*), en corto: consejo médico y
// síntomas que la muestra no grabó. Sin conexión no se buscan remedios.
const SYMPTOM =
  /\b(?:fiebre|resfrio|resfriado|tos|gripe|dolor|migrana|me duele|guata|nauseas|diarrea|alergia|enferm[oa]|me siento mal|remedios?|acidez|garganta|estrenid[oa]|estrenimiento)\b/
const MEDICINE = /\b(?:medicamentos?|pastillas?|jarabe|dosis)\b/
const NAMED_MEDICINE = /\b(?:paracetamol|ibuprofeno|aspirina|antibiotico|antialergico|antigripal)\b/
const ADVICE =
  /\b(?:le|les|me|te) (?:doy|damos|tomo|tomas|puedo dar|puedo tomar)\b|\b(?:puedo|puede|debo|debe) tomar\b|\bque (?:tomo|tomar|remedios?|medicamento|pastilla|jarabe)\b|\bdosis\b|\bcada cuanto\b|\b(?:sirven?|es buen[oa]) para\b/
const CHILD = /\b(?:hij[oa]s?|nin[oa]s?|guaguas?|bebes?|niet[oa]|sobrin[oa])\b/
const ADVICE_TEXT =
  'No puedo decirte qué remedio tomar o dar, ni cuánto: eso lo ve un médico o un químico farmacéutico 💊.'
const ADVICE_CHILD = ' Pregúntale a su pediatra.'
const ADVICE_END = ' Si es urgente, llama al SAMU (131). Si ya sabes qué remedio buscas, búscalo por su nombre.'
const NO_REMEDIES =
  'Esta demo sin conexión no busca remedios. Pregúntale al químico farmacéutico qué te sirve para eso.'
const NEW_QUESTION = 'Esta demo sin conexión no entiende preguntas nuevas'

/** Una respuesta de solo texto, con el formato de /agent/ask; `symptom`, si es de salud (la app no ofrece ideas debajo). */
function textReply(text, kind, { symptom = false, ...extra } = {}) {
  return {
    text,
    products: [],
    vertical: null,
    prototype_vertical: null,
    intent: {
      kind,
      query: '',
      concepts: [],
      vertical: null,
      confidence: 1,
      follow_up: false,
      occasion: null,
      price_max: null,
      symptom,
    },
    reason: null,
    suggestion: null,
    actions: [],
    tags: [],
    stores: [],
    unmet: false,
    unmet_reason: null,
    age_notice: false,
    ...extra,
  }
}

/**
 * Lo que la muestra no grabó: el consejo médico, como la API (no lo da); un síntoma, sin buscar remedios; y una
 * pregunta nueva, con la búsqueda por palabras y diciendo que no la entiende. null si es un pedido suelto.
 */
function unrecorded(snapshot, message, body, userId) {
  const said = normalize(message)
  const symptom = SYMPTOM.test(said)
  const named = detectConcepts(snapshot.meta, message)
  // Como agent/understand.py (_advice): no si nombra algo que Mochi propone ("qué sopa le doy…"); un niño con un
  // síntoma, sin nombrar el remedio, también es consejo.
  const offerable = named.some((c) => snapshot.meta.concepts[c]?.offerable)
  const child = symptom && CHILD.test(said) && !NAMED_MEDICINE.test(said)
  const sick = symptom || MEDICINE.test(said) || NAMED_MEDICINE.test(said)
  if (sick && !offerable && (child || ADVICE.test(said))) {
    const text = ADVICE_TEXT + (CHILD.test(said) ? ADVICE_CHILD : '') + ADVICE_END
    const farmacia = [{ label: 'Ir a Farmacia', vertical: 'farmacia' }]
    return textReply(text, 'consejo', { symptom: true, actions: farmacia })
  }
  if (symptom && !named.length) return textReply(NO_REMEDIES, 'buscar', { symptom: true })
  if (!looksLikeQuestion(message)) return null
  const found = matchProducts(snapshot, message)
  const group = groupsOf(snapshot, found, backendVertical(body?.vertical), ASK_LIMIT)[0]
  if (!group) return textReply(`${NEW_QUESTION}. Prueba con una de las ideas o escribe un producto.`, 'buscar')
  const reply = replyWith(snapshot, message, group, { mode: body?.mode, userId })
  const label = snapshot.meta.vertical_labels[group.vertical] ?? group.vertical
  reply.text = `${NEW_QUESTION}, solo busca palabras: esto encontré en ${label}.${reply.age_notice ? AGE_NOTICE : ''}`
  return reply
}

/**
 * `POST /agent/ask`: un seguimiento del turno anterior (`previous`: el grabado de la API real o, si no hay, el que arma
 * conversation.js sobre la muestra); "qué me recomiendas" (sin nombrar qué) con los intereses de la persona
 * (`interests`, sus conceptos de mayor a menor); lo demás, la respuesta grabada de esa pregunta o, si no hay, lo que calza
 * en la muestra. Cada respuesta trae `conversation`, lo que la app devuelve como `previous`.
 */
export function ask(snapshot, body, context = {}) {
  const message = String(body?.message ?? '')
  if (body?.previous) {
    const recorded = snapshot.followUps?.[followKey(body.previous, message)]
    if (recorded) return recorded
    const refinement = readRefinement(message)
    if (refinement) return followUp(snapshot, body, refinement)
  }
  return withConversation(answer(snapshot, body, context), body)
}

function answer(snapshot, body, { interests = [], userId = null } = {}) {
  const message = String(body?.message ?? '')
  // Como en agent/understand.py, solo si no nombra algo: "¿me recomiendas un vino?" busca vino.
  const named = detectConcepts(snapshot.meta, message).length || namesOccasion(snapshot.meta, message)
  if (asksRecommendation(message) && !named) return recommend(snapshot, body, { interests, userId })
  const chatted = smallTalk(snapshot, message, body?.mode, interests)
  if (chatted) return chatted
  const asked = appQuestion(snapshot, message, body?.mode)
  if (asked) return asked
  const recorded = snapshot.ask[normalize(message)]
  if (recorded) return recorded
  const honest = unrecorded(snapshot, message, body, userId)
  if (honest) return honest
  const found = matchProducts(snapshot, message)
  const group = groupsOf(snapshot, found, backendVertical(body?.vertical), ASK_LIMIT)[0]
  return replyWith(snapshot, message, group, { mode: body?.mode, userId })
}
