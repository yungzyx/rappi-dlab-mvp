// @vitest-environment node
import { readFileSync } from 'node:fs'
import { describe, expect, test } from 'vitest'
import { LIMITS } from './autonomy'
import { DAILY_CROSS_CAP, INTEREST_HALF_LIFE_DAYS, INTEREST_WEIGHTS, SENSITIVE_CONCEPTS } from './index'
import { DEFAULT_ORDER, MIN_USE_DAYS, OWN_CONCEPT_GROUPS } from './motor'
import { PET_SPECIES } from './offers'

// Las constantes que la demo sin conexión copia a mano del backend tienen que ser las de allá: se leen los .py, sin
// Python (como guards.test.js). winback.js y motor.js no exportan todas las suyas: se leen también de su código.
const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')
const backend = (path) => read(`../../../../rappi-ia/src/rappi_ia/${path}`)
const STORE_PY = backend('events/store.py')
const AGENT_PY = backend('agent/rappi_agent.py')
const AUTONOMY_PY = backend('offers/autonomy.py')
const WINBACK_PY = backend('offers/winback.py')
const MODEL_PY = backend('motor/model.py')
const HOME_PY = backend('motor/home.py')
const COMPLEMENTS_TOML = backend('concepts/complements.toml')
const TAXONOMY_TOML = backend('concepts/taxonomy.toml')
const WINBACK_JS = read('./winback.js')
const MOTOR_JS = read('./motor.js')

const number = (text) => Number(text.replace(/_/g, ''))

/** `NAME = 14` (con o sin comentario) en un .py o `const NAME = 14` en un .js. */
function constant(source, name) {
  const found = source.match(new RegExp(`^(?:export )?(?:const )?${name} = ([\\d_.]+)\\b`, 'm'))
  if (!found) throw new Error(`No encontré ${name}`)
  return number(found[1])
}

/** Un diccionario de números de un .py (`NAME = {` hasta el `}` al comienzo de una línea). */
function pyWeights(source, name) {
  const block = source.match(new RegExp(`^${name} = \\{([\\s\\S]*?)^\\}`, 'm'))
  if (!block) throw new Error(`No encontré ${name}`)
  return Object.fromEntries(
    [...block[1].matchAll(/"(\w+)":\s*([\d_.]+)/g)].map(([, key, value]) => [key, number(value)]),
  )
}

/** Un objeto de números en una línea de un .js (`const NAME = { order: 5, … }`). */
function jsWeights(source, name) {
  const block = source.match(new RegExp(`^(?:export )?const ${name} = \\{([^}]*)\\}`, 'm'))
  if (!block) throw new Error(`No encontré ${name}`)
  return Object.fromEntries([...block[1].matchAll(/(\w+):\s*([\d_.]+)/g)].map(([, key, value]) => [key, number(value)]))
}

