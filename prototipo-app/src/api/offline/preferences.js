// Preferencias explícitas con Mochi sin conexión: copia corta de rappi-ia/src/rappi_ia/offers/preferences.py y de sus
// opciones (offers/preferencias.toml; preferences.test.js revisa que los ids y las frases sean los mismos). Se guardan
// en el estado de la API simulada (state.js). La dieta y las alergias solo filtran lo que Mochi muestra y ofrece, por el
// nombre y solo en comida; nunca son la razón de una oferta. Las favoritas solo ordenan.
import { normalize } from './text'

const MEAT = [
  ...['carne', 'carnes', 'vacuno', 'cerdo', 'chancho', 'pollo', 'pavo', 'jamon', 'tocino', 'bacon', 'salame'],
  ...['salami', 'chorizo', 'longaniza', 'prieta', 'salchicha', 'salchichas', 'vienesa', 'vienesas', 'pepperoni'],
  ...['peperoni', 'pino', 'lomo', 'lomito', 'filete', 'churrasco', 'mechada', 'costilla', 'costillas', 'costillar'],
  ...['pernil', 'asado', 'parrillada', 'plateada', 'panceta', 'hamburguesa', 'nuggets', 'alitas', 'chicken', 'beef'],
  ...['pork', 'atun', 'salmon', 'pescado', 'reineta', 'merluza', 'congrio', 'camaron', 'camarones', 'marisco'],
  ...['mariscos', 'pulpo', 'calamar', 'kanikama', 'surimi', 'ebi', 'anchoa', 'anchoas', 'sardina', 'sardinas', 'jurel'],
  ...['chacarero', 'barros luco', 'completo', 'hot dog', 'choripan', 'anticucho', 'anticuchos', 'chorrillana'],
  ...['shawarma', 'kebab', 'carnitas', 'al pastor', 'gallina', 'ternera', 'cordero', 'ceviche'],
]
const MEAT_CONCEPTS = ['carnes', 'pollo', 'pescados-mariscos', 'fiambres', 'pollo-preparado', 'hamburguesa']
const PLANT_MILKS = 'de almendras?|de avena|de soya|de soja|de coco|de arroz'

