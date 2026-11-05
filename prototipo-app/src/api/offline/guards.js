// Las palabras de offers/guards.py con que el agente reconoce alcohol o bebé en un nombre, y su KeywordMatcher
// (concepts/matcher.py) en corto. `npm run demo:snapshot` las graba de guards.py en `meta.guards`; GUARDS es la copia a
// mano, para una muestra grabada antes de que las trajera (guards.test.js la compara con guards.py).
import { normalize } from './text'

/**
 * offers/guards.py, como lo graba scripts/demo-snapshot-meta.py: `catalog_alcohol` (ALCOHOL_NAME_WORDS, los nombres del
 * catálogo), `menu_alcohol` (MENU_ALCOHOL_NAME_WORDS, los de un menú), `menu_food_senses` (_MENU_FOOD_SENSES: palabra →
 * [frases que dicen que es comida, conceptos de plato que lo dicen]) y `baby` (BABY_NAME_WORDS).
 */
export const GUARDS = {
  catalog_alcohol: [
    ...['soju', 'makgeolli', 'umeshu', 'sake', 'cerveza', 'vino', 'whisky', 'pisco', 'ron', 'vodka', 'gin'],
    ...['tequila', 'licor', 'aperitivo', 'espumante', 'champagne', 'sidra'],
    ...['eristoff', 'smirnoff', 'capel', 'bauza', 'tres erre', 'gran malo', 'petaca'],
  ],
  menu_alcohol: [
    ...['soju', 'sangria', 'michelada', 'cerveza', 'schop', 'shop', 'chela', 'chelada', 'vino', 'pisco', 'piscola'],
    ...['vodka', 'whisky', 'whiskey', 'tequila', 'ron', 'gin', 'mojito', 'margarita', 'terremoto', 'spritz'],
    ...['makgeolli', 'makgeoli', 'umeshu', 'licor', 'espumante', 'champagne', 'champana', 'sidra', 'negroni'],
    ...['caipirinha', 'caipirina', 'daiquiri', 'sour', 'borgona', 'pina colada'],
    ...['corona', 'escudo', 'guinness', 'kunstmann', 'heineken', 'cristal', 'stella artois'],
    ...['budweiser', 'cusquena'],
    ...['cabernet', 'carmenere', 'merlot', 'chardonnay', 'sauvignon', 'syrah', 'malbec', 'pinot', 'cono sur'],
    ...['tom collins', 'vaina', 'algarrobina', 'daikiri', 'caipiroska', 'bloody mary', 'cuba libre', 'kir royal'],
    ...['ruso blanco', 'ruso negro', 'cosmopolitan', 'clavo oxidado', 'ramazzotti'],
    ...['absolut', 'absolute', 'ramazzoti'],
  ],
  menu_food_senses: {
    margarita: [['pizza', 'pizzeta'], ['pizza']],
    sour: [
      ['cream', 'sweet', 'hot', 'roll', 'papas'],
      ['salsas', 'sushi', 'pescados-mariscos', 'sopas'],
    ],
    corona: [['la corona', 'sacra'], []],
    negroni: [['salame'], []],
    cristal: [['latte', 'fideo'], []],
    'pina colada': [
      ['sin alcohol', 'virgin', 'jugo', 'smoothie', 'shake', 'milkshake', 'tea', 'helado'],
      ['jugos', 'helados'],
    ],
    vaina: [['edamame', 'en vaina', 'con vaina', 'sin vaina'], []],
    algarrobina: [['tres leches', 'torta', 'helado', 'postre'], []],
    ramazzotti: [['eros'], []],
    ramazzoti: [['eros'], []],
  },
  baby: ['bebe', 'guagua'],
}

const tokens = (text) => {
  const clean = normalize(text)
  return clean ? clean.split(' ') : []
}

/** La palabra tal cual y su posible singular (galletas → galleta, panes → pan), como KeywordMatcher._candidates. */
const candidates = (word) => [
  word,
  ...(word.length > 3 && word.endsWith('es') ? [word.slice(0, -2)] : []),
  ...(word.length > 2 && word.endsWith('s') ? [word.slice(0, -1)] : []),
]

