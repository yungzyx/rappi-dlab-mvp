// El panel de la demo sin conexión: personas listas (un historial de pedidos y toques que se siembra en la API
// simulada), "+1 visita" para mover la Home y la lectura de la escalera. Solo existe en "Prototipo MVP.html".
import { MAIN_TILES, SHORTCUTS } from '../../data/home'
import { currentFine, NONE_COMBO, targetStep } from './motor'
import { featuredProduct, offerableProduct } from './offers'
import { PRO_KEY } from '../../state/pro'
import { localStore, saveStored, tabStore } from '../../state/storage'
import { addEvents, readState, writeState } from './state'

const DAY_MS = 86_400_000
const ALL_CATALOG = ['restaurantes', 'turbo', 'supermercado', 'conveniencia', 'mall', 'chocolateria']

/**
 * Las personas del panel: con qué verticales pidió (`orders`, uno cada dos días), qué abrió (`opens`) o qué perfil de
 * gusto tiene. `pro`: si es Rappi Pro (el checkout lo usa). Es coherente con lo que pide, como en los simulados
 * (events/synth.py, PRO_SHARE): quien combina verticales o pide seguido es Pro; la nueva y quien pide en una sola, no.
 */
export function personas(snapshot) {
  // El principal primero (offers/perfiles.toml: `principal`, hoy el mexicano): es con quien arranca la demo.
  const tastes = Object.entries(snapshot.meta.profiles ?? {})
    .filter(([id]) => snapshot.tastes?.[id])
    .sort(([, a], [, b]) => Boolean(b.main) - Boolean(a.main))
    .map(([id, profile]) => ({ id: `gusto-${id}`, label: `${profile.emoji} ${profile.name}`, taste: id, pro: true }))
  return [
    { id: 'nueva', label: 'Nueva (sin historial)', orders: [], pro: false },
    { id: 'restaurantes', label: 'Solo Restaurantes', orders: ['restaurantes'], pro: false },
    { id: 'rest-turbo', label: 'Restaurantes + Turbo', orders: ['restaurantes', 'turbo'], pro: true },
    {
      id: 'rest-turbo-super',
      label: 'Restaurantes + Turbo + Súper',
      orders: ['restaurantes', 'turbo', 'supermercado'],
      pro: true,
    },
    { id: 'todo', label: 'Todo el catálogo', orders: ALL_CATALOG, pro: true },
    {
      id: 'farmacia',
      label: 'Usa mucho Farmacia',
      orders: ['restaurantes', 'farmacia'],
      opens: Array.from({ length: 6 }, () => 'farmacia'),
      pro: false,
    },
    ...tastes,
  ]
}

// La demo arranca, la primera vez en este navegador, con la persona del perfil de gusto principal y su historial
// (`startingHistory`). Se recuerda fuera de `rappi-proto-`: "Borrar mis datos" y "Empezar de cero" dejan a una persona
// nueva, sin volver a sembrarla.
const STARTED_KEY = 'rappi-demo-persona-inicial'

/** La persona con que arranca la demo: la del perfil principal grabado en la muestra (hoy, el mexicano), o null. */
export function startingPersona(snapshot) {
  const [main] = Object.entries(snapshot.meta.profiles ?? {}).find(([id, p]) => p.main && snapshot.tastes?.[id]) ?? []
  return main ? (personas(snapshot).find((p) => p.taste === main) ?? null) : null
}

/**
 * El historial (`{ orders, events }`) con que arranca la demo la primera vez (`POST /session` sin persona), con su marca
 * Rappi Pro; null si ya arrancó antes en este navegador o si la muestra no trae el perfil principal. Sin almacenamiento
 * (modo privado), arranca así en cada pestaña.
 */
export function startingHistory(snapshot, now = Date.now()) {
  const persona = startingPersona(snapshot)
  if (!persona) return null
  try {
    if (localStorage.getItem(STARTED_KEY)) return null
    localStorage.setItem(STARTED_KEY, persona.id)
  } catch {
    // Sin almacenamiento: arranca con ella igual.
  }
  saveStored(PRO_KEY, Boolean(persona.pro))
  return personaHistory(snapshot, persona, now)
}