export const RULES = [
  {
    id: 'vegetariano',
    tipo: 'dieta',
    nombre: 'Vegetariano',
    sin: 'carne',
    frases: ['soy vegetariano', 'soy vegetariana', 'no como carne', 'no como carnes', 'no como nada de carne'],
    conceptos: MEAT_CONCEPTS,
    palabras: MEAT,
    salvo: /\b(?:vegetarian[oa]s?|vegan[oa]s?|veggies?|vegetal|sin carne|plant based)\b/,
  },
  {
    id: 'vegano',
    tipo: 'dieta',
    nombre: 'Vegano',
    sin: 'carne, lácteos, huevo y miel',
    frases: ['soy vegano', 'soy vegana'],
    conceptos: [...MEAT_CONCEPTS, 'lacteos', 'quesos', 'huevos'],
    palabras: [
      ...MEAT,
      ...['leche', 'queso', 'quesos', 'quesillo', 'crema', 'mantequilla', 'yogur', 'yogurt', 'yoghurt', 'huevo'],
      ...['huevos', 'miel', 'manjar', 'mayonesa', 'cheese', 'mozzarella', 'parmesano', 'gouda', 'ricota', 'nata'],
      ...['chantilly', 'tres leches'],
    ],
    salvo: new RegExp(`\\b(?:vegan[oa]s?|vegetal|plant based|sin lacteos|${PLANT_MILKS})\\b`),
  },
  {
    id: 'mani',
    tipo: 'alergia',
    nombre: 'Alergia al maní',
    sin: 'maní',
    frases: [
      ...['no como mani', 'soy alergico al mani', 'soy alergica al mani', 'tengo alergia al mani', 'alergia al mani'],
      ...['alergico al mani', 'alergica al mani'],
    ],
    conceptos: [],
    palabras: ['mani', 'manies', 'cacahuate', 'cacahuete', 'peanut', 'peanuts', 'snickers'],
    salvo: /\bsin mani\b/,
  },
  {
    id: 'mariscos',
    tipo: 'alergia',
    nombre: 'Alergia a los mariscos',
    sin: 'mariscos',
    frases: [
      ...['no como mariscos', 'soy alergico a los mariscos', 'soy alergica a los mariscos'],
      ...['tengo alergia a los mariscos', 'alergia a los mariscos', 'alergico a los mariscos'],
      ...['alergica a los mariscos', 'alergia a mariscos'],
    ],
    conceptos: [],
    palabras: [
      ...['marisco', 'mariscos', 'camaron', 'camarones', 'langostino', 'langostinos', 'jaiba', 'jaibas', 'centolla'],
      ...['langosta', 'ostion', 'ostiones', 'ostra', 'ostras', 'chorito', 'choritos', 'mejillon', 'mejillones'],
      ...['almeja', 'almejas', 'macha', 'machas', 'locos', 'calamar', 'calamares', 'pulpo', 'ebi', 'kanikama'],
      ...['paila marina', 'ceviche mixto'],
    ],
    salvo: /\bsin mariscos\b/,
  },
  {
    id: 'gluten',
    tipo: 'alergia',
    nombre: 'Sin gluten',
    sin: 'gluten',
    frases: [
      ...['soy celiaco', 'soy celiaca', 'no como gluten', 'soy intolerante al gluten', 'intolerante al gluten'],
      ...['tengo intolerancia al gluten', 'alergia al gluten', 'soy alergico al gluten', 'soy alergica al gluten'],
    ],
    conceptos: [
      ...['panaderia', 'pastas', 'galletas', 'pasteleria', 'pizza', 'empanadas', 'sandwiches', 'hamburguesa'],
      ...['cerveza', 'cereales', 'reposteria', 'barras-cereal'],
    ],
    palabras: [
      ...['trigo', 'harina', 'pan', 'panes', 'pancito', 'galleta', 'galletas', 'galleton', 'galletones', 'fideo'],
      ...['fideos', 'tallarin', 'tallarines', 'spaghetti', 'espagueti', 'lasana', 'ravioles', 'noquis', 'pasta'],
      ...['pastas', 'empanada', 'empanadas', 'pizza', 'pizzas', 'cerveza', 'cervezas', 'queque', 'torta', 'tortas'],
      ...['kuchen', 'berlin', 'croissant', 'medialuna', 'sandwich', 'sandwiches', 'marraqueta', 'hallulla'],
      ...['baguette', 'cebada', 'centeno', 'apanado', 'apanada', 'tempura', 'churros', 'sopaipilla', 'sopaipillas'],
      ...['wrap', 'brownie', 'muffin', 'panqueques'],
    ],
    salvo: /\b(?:sin gluten|libre de gluten|gluten free|celiac[oa]s?|sin tacc)\b/,
  },
  {
    id: 'lactosa',
    tipo: 'alergia',
    nombre: 'Sin lactosa',
    sin: 'lactosa',
    frases: [
      ...['soy intolerante a la lactosa', 'intolerante a la lactosa', 'tengo intolerancia a la lactosa'],
      ...['no tomo leche', 'no puedo tomar leche', 'alergia a la lactosa'],
    ],
    conceptos: ['lacteos', 'quesos', 'helados'],
    palabras: [
      ...['leche', 'queso', 'quesos', 'quesillo', 'crema', 'mantequilla', 'yogur', 'yogurt', 'yoghurt', 'manjar'],
      ...['helado', 'helados', 'cheese', 'mozzarella', 'parmesano', 'gouda', 'ricota', 'nata', 'chantilly'],
      ...['tres leches', 'milkshake'],
    ],
    salvo: new RegExp(
      `\\b(?:sin lactosa|deslactosad[oa]s?|libre de lactosa|lactose free|0 lactosa|vegetal|vegan[oa]s?|${PLANT_MILKS})\\b`,
    ),
  },
].map((rule) => ({ ...rule, words: new RegExp(`\\b(?:${rule.palabras.join('|')})\\b`) }))

