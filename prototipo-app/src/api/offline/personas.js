// El panel de la demo sin conexión: personas listas (un historial de pedidos y toques que se siembra en la API
// simulada), «+1 visita» para mover la Home y la lectura de la escalera. Solo existe en «Prototipo MVP.html».
import { currentFine, NONE_COMBO, targetStep } from './motor'
import { featuredProduct, offerableProduct } from './offers'
import { addEvents, readState, writeState } from './state'

const DAY_MS = 86_400_000
const ALL_CATALOG = ['restaurantes', 'turbo', 'supermercado', 'conveniencia', 'mall', 'chocolateria']

// «¿Volvemos a…?» necesita semanas de historial: un plato pedido cada 7 días hasta hace 24 (y pedidos recientes en
// otras verticales), o Turbo en 3 días hasta hace 40 mientras sigue pidiendo en restaurantes (offers/winback.py).
const HABIT_CONCEPTS = ['sushi', 'pizza', 'hamburguesa', 'empanadas']
const STOPPED_DISH = [
  ...[45, 38, 31, 24].map((days) => ['restaurantes', days, 'habito']),
  ['turbo', 3],
  ['supermercado', 1],
]
const STOPPED_TURBO = [
  ['turbo', 60],
  ['turbo', 50],
  ['turbo', 40],
  ['restaurantes', 6],
  ['restaurantes', 2],
]

/**
 * Las personas del panel: con qué verticales pidió (`orders`, uno cada dos días, o `plan`: `[vertical, hace cuántos
 * días, clave]`, donde la misma clave repite el producto), qué abrió (`opens`) o qué perfil de gusto tiene.
 */
export function personas(snapshot) {
  const tastes = Object.entries(snapshot.meta.profiles ?? {})
    .filter(([id]) => snapshot.tastes?.[id])
    .map(([id, profile]) => ({ id: `gusto-${id}`, label: `${profile.emoji} ${profile.name}`, taste: id }))
  return [
    { id: 'nueva', label: 'Nueva (sin historial)', orders: [] },
    { id: 'restaurantes', label: 'Solo Restaurantes', orders: ['restaurantes'] },
    { id: 'rest-turbo', label: 'Restaurantes + Turbo', orders: ['restaurantes', 'turbo'] },
    {
      id: 'rest-turbo-super',
      label: 'Restaurantes + Turbo + Súper',
      orders: ['restaurantes', 'turbo', 'supermercado'],
    },
    { id: 'todo', label: 'Todo el catálogo', orders: ALL_CATALOG },
    {
      id: 'farmacia',
      label: 'Usa mucho Farmacia',
      orders: ['restaurantes', 'farmacia'],
      opens: Array.from({ length: 6 }, () => 'farmacia'),
    },
    { id: 'volver-plato', label: 'Dejó de pedir su plato de siempre', plan: STOPPED_DISH, habit: HABIT_CONCEPTS },
    { id: 'volver-turbo', label: 'Dejó Turbo hace 40 días', plan: STOPPED_TURBO },
    ...tastes,
  ]
}

/** Si la tienda o el restaurante del producto está en la muestra (su «Ver producto» abre algo). */
const inSample = (snapshot, p) =>
  Boolean(
    p.entity_type === 'menu_item' ? snapshot.catalog?.menus?.[p.store_id] : snapshot.catalog?.stores?.[p.store_id],
  )

// offers/engine.py (FOOD_VERTICALS y FOOD_GROUPS de `_typical_first`): en las verticales de comida, primero la comida.
const FOOD_VERTICALS = ['supermercado', 'conveniencia', 'turbo']
const FOOD_GROUPS = ['bebidas', 'snacks', 'dulces', 'despensa', 'frescos', 'comida']
const POPULAR_SECTION = 'Lo más pedido' // catalog/restaurants.py: la sección que el menú suma arriba

/** La sección del menú grabado donde está el plato (la suya, no «Lo más pedido»), o null. */
function sectionOf(snapshot, dish) {
  const sections = snapshot.catalog?.menus?.[dish.store_id]?.sections ?? []
  const found = sections.find(
    (s) => s.name !== POPULAR_SECTION && s.items.some((item) => item.entity_id === dish.entity_id),
  )
  return found?.name ?? null
}

/**
 * Un producto de la muestra para un pedido de esa vertical: el primero con concepto que el agente puede ofrecer, de un
 * concepto que la persona no pidió ya (`used`): si no, dos pedidos del mismo concepto ya serían un «¿Repetimos?». Mejor
 * de una tienda que la muestra tiene, y de los conceptos de `prefer` si hay. Primero lo que se puede destacar
 * (`featuredProduct`: lo pedido vuelve en «¿Repetimos?» y «¿Volvemos a…?») y, en las verticales de comida, la comida:
 * la persona no pide un vaso de cotillón ni un agregado de $1.300.
 */