/** Si la tienda o el restaurante del producto está en la muestra (su "Ver producto" abre algo). */
const inSample = (snapshot, p) =>
  Boolean(
    p.entity_type === 'menu_item' ? snapshot.catalog?.menus?.[p.store_id] : snapshot.catalog?.stores?.[p.store_id],
  )

// offers/engine.py (FOOD_VERTICALS y FOOD_GROUPS de `_typical_first`): en las verticales de comida, primero la comida.
const FOOD_VERTICALS = ['supermercado', 'conveniencia', 'turbo']
const FOOD_GROUPS = ['bebidas', 'snacks', 'dulces', 'despensa', 'frescos', 'comida']
const POPULAR_SECTION = 'Lo más pedido' // catalog/restaurants.py: la sección que el menú suma arriba

/** La sección del menú grabado donde está el plato (la suya, no "Lo más pedido"), o null. */
function sectionOf(snapshot, dish) {
  const sections = snapshot.catalog?.menus?.[dish.store_id]?.sections ?? []
  const found = sections.find(
    (s) => s.name !== POPULAR_SECTION && s.items.some((item) => item.entity_id === dish.entity_id),
  )
  return found?.name ?? null
}

/**
 * Un producto de la muestra para un pedido de esa vertical: el primero con concepto que el agente puede ofrecer, de un
 * concepto que la persona no pidió ya (`used`): si no, dos pedidos del mismo concepto ya serían un "¿Repetimos?". Mejor
 * de una tienda que la muestra tiene. Primero lo que se puede destacar (`featuredProduct`: lo pedido vuelve en
 * "¿Repetimos?") y, en las verticales de comida, la comida: la persona no pide un vaso de cotillón ni un agregado de
 * $1.300.
 */
function sampleOf(snapshot, vertical, used) {
  const { concepts, featured, guards } = snapshot.meta
  const ofVertical = snapshot.pool.filter((p) => p.vertical === vertical && p.concept && p.store_id)
  const fresh = ofVertical.filter((p) => !used.has(p.concept))
  const rank = (p) =>
    (featuredProduct(p, featured, p.entity_type === 'menu_item' ? sectionOf(snapshot, p) : null) ? 0 : 2) +
    (FOOD_VERTICALS.includes(vertical) && !FOOD_GROUPS.includes(concepts[p.concept]?.group) ? 1 : 0)
  const good = fresh.filter((p) => offerableProduct(p, concepts, guards)).sort((a, b) => rank(a) - rank(b))
  const shown = good.filter((p) => inSample(snapshot, p))
  const found = shown[0] ?? good[0] ?? fresh[0] ?? ofVertical[0]
  if (found) used.add(found.concept)
  return found
}

const orderOf = (product, ts, i) => ({
  order_id: `o-demo-${i}`,
  ts,
  vertical: product.vertical,
  mode: 'propuesta',
  lines: [
    {
      entity_type: product.entity_type,
      entity_id: product.entity_id,
      concept_id: product.concept,
      store_id: product.store_id,
      qty: 1,
      unit_price: product.price_value,
    },
  ],
})

/** El historial de una persona (`{ orders, events }`): sus pedidos (uno cada dos días) y toques. */
export function personaHistory(snapshot, persona, now = Date.now()) {
  const used = new Set()
  const plan = persona.taste
    ? snapshot.tastes[persona.taste].seed.map((product, i, all) => [product, (all.length - i) * 2])
    : (persona.orders ?? []).map((vertical, i, all) => [sampleOf(snapshot, vertical, used), (all.length - i) * 2])
  const orders = plan
    .filter(([product]) => product)
    .map(([product, days], i) => orderOf(product, now - days * DAY_MS, i))
  // Un toque por día: la Home pide uso en dos días distintos para moverse (motor.js: MIN_USE_DAYS).
  const events = (persona.opens ?? []).map((vertical, i) => ({
    type: 'vertical_open',
    ts: now - (i + 1) * DAY_MS,
    vertical,
    payload: { desde: 'panel-demo' },
  }))
  return { orders, events }
}