const BY_ID = Object.fromEntries(RULES.map((rule) => [rule.id, rule]))
// offers/preferencias.toml: los grupos que son comida y las cocinas que se pueden marcar.
export const FOOD_GROUPS = ['alcohol', 'bebidas', 'snacks', 'dulces', 'despensa', 'frescos', 'comida']
export const CUISINES = [
  ...['sushi', 'pizza', 'hamburguesa', 'ensaladas-bowls', 'mexicana', 'peruana', 'asiatica', 'arabe', 'latina'],
  ...['sandwiches', 'empanadas', 'postres'],
]
const KINDS = ['dieta', 'alergia', 'cocina', 'tienda']
const FILTERS = ['dieta', 'alergia']
const MAX_PREFERENCES = 30

const isFood = (meta, product) =>
  product.entity_type === 'menu_item' || !product.concept || FOOD_GROUPS.includes(meta.concepts[product.concept]?.group)

/** Lo que guarda la persona, por tipo (`[{ tipo, valor }]`), listo para filtrar y ordenar. */
export function applied(meta, saved = []) {
  const filters = saved
    .filter((p) => FILTERS.includes(p.tipo))
    .map((p) => BY_ID[p.valor])
    .filter(Boolean)
  const cuisines = saved.filter((p) => p.tipo === 'cocina').map((p) => p.valor)
  const stores = saved.filter((p) => p.tipo === 'tienda').map((p) => normalize(p.valor))
  const keeps = (product) => {
    if (!filters.length || !isFood(meta, product)) return true
    const said = normalize(product.name)
    return !filters.some(
      (rule) => !rule.salvo.test(said) && (rule.conceptos.includes(product.concept) || rule.words.test(said)),
    )
  }
  const favorite = (product) => {
    const store = normalize(product.store)
    return cuisines.includes(product.concept) || stores.some((s) => store === s || store.startsWith(`${s} `))
  }
  return {
    any: saved.length > 0,
    /** Los productos que quedan, con lo de sus favoritas primero (sin sacar nada por ellas). */
    products: (list) => {
      const kept = list.filter(keeps)
      return [...kept.filter(favorite), ...kept.filter((p) => !favorite(p))]
    },
    notice: (list) => {
      if (!filters.length || !list.some((p) => isFood(meta, p))) return null
      return `Por tus preferencias, saqué lo que dice tener ${withoutOf(saved)}; revisa los ingredientes en la tienda.`
    },
  }
}

/** Lo que sacan la dieta y las alergias de `items`: «carne o maní». */
export function withoutOf(items) {
  const said = [...new Set(items.map((p) => FILTERS.includes(p.tipo) && BY_ID[p.valor]?.sin).filter(Boolean))]
  return said.length === 1 ? said[0] : `${said.slice(0, -1).join(', ')} o ${said.at(-1)}`
}

const label = (meta, { tipo, valor }) => {
  if (FILTERS.includes(tipo)) return BY_ID[valor]?.nombre ?? valor
  if (tipo === 'cocina') {
    const concept = meta.concepts[valor]
    return concept ? `${concept.emoji} ${concept.name}` : valor
  }
  return valor
}

/** `[{ tipo, valor, nombre }]`, por tipo y en el orden en que se dijeron (offers/preferences.py: saved y describe). */
export const describe = (meta, saved = []) =>
  KINDS.flatMap((kind) => saved.filter((p) => p.tipo === kind)).map((p) => ({ ...p, nombre: label(meta, p) }))

/** Lo que el panel ofrece marcar (las tiendas se dicen por chat). */
export const options = (meta) =>
  describe(meta, [
    ...RULES.map((rule) => ({ tipo: rule.tipo, valor: rule.id })),
    ...CUISINES.filter((c) => meta.concepts[c]).map((c) => ({ tipo: 'cocina', valor: c })),
  ])

const valid = (meta, { tipo, valor }) =>
  FILTERS.includes(tipo) ? BY_ID[valor]?.tipo === tipo : tipo === 'cocina' ? CUISINES.includes(valor) : false