function sampleOf(snapshot, vertical, used, prefer = []) {
  const { concepts, featured } = snapshot.meta
  const ofVertical = snapshot.pool.filter((p) => p.vertical === vertical && p.concept && p.store_id)
  const fresh = ofVertical.filter((p) => !used.has(p.concept))
  const rank = (p) =>
    (featuredProduct(p, featured, p.entity_type === 'menu_item' ? sectionOf(snapshot, p) : null) ? 0 : 2) +
    (FOOD_VERTICALS.includes(vertical) && !FOOD_GROUPS.includes(concepts[p.concept]?.group) ? 1 : 0)
  const good = fresh.filter((p) => offerableProduct(p, concepts)).sort((a, b) => rank(a) - rank(b))
  const shown = good.filter((p) => inSample(snapshot, p))
  const found =
    prefer.map((c) => shown.find((p) => p.concept === c)).find(Boolean) ??
    shown[0] ??
    good[0] ??
    fresh[0] ??
    ofVertical[0]
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

/** El historial de una persona (`{ orders, events }`): sus pedidos (uno cada dos días, salvo con `plan`) y toques. */
export function personaHistory(snapshot, persona, now = Date.now()) {
  const used = new Set()
  const byKey = new Map()
  const plan = persona.taste
    ? snapshot.tastes[persona.taste].seed.map((product, i, all) => [product, (all.length - i) * 2])
    : (persona.plan ?? (persona.orders ?? []).map((vertical, i, all) => [vertical, (all.length - i) * 2])).map(
        ([vertical, days, key]) => {
          if (key && !byKey.has(key)) byKey.set(key, sampleOf(snapshot, vertical, used, persona.habit))
          return [key ? byKey.get(key) : sampleOf(snapshot, vertical, used), days]
        },
      )
  const orders = plan
    .filter(([product]) => product)
    .map(([product, days], i) => orderOf(product, now - days * DAY_MS, i))
  const events = (persona.opens ?? []).map((vertical, i) => ({
    type: 'vertical_open',
    ts: now - (i + 1) * 3_600_000,
    vertical,
    payload: { desde: 'panel-demo' },
  }))
  return { orders, events }
}

// Lo que la app guarda en este navegador y sobrevive al cambiar de persona: la sesión, el modo y los avisos ya vistos.
const KEEP = ['rappi-proto-user', 'rappi-proto-token', 'rappi-proto-demo-mode', 'rappi-proto-privacy-seen']
const KEEP_TOO = ['rappi-proto-guia-vista', 'rappi-proto-address']

/** Cambia a la persona: borra el carro, los pedidos y lo demás de la app, siembra su historial y vuelve a la Home. */
export function switchPersona(snapshot, persona) {
  const { userId } = readState()
  writeState({ userId, ...personaHistory(snapshot, persona) })
  for (const storage of [localStorage, sessionStorage]) {
    try {
      for (const key of Object.keys(storage))
        if (
          key.startsWith('rappi-proto-') &&
          key !== 'rappi-proto-offline-api' &&
          ![...KEEP, ...KEEP_TOO].includes(key)
        )
          storage.removeItem(key)
    } catch {
      // Sin almacenamiento no hay nada que borrar.
    }
  }
  // Sin el estado de la pantalla en que estaba (useNavigation lo lee antes que el hash): vuelve a la Home.
  window.history.replaceState(null, '', `${window.location.pathname}#/home`)
  window.location.reload()
}

/** El aviso con que la Home vuelve a pedir el orden de sus accesos (screens/home/useVerticalOrder.js). */
export const DEMO_HISTORY_EVENT = 'rappi-demo-history'

/** «+1 visita»: un toque al acceso de esa vertical en el prototipo (no en «Rappi hoy»), y la Home se reordena. */
export function addVisit(vertical) {
  addEvents([{ type: 'vertical_open', ts: Date.now(), vertical, payload: { desde: 'panel-demo' } }])
  window.dispatchEvent(new Event(DEMO_HISTORY_EVENT))
}

/** «Borrar historial»: sin pedidos ni toques (la sesión sigue), y la Home vuelve a su orden fijo. */
export function clearHistory() {
  const { userId } = readState()
  writeState({ userId, events: [], orders: [] })
  window.dispatchEvent(new Event(DEMO_HISTORY_EVENT))
}

const SERVICE_NAMES = { favor: 'RappiFavor', travel: 'RappiTravel' }

/** «Hoy: restaurantes+turbo → siguiente: supermercado»: la combinación de la persona y el paso que Mochi propone. */
export function ladderReadout(snapshot, state = readState(), now = Date.now()) {
  const { combos } = snapshot.meta
  const fine = currentFine(combos, state, now)
  if (fine === NONE_COMBO) return 'Hoy: sin pedidos → siguiente: la de siempre (supermercado)'
  const step = targetStep(combos, state, now)
  const next = step ? (SERVICE_NAMES[step.vertical] ?? step.vertical) : 'nada más que ofrecer'
  return `Hoy: ${fine} → siguiente: ${next}`
}