// Lo que la app guarda en este navegador y sobrevive al cambiar de persona: la sesión, el modo y los avisos ya vistos.
const KEEP = ['rappi-proto-user', 'rappi-proto-token', 'rappi-proto-demo-mode', 'rappi-proto-privacy-seen']
const KEEP_TOO = ['rappi-proto-address']

/** Cambia a la persona: borra el carro, los pedidos y lo demás de la app, siembra su historial y vuelve a la Home. */
export function switchPersona(snapshot, persona) {
  const { userId } = readState()
  writeState({ userId, ...personaHistory(snapshot, persona) })
  for (const store of [localStore, tabStore])
    store.clear('rappi-proto-', ['rappi-proto-offline-api', ...KEEP, ...KEEP_TOO])
  // Su marca Rappi Pro (state/pro.js), después de borrar la de la persona anterior.
  saveStored(PRO_KEY, Boolean(persona.pro))
  // Sin el estado de la pantalla en que estaba (useNavigation lo lee antes que el hash): vuelve a la Home.
  window.history.replaceState(null, '', `${window.location.pathname}#/home`)
  window.location.reload()
}

/** El aviso con que la Home vuelve a pedir el orden de sus accesos (screens/home/useVerticalOrder.js). */
export const DEMO_HISTORY_EVENT = 'rappi-demo-history'

/**
 * "+1 visita": un toque al acceso de esa vertical en el prototipo (no en "Rappi hoy"), un día antes que el anterior del
 * panel a esa vertical (la Home pide uso en dos días distintos: motor.js, MIN_USE_DAYS), y la Home se reordena.
 */
export function addVisit(vertical) {
  const before = readState().events.filter((e) => e.vertical === vertical && e.payload?.desde === 'panel-demo').length
  addEvents([{ type: 'vertical_open', ts: Date.now() - before * DAY_MS, vertical, payload: { desde: 'panel-demo' } }])
  window.dispatchEvent(new Event(DEMO_HISTORY_EVENT))
}

/**
 * "Borrar historial": sin pedidos ni toques (la sesión sigue), y la Home vuelve a su orden fijo. La dieta y las alergias
 * se quedan (no son historial); "Pedir por mí" no, porque sus tiendas salen de los pedidos.
 */
export function clearHistory() {
  const { userId, preferences } = readState()
  writeState({ userId, events: [], orders: [], preferences })
  window.dispatchEvent(new Event(DEMO_HISTORY_EVENT))
}

// El nombre de cada vertical en la Home ("mall" → "Rappi Mall"); los servicios, con su marca.
const VISIBLE_NAMES = {
  ...Object.fromEntries([...MAIN_TILES, ...SHORTCUTS].filter((t) => t.vertical).map((t) => [t.vertical, t.label])),
  favor: 'RappiFavor',
  travel: 'RappiTravel',
}
const nameOf = (vertical) => VISIBLE_NAMES[vertical] ?? vertical
const joinNames = (names) => (names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')} y ${names.at(-1)}`)

/** "Hoy: Restaurantes y Turbo → siguiente: Súper": la combinación de la persona y el paso que Mochi propone. */
export function ladderReadout(snapshot, state = readState(), now = Date.now()) {
  const { combos } = snapshot.meta
  const fine = currentFine(combos, state, now)
  if (fine === NONE_COMBO) return `Hoy: sin pedidos → siguiente: la de siempre (${nameOf('supermercado')})`
  const step = targetStep(combos, state, now)
  const next = step ? nameOf(step.vertical) : 'nada más que ofrecer'
  return `Hoy: ${joinNames(fine.split('+').map(nameOf))} → siguiente: ${next}`
}