/** La tienda de la muestra que nombró la persona («jumbo» → «Jumbo»), o null. */
export function findStore(snapshot, said) {
  const wanted = normalize(said)
  if (wanted.length < 3) return null
  const names = [...new Set(snapshot.pool.map((p) => p.store?.trim()).filter(Boolean))]
  const found = names
    .filter((name) => normalize(name) === wanted || normalize(name).startsWith(`${wanted} `))
    .sort((a, b) => a.length - b.length || a.localeCompare(b))
  return found[0] ?? null
}

/** Las de `list` que se pueden guardar, sin repetidas y hasta el tope (las tiendas, solo si existen o ya estaban). */
export function cleaned(snapshot, list, current = []) {
  const kept = []
  for (const item of list) {
    let value = item
    if (item.tipo === 'tienda') {
      const had = current.some((p) => p.tipo === 'tienda' && p.valor === item.valor)
      const store = had ? item.valor : findStore(snapshot, item.valor)
      if (!store) continue
      value = { tipo: 'tienda', valor: store }
    } else if (!valid(snapshot.meta, item)) continue
    if (!kept.some((p) => p.tipo === value.tipo && p.valor === value.valor)) kept.push(value)
  }
  return kept.slice(0, MAX_PREFERENCES)
}

// ── Lo que se dice por chat (offers/preferences.py: read_command) ───────────
const LEADS = /^(?:(?:oye|bueno|ok|hola)\s+)*(?:(?:recuerda que|acuerdate que|anota que|toma nota|yo)\s+)?/
const CLEAR =
  /^(?:olvida|olvidate de|borra|borrame|elimina|quita|limpia|resetea)\s+(?:todas\s+)?(?:mis|las)\s+preferencias\b/
const SHOW =
  /^(?:(?:muestrame|dime|ensename|ver|revisa|cuales son|que son)\s+)?(?:mis\s+preferencias|que preferencias(?:\s+(?:tengo|guardaste|recuerdas))?)\s*$/
const FAVORITE_CUISINE =
  /^(?:mi|mis)\s+(?:comida|comidas|cocina|cocinas)\s+favoritas?\s+(?:es|son)\s+(.+)$|^(?:me gusta|me gustan|me encanta|me encantan)\s+(?:la\s+)?(?:comida|cocina)\s+(.+)$|^(?:agrega|anota|suma)\s+(.+?)\s+(?:a|en)\s+mis\s+favorit[oa]s$/
const FAVORITE_STORE =
  /^(?:mi|mis)\s+(?:tienda|tiendas|super|supermercado|local|restaurante|restaurant)\s+favorit[oa]s?\s+(?:es|son)\s+(.+)$|^prefiero\s+(?:pedir|comprar)\s+en\s+(.+)$/
const UNSAY = ['soy ', 'tengo ', 'alergi', 'intolerante']

function rulesSaid(body) {
  const starts = RULES.some((rule) => rule.frases.some((p) => body === p || body.startsWith(`${p} `)))
  if (!starts) return []
  return RULES.filter((rule) => rule.frases.some((p) => ` ${body} `.includes(` ${p} `)))
}

/** `{ action, items, store?, cuisineText? }` o null si el mensaje no habla de sus preferencias. */
export function readCommand(message) {
  const said = normalize(message)
  if (CLEAR.test(said)) return { action: 'olvidar', items: [] }
  if (SHOW.test(said)) return { action: 'mostrar', items: [] }
  let body = said.replace(LEADS, '')
  let removing = false
  if (body.startsWith('ya no ')) {
    const rest = body.slice('ya '.length)
    const unsay = rest.slice('no '.length)
    removing = UNSAY.some((lead) => unsay.startsWith(lead))
    body = removing ? unsay : rest
  }
  const found = rulesSaid(body)
  if (found.length)
    return { action: removing ? 'quitar' : 'agregar', items: found.map((r) => ({ tipo: r.tipo, valor: r.id })) }
  if (removing) return null
  const store = FAVORITE_STORE.exec(body)
  if (store)
    return {
      action: 'agregar',
      items: [],
      store: store
        .slice(1)
        .find(Boolean)
        .replace(/^(?:el|la|los|las)\s+/, ''),
    }
  const cuisine = FAVORITE_CUISINE.exec(body)
  if (cuisine) return { action: 'agregar', items: [], cuisineText: cuisine.slice(1).find(Boolean) }
  return null
}