const contains = (words, phrase) => words.some((_, i) => phrase.every((word, j) => words[i + j] === word))

/** Más palabras primero y, a igualdad, la que aparece antes (KeywordMatcher: _rank, de mayor a menor). */
const byRank = (a, b) => b.words - a.words || a.position - b.position

/**
 * concepts/matcher.py: KeywordMatcher en corto. `entries`: pares [id, palabra clave]; `avoid`: pares [id, frase] que,
 * si el texto las trae, impiden que ese id calce. Devuelve `matches(text)`: lo que calza, sin solapes, de lo más
 * específico a lo menos.
 */
function keywordMatcher(entries, avoid = []) {
  const avoided = new Map()
  for (const [target, phrase] of avoid) {
    const words = tokens(phrase)
    if (words.length) avoided.set(target, [...(avoided.get(target) ?? []), words])
  }
  const byFirst = new Map()
  for (const [target, keyword] of entries) {
    const words = tokens(keyword)
    if (words.length) byFirst.set(words[0], [...(byFirst.get(words[0]) ?? []), { words, target }])
  }
  return (text) => {
    const words = tokens(text)
    const forms = new Set(words.flatMap(candidates))
    const isAvoided = (target) =>
      (avoided.get(target) ?? []).some((phrase) =>
        phrase.length === 1 ? forms.has(phrase[0]) : contains(words, phrase),
      )
    const found = new Map()
    words.forEach((word, i) => {
      for (const candidate of candidates(word))
        for (const keyword of byFirst.get(candidate) ?? []) {
          // Una palabra suelta ya calzó con su plural; una frase, palabra por palabra (KeywordMatcher: _matches_at).
          const fits = keyword.words.length === 1 || keyword.words.every((w, j) => words[i + j] === w)
          if (!fits || isAvoided(keyword.target)) continue
          const match = { target: keyword.target, words: keyword.words.length, position: i }
          const best = found.get(keyword.target)
          if (!best || byRank(match, best) < 0) found.set(keyword.target, match)
        }
    })
    const covered = new Set()
    const result = []
    for (const match of [...found.values()].sort(byRank)) {
      const span = Array.from({ length: match.words }, (_, k) => match.position + k)
      if (span.some((i) => covered.has(i))) continue
      span.forEach((i) => covered.add(i))
      result.push(match)
    }
    return result
  }
}

const compiled = new WeakMap()

/** Los matchers de unas guardias (las de la muestra o, sin ellas, GUARDS), armados una vez. */
function matchersOf(guards) {
  const words = guards ?? GUARDS
  if (!compiled.has(words)) {
    const senses = words.menu_food_senses
    compiled.set(words, {
      catalog: keywordMatcher(words.catalog_alcohol.map((word) => ['alcohol', word])),
      menu: keywordMatcher(
        words.menu_alcohol.map((word) => [Object.hasOwn(senses, word) ? word : 'alcohol', word]),
        Object.entries(senses).flatMap(([word, [phrases]]) => phrases.map((phrase) => [word, phrase])),
      ),
      baby: keywordMatcher(words.baby.map((word) => ['bebe', word])),
      senses,
    })
  }
  return compiled.get(words)
}

/**
 * offers/guards.py: alcohol_in_name. Si el nombre de un producto del catálogo o de un plato dice alcohol; `concept`, el
 * del plato (una "Margarita" con concepto pizza es una pizza). `guards`: `meta.guards` de la muestra (sin ellas, GUARDS).
 */
export function alcoholInName(guards, entityType, name, concept = null) {
  const matchers = matchersOf(guards)
  if (entityType === 'catalog_item') return matchers.catalog(name).length > 0
  if (entityType !== 'menu_item') return false
  return matchers.menu(name).some((m) => m.target === 'alcohol' || !matchers.senses[m.target][1].includes(concept))
}

/** offers/guards.py: baby_in_name. Si el nombre de un producto del catálogo dice bebé (los platos, no). */
export function babyInName(guards, entityType, name) {
  return entityType === 'catalog_item' && matchersOf(guards).baby(name).length > 0
}