describe('la demo sin conexión tiene las constantes del backend', () => {
  test('las especies de mascota (concepts/complements.toml: [especies])', () => {
    const list = (text) => [...text.matchAll(/"([^"]+)"/g)].map(([, word]) => word)
    const species = Object.fromEntries(
      [...COMPLEMENTS_TOML.matchAll(/^\[especies\.(\w+)\]\nconceptos = \[(.*)\]\npalabras = \[(.*)\]$/gm)].map(
        ([, id, concepts, words]) => [id, { concepts: list(concepts), words: list(words) }],
      ),
    )
    expect(PET_SPECIES).toEqual(species)
  })

  test('el perfil de intereses (events/store.py: WEIGHTS y HALF_LIFE_DAYS), salvo "chat" (el nombre anterior de `ask`, que la app ya no manda)', () => {
    const { chat: _chat, ...weights } = pyWeights(STORE_PY, 'WEIGHTS')
    expect(INTEREST_WEIGHTS).toEqual(weights)
    expect(INTEREST_HALF_LIFE_DAYS).toBe(constant(STORE_PY, 'HALF_LIFE_DAYS'))
  })

  test('los conceptos sensibles, que no entran al perfil de intereses (concepts/taxonomy.toml: sensitive = true)', () => {
    const sensitive = TAXONOMY_TOML.split(/^\[\[concept\]\]$/m)
      .filter((block) => /^sensitive = true$/m.test(block))
      .map((block) => block.match(/^id = "([^"]+)"$/m)[1])
    expect([...SENSITIVE_CONCEPTS].sort()).toEqual(sensitive.sort())
  })

  test('el tope diario de sugerencias cruzadas (agent/rappi_agent.py: DAILY_CROSS_CAP)', () => {
    expect(DAILY_CROSS_CAP).toBe(constant(AGENT_PY, 'DAILY_CROSS_CAP'))
  })

  test('los límites de "Pedir por mí" (offers/autonomy.py)', () => {
    const [, min, max] = AUTONOMY_PY.match(/^MIN_TOTAL, MAX_TOTAL = ([\d_]+), ([\d_]+)/m)
    expect(LIMITS).toEqual({
      min: number(min),
      max: number(max),
      suggested: constant(AUTONOMY_PY, 'DEFAULT_TOTAL'),
      stores: constant(AUTONOMY_PY, 'MAX_STORES'),
    })
  })

  test('la recompra y "volver" (offers/winback.py y motor/model.py)', () => {
    for (const name of [
      'REPEAT_AHEAD_DAYS',
      'LAPSE_MIN_DAYS',
      'LAPSE_MAX_DAYS',
      'VERTICAL_LAPSE_DAYS',
      'VERTICAL_MIN_DAYS',
      'COOLDOWN_DAYS',
      'MAX_DISMISSALS',
      'PAUSE_DAYS',
    ])
      expect([name, constant(WINBACK_JS, name)]).toEqual([name, constant(WINBACK_PY, name)])
    expect(constant(WINBACK_JS, 'LOW_RATING')).toBe(constant(STORE_PY, 'LOW_RATING'))
    for (const name of ['REPLENISH_MIN_ORDERS', 'REPLENISH_MAX_CV'])
      expect([name, constant(WINBACK_JS, name)]).toEqual([name, constant(MODEL_PY, name)])
  })

  test('la afinidad y el orden por defecto del motor (motor/model.py)', () => {
    expect(jsWeights(MOTOR_JS, 'AFFINITY_WEIGHTS')).toEqual(pyWeights(MODEL_PY, 'AFFINITY_WEIGHTS'))
    for (const name of ['AFFINITY_HALF_LIFE_DAYS', 'AFFINITY_WINDOW_DAYS'])
      expect([name, constant(MOTOR_JS, name)]).toEqual([name, constant(MODEL_PY, name)])
    const order = MODEL_PY.match(/^DEFAULT_ORDER = \(([^)]*)\)/m)[1]
    expect(DEFAULT_ORDER).toEqual([...order.matchAll(/"([^"]+)"/g)].map((m) => m[1]))
  })

  test('el uso mínimo de la Home y lo propio de Farmacia y Licores (motor/home.py)', () => {
    expect(MIN_USE_DAYS).toBe(constant(HOME_PY, 'MIN_USE_DAYS'))
    const groups = HOME_PY.match(/^OWN_CONCEPT_GROUPS = \{([^}]*)\}/m)[1]
    expect(OWN_CONCEPT_GROUPS).toEqual(
      Object.fromEntries([...groups.matchAll(/"(\w+)": "(\w+)"/g)].map((m) => m.slice(1))),
    )
  })

  test('los demás números copiados a mano (escalera, catálogo, ofertas, búsqueda y conversación)', () => {
    const pairs = [
      // [archivo de la demo, su nombre, archivo del backend, su nombre]
      ['./motor.js', 'CURRENT_COMBO_DAYS', 'motor/predict.py', 'CURRENT_COMBO_DAYS'],
      ['./motor.js', 'LAPSED_COMBO_DAYS', 'motor/predict.py', 'LAPSED_COMBO_DAYS'],
      ['./catalog.js', 'TOP_MIN_RATING', 'catalog/restaurants.py', 'TOP_MIN_RATING'],
      ['./catalog.js', 'TOP_MIN_REVIEWS', 'catalog/restaurants.py', 'TOP_MIN_REVIEWS'],
      ['./offers.js', 'ONTOP_WINDOW_MIN', 'offers/engine.py', 'ONTOP_WINDOW_MIN'],
      ['./offers.js', 'WINBACK_VERTICAL_PRODUCTS', 'offers/engine.py', 'WINBACK_VERTICAL_PRODUCTS'],
      ['./offers.js', 'MIN_LADDER_STEPS', 'offers/engine.py', 'MIN_LADDER_STEPS'],
      ['./search.js', 'GROUPED_LIMIT', 'api/app.py', 'GROUPED_SEARCH_LIMIT'],
      ['./conversation.js', 'MAX_SHOWN_IDS', 'agent/rappi_agent.py', 'MAX_SHOWN_IDS'],
      ['./conversation.js', 'MIN_NAMED', 'agent/rappi_agent.py', 'MIN_SHOWN'],
    ]
    for (const [js, name, py, pyName] of pairs)
      expect([name, constant(read(js), name)]).toEqual([name, constant(backend(py), pyName)])
    // api/app.py: SCHEDULE_AHEAD (en días) y index.js: SCHEDULE_AHEAD_MS (en días por DAY_MS).
    const days = backend('api/app.py').match(/^SCHEDULE_AHEAD = timedelta\(days=(\d+)\)/m)[1]
    expect(read('./index.js').match(/^const SCHEDULE_AHEAD_MS = (\d+) \* DAY_MS$/m)[1]).toBe(days)
  })
})
