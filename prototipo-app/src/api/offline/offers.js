// `POST /agent/offer` sin conexión (offers/engine.py simplificado): la vertical por probar con la escalera del motor,
// «¿Repetimos?», «¿Volvemos a…?», los complementos del carro, del checkout y del próximo pedido, y las respuestas
// grabadas (kits de una ocasión, sin resultado). Todo lo que se ofrece pasa por `offerableProduct` (offers/guards.py).
import { NONE_COMBO, OFFER_BLOCKED_VERTICALS, contractArticles, currentFine, stepSignal, targetStep } from './motor'
import { entityKey } from './snapshot'
import { normalize } from './text'
import {
  BASIS_KINDS,
  LAPSE_MIN_DAYS,
  available,
  lapses,
  localDay,
  offerableVertical,
  orderDays,
  REPLENISH_MIN_ORDERS,
  repeatDue,
  replenishment,
  roundHalfEven,
} from './winback'

// offers/guards.py: palabras de un nombre que dicen alcohol o bebé aunque la tienda no lo marque (palabra entera, con
// su plural). La lista de los platos es más larga en el backend; aquí basta con la del catálogo más los tragos que no
// son también comida. Los que sí («vaina», «algarrobina», «margarita», «sour»…) el backend los libra por la frase o el
// concepto del plato; aquí los cubre el concepto (cócteles y licores no se ofrecen).
const ALCOHOL_WORDS = [
  ...['soju', 'makgeolli', 'umeshu', 'cerveza', 'vino', 'whisky', 'pisco', 'ron', 'vodka', 'gin', 'tequila'],
  ...['licor', 'aperitivo', 'espumante', 'champagne', 'sidra', 'sangria', 'michelada', 'schop', 'piscola'],
  ...['mojito', 'terremoto', 'spritz', 'negroni', 'caipirinha', 'daiquiri', 'daikiri', 'caipiroska'],
  ...['tom collins', 'bloody mary', 'cuba libre', 'kir royal', 'ruso blanco', 'ruso negro', 'cosmopolitan'],
  ...['clavo oxidado'],
]
const MENU_ALCOHOL_WORDS = ['absolut', 'absolute'] // solo en un menú: en el catálogo hay maquillaje «Absolute New York»
const BABY_WORDS = ['bebe', 'guagua']
const wordsIn = (list) => new RegExp(`\\b(?:${list.join('|')})(?:s|es)?\\b`)
const ALCOHOL_NAME = wordsIn(ALCOHOL_WORDS)
const MENU_ALCOHOL_NAME = wordsIn(MENU_ALCOHOL_WORDS)
const BABY_NAME = wordsIn(BABY_WORDS)

/**
 * Si el agente puede proponer este producto por su cuenta: ni +18, ni de Farmacia o Licores, ni de un concepto que no
 * ofrece (alcohol, salud, bebé, sensibles: `meta.concepts[…].offerable`), ni con un nombre que dice alcohol o bebé.
 * Un plato sin concepto o con uno de bebida, tampoco: el backend lee si su descripción nombra alcohol
 * (`alcohol_in_description`) y la muestra no trae descripciones (la API no las da).
 */
export function offerableProduct(product, concepts) {
  if (!product || product.age_restricted) return false
  if (OFFER_BLOCKED_VERTICALS.includes(product.vertical)) return false
  if (product.concept && concepts[product.concept] && !concepts[product.concept].offerable) return false
  const group = product.concept && concepts[product.concept]?.group
  if (product.entity_type === 'menu_item' && (!group || group === 'bebidas')) return false // sin concepto conocido
  const name = normalize(product.name)
  if (ALCOHOL_NAME.test(name)) return false
  if (product.entity_type === 'menu_item') return !MENU_ALCOHOL_NAME.test(name)
  return !BABY_NAME.test(name)
}

/**
 * Si el producto se puede destacar como plato principal (offers/featured.py con `main`, y las reglas de
 * offers/destacado.toml que trae `meta.featured`): con foto y, si es un plato, desde el precio mínimo, de un concepto
 * que es plato y no de una sección de relleno (`section`, la del menú grabado: «Bebidas», «Agregados»). Desde el precio
 * mínimo, la regla de los nombres de relleno del backend no saca nada: aquí no hace falta. La comuna del local no viene
 * en la muestra: los menús grabados son los que mostró la API.
 */
export function featuredProduct(product, featured, section = null) {
  if (!product?.img) return false
  if (product.entity_type !== 'menu_item' || !featured) return true
  const heading = normalize(section).split(' ')
  return (
    !featured.side_sections.some((start) => start.every((word, i) => heading[i] === word)) &&
    (product.price_value ?? 0) >= featured.min_main_price &&
    !featured.not_main.includes(product.concept)
  )
}

const TO_TRY_TEXT = 'Aún no pides en {vertical}: mira estas ofertas.'
const REASON_TO_TRY = 'Porque aún no pides en {vertical}.'
const REASON_SERVICE = {
  favor: 'Porque ya pides en {n} verticales: {servicio} te ayuda con lo que no está en la app.',
  travel: 'Porque ya pides en {n} verticales: con {servicio} planeas el viaje.',
}
const CHECKOUT_TEXT = 'Para completar lo que llevas: {destino}, en {vertical}.'
const NEXT_ORDER_TEXT = 'Para tu próximo pedido: {destino}, en {vertical}.'
const REASON_NEXT = 'Porque pediste {emoji} {name}.'
const REASON_NEXT_ANONYMOUS = 'Para acompañar lo que pediste.'
const fill = (template, values) => template.replace(/\{(\w+)\}/g, (_, key) => values[key])
const clone = (value) => structuredClone(value)

/** La oferta con solo los productos que pasan las guardias; sin productos (y sin ser un servicio), null. */
function guarded(offer, concepts) {
  if (!offer) return null
  const products = offer.products.filter((p) => offerableProduct(p, concepts))
  if (!products.length && !offer.actions?.some((a) => a.service)) return null
  return { ...offer, products }
}

/** «¿Conoces RappiFavor?»: el paso es un servicio, sin productos (engine.py: _service_offer). */
function serviceOffer(snapshot, step) {
  const { combos, services } = snapshot.meta
  const service = services[step.vertical]
  const pitch = service.pitch.trim().replace(/\.$/, '')
  const used = step.current.split('+').filter((m) => !combos.service_keys.includes(m)).length
  return {
    moment: 'vertical_por_probar',
    text: `¿Conoces ${service.name}? ${pitch[0].toUpperCase()}${pitch.slice(1)}.`,
    products: [],
    vertical: null,
    prototype_vertical: null,
    reason: {
      text: fill(REASON_SERVICE[step.vertical], { n: used, servicio: service.name }),
      basis: [stepSignal(combos, step)],
    },
    actions: [{ label: `Abrir ${service.name}`, route: [service.route], service: service.id }],
  }
}

/**
 * La vertical por probar (engine.py: vertical_to_try): el paso de la escalera del motor. Si es un servicio, su oferta;
 * si es una vertical, la oferta real grabada para ese paso (`toTry[vertical]`) con la señal `combinacion` de esta
 * persona. Sin pedidos, la de siempre (el súper, `toTry.usual`).
 */
export function verticalToTry(snapshot, state, now) {
  const { combos, vertical_labels: labels, concepts } = snapshot.meta
  const step = targetStep(combos, state, now)
  if (step && combos.service_keys.includes(step.vertical)) return serviceOffer(snapshot, step)
  if (step && snapshot.toTry[step.vertical]) {
    const offer = clone(snapshot.toTry[step.vertical])
    offer.reason.basis = [stepSignal(combos, step), ...offer.reason.basis.filter((b) => b.kind !== 'combinacion')]
    return guarded(offer, concepts)
  }
  if (currentFine(combos, state, now) !== NONE_COMBO) return null // ya usa todo lo que se ofrece
  const usual = snapshot.toTry.usual && clone(snapshot.toTry.usual)
  if (!usual) return null
  const label = labels[usual.vertical] ?? usual.vertical
  usual.text = TO_TRY_TEXT.replace('{vertical}', label)
  usual.reason = {
    text: contractArticles(REASON_TO_TRY.replace('{vertical}', label)),
    basis: [{ kind: 'sin_pedidos', id: usual.vertical, source: 'contexto' }],
  }
  return guarded(usual, concepts)
}

const REPEAT_TEXT = '¿Repetimos {destino}? Pides {cada}.'
const REASON_REPEAT = 'Porque pides {destino} {cada} y tu último pedido fue {hace}.'
const REPEAT_DEMO_TEXT = '¿Repetimos {destino}? Lo pediste {veces} veces.'
const REASON_REPEAT_DEMO = 'Porque pediste {destino} {veces} veces y tu último pedido fue {hace}.'
const REPEAT_ACTION = 'Ver producto'
const WINBACK_TEXT = '¿Volvemos a {destino}? La última vez que pediste {destino} fue hace {n} días.'
const REASON_WINBACK = 'Porque pedías {destino} {cada} y la última vez fue hace {n} días.'
const WINBACK_VERTICAL_TEXT = '¿Volvemos a {vertical}? Tu último pedido ahí fue hace {n} días.'
const REASON_WINBACK_VERTICAL = 'Porque pediste {veces} veces en {vertical} y tu último pedido ahí fue hace {n} días.'
const every = (days) => (days === 1 ? 'cada día' : `cada ${days} días`)
const daysAgo = (now, ts) => {
  const days = localDay(now) - localDay(ts)
  return days <= 0 ? 'hoy' : days === 1 ? 'ayer' : `hace ${days} días`
}

/** Las líneas de pedidos `propuesta`, de la más reciente a la más antigua, con su pedido. */
const linesNewestFirst = (state) =>
  state.orders
    .filter((o) => o.mode === 'propuesta')
    .sort((a, b) => b.ts - a.ts)
    .flatMap((order) => [...order.lines].reverse().map((line) => ({ line, order })))

/** Lo que se pide en una vertical: platos en restaurantes, productos en las demás. */
const kindOf = (vertical) => (vertical === 'restaurantes' ? 'menu_item' : 'catalog_item')

/**
 * La copia de una entidad en esa vertical (con su tienda y su precio de ahí: una entidad puede estar en varias), si está
 * en la muestra y pasa las guardias (engine.py: _priced_in_vertical y _offerable_products).
 */
const offerableIn = (snapshot, vertical, entity) => {
  const product = snapshot.pool.find(
    (p) =>
      p.vertical === vertical &&
      p.entity_type === entity.entity_type &&
      String(p.entity_id) === String(entity.entity_id),
  )
  return product && offerableProduct(product, snapshot.meta.concepts) ? product : null
}

/** El último producto (o plato) del concepto que compró, si está en la muestra en esa vertical; si no, el primero de la
 * muestra del concepto ahí (engine.py: _repeat_product). */
function repeatProduct(snapshot, state, concept, vertical) {
  const kind = kindOf(vertical)
  const last = linesNewestFirst(state).find(({ line }) => line.concept_id === concept && line.entity_type === kind)
  const bought = last && offerableIn(snapshot, vertical, last.line)
  if (bought) return bought
  const { concepts } = snapshot.meta
  return snapshot.pool.find(
    (p) => p.concept === concept && p.vertical === vertical && p.entity_type === kind && offerableProduct(p, concepts),
  )
}

const repeatReply = (snapshot, moment, { text, why, basis, concept, vertical, product }) => {
  const screen = snapshot.meta.screen_verticals[vertical]
  return {
    moment,
    text,
    products: [product],
    vertical,
    prototype_vertical: screen,
    reason: { ...(concept ? { concept } : {}), text: why, basis },
    actions: [{ label: REPEAT_ACTION, route: [screen], store_id: product.store_id }],
  }
}

/**
 * «¿Repetimos?» (engine.py: repeat_offer): un concepto que la persona pide con ritmo (tres días de compra o más) y le
 * toca entre hace un intervalo y dentro de dos días, el más atrasado primero. La demo no puede esperar días, así que un
 * concepto que todavía no tiene ritmo se repite con dos pedidos `propuesta` en las últimas dos semanas. El producto es
 * el último que compró del concepto.
 */
export function repeatOffer(snapshot, state, now) {
  const { concepts, screen_verticals: screens } = snapshot.meta
  const today = localDay(now)
  const rows = replenishment(state)
  const due = rows
    .filter((row) => repeatDue(row, today))
    .sort((a, b) => a.dueOn - b.dueOn || (a.concept < b.concept ? -1 : 1))
  for (const row of due) {
    const concept = concepts[row.concept]
    if (!concept?.offerable || !offerableVertical(row.vertical, screens)) continue
    const product = repeatProduct(snapshot, state, row.concept, row.vertical)
    if (!product) continue
    const values = { destino: concept.name.toLowerCase(), cada: every(roundHalfEven(row.interval)) }
    return repeatReply(snapshot, 'recompra', {
      text: fill(REPEAT_TEXT, values),
      why: fill(REASON_REPEAT, { ...values, hace: daysAgo(now, row.lastTs) }),
      basis: [{ kind: 'recompra', id: row.concept, source: 'pedidos' }],
      concept: row.concept,
      vertical: row.vertical,
      product,
    })
  }
  // Sin ritmo todavía (menos de tres días de compra: lo pedido en la demo).
  const seen = new Map() // concepto → { orders, recent, last: { line, order } }
  for (const { line, order } of linesNewestFirst(state).reverse()) {
    if (!line.concept_id) continue
    const entry = seen.get(line.concept_id) ?? { orders: new Map(), recent: new Set() }
    entry.orders.set(order.order_id, order)
    if (today - localDay(order.ts) < LAPSE_MIN_DAYS) entry.recent.add(order.order_id)
    entry.last = { line, order }
    seen.set(line.concept_id, entry)
  }
  const recent = [...seen]
    .filter(([, e]) => e.recent.size >= 2 && orderDays([...e.orders.values()]).length < REPLENISH_MIN_ORDERS)
    .sort((a, b) => b[1].last.order.ts - a[1].last.order.ts)
  for (const [conceptId, entry] of recent) {
    const concept = concepts[conceptId]
    const { line, order } = entry.last
    const product = offerableIn(snapshot, order.vertical, line)
    if (!concept?.offerable || !offerableVertical(order.vertical, screens) || !product) continue
    const values = { destino: concept.name.toLowerCase(), veces: entry.recent.size }
    return repeatReply(snapshot, 'recompra', {
      text: fill(REPEAT_DEMO_TEXT, values),
      why: fill(REASON_REPEAT_DEMO, { ...values, hace: daysAgo(now, order.ts) }),
      basis: [{ kind: 'recompra', id: conceptId, source: 'pedidos' }],
      concept: conceptId,
      vertical: order.vertical,
      product,
    })
  }
  return null
}

const WINBACK_VERTICAL_PRODUCTS = 10 // engine.py: lo último que compró en la vertical, para encontrar uno a la venta

/** Lo último que compró en la vertical que está en la muestra, tiene concepto y pasa las guardias (_last_bought_in). */
const lastBoughtIn = (snapshot, state, vertical) =>
  linesNewestFirst(state)
    .filter(({ order, line }) => order.vertical === vertical && line.entity_type === kindOf(vertical))
    .slice(0, WINBACK_VERTICAL_PRODUCTS)
    .map(({ line }) => offerableIn(snapshot, vertical, line))
    .find((product) => product?.concept)

/**
 * «¿Volvemos a…?» (engine.py: winback_offer): la primera invitación que se puede mostrar (winback.js: lapses y
 * available) y tiene producto. De un concepto, el de la recompra; de una vertical, lo último que compró ahí.
 */
export function winbackOffer(snapshot, state, now) {
  const { concepts, vertical_labels: labels } = snapshot.meta
  for (const lapse of available(state, lapses(snapshot, state, now), now)) {
    const product =
      lapse.kind === 'concepto'
        ? repeatProduct(snapshot, state, lapse.key, lapse.vertical)
        : lastBoughtIn(snapshot, state, lapse.vertical)
    if (!product) continue
    if (lapse.kind === 'concepto') {
      const destino = concepts[lapse.key].name.toLowerCase()
      return repeatReply(snapshot, 'volver', {
        text: fill(WINBACK_TEXT, { destino, n: lapse.days }),
        why: fill(REASON_WINBACK, { destino, cada: every(lapse.interval), n: lapse.days }),
        basis: [{ kind: BASIS_KINDS.concepto, id: lapse.key, source: 'pedidos' }],
        concept: lapse.key,
        vertical: lapse.vertical,
        product,
      })
    }
    const vertical = labels[lapse.vertical] ?? lapse.vertical
    return repeatReply(snapshot, 'volver', {
      text: contractArticles(fill(WINBACK_VERTICAL_TEXT, { vertical, n: lapse.days })),
      why: fill(REASON_WINBACK_VERTICAL, { veces: lapse.orders, vertical, n: lapse.days }),
      basis: [{ kind: BASIS_KINDS.vertical, id: lapse.vertical, source: 'pedidos' }],
      vertical: lapse.vertical,
      product,
    })
  }
  return null
}

/**
 * Si a la persona le toca primero el segundo complemento de un concepto (agent/tools.py: _takes_second): a la mitad de
 * las personas, siempre la misma para un mismo origen. El backend usa md5 de la persona y el concepto; aquí basta un
 * hash corto (FNV-1a, su bit alto), porque la persona de la demo no existe en el backend.
 */
function takesSecond(userId, concept) {
  let hash = 0x811c9dc5
  for (const char of `${userId}|${concept}`) hash = Math.imul(hash ^ char.codePointAt(0), 0x01000193) >>> 0
  return hash >>> 31 === 1
}

/**
 * La oferta `carrito` grabada para un concepto de origen, la de esta persona: la de siempre o, si los dos primeros
 * complementos pesan parecido y le toca (`takesSecond`), la del segundo (`complementsAlt`, grabada con una persona de
 * prueba a la que le tocaba).
 */
export function complementOf(snapshot, concept, userId) {
  const second = snapshot.complementsAlt?.[concept]
  return second && userId && takesSecond(userId, concept) ? second : snapshot.complements[concept]
}

/**
 * El complemento de lo que hay (engine.py: complement): la oferta `carrito` real grabada para el concepto de origen
 * (la de esta persona: `complementOf`), sin lo que ya lleva. En `checkout` y `proximo_pedido` cambia el texto (y en el
 * próximo pedido, el porqué).
 */
export function complementOffer(snapshot, moment, entities, userId) {
  const { concepts, vertical_labels: labels } = snapshot.meta
  const have = new Set(entities.map((e) => entityKey(e.entity_type, e.entity_id)))
  const sources = [
    ...new Set(
      entities.map((e) => snapshot.byEntity.get(entityKey(e.entity_type, e.entity_id))?.concept).filter(Boolean),
    ),
  ]
  for (const source of sources) {
    const recorded = complementOf(snapshot, source, userId)
    if (!recorded || sources.includes(recorded.reason?.concept)) continue
    const offer = guarded(
      {
        ...clone(recorded),
        products: recorded.products.filter((p) => !have.has(entityKey(p.entity_type, p.entity_id))),
      },
      concepts,
    )
    if (!offer) continue
    if (moment === 'carrito') return offer
    const target = concepts[offer.reason.concept]
    const values = { destino: target?.name.toLowerCase() ?? '', vertical: labels[offer.vertical] ?? offer.vertical }
    offer.moment = moment
    offer.text = fill(moment === 'checkout' ? CHECKOUT_TEXT : NEXT_ORDER_TEXT, values)
    if (moment === 'proximo_pedido') {
      const origin = concepts[source]
      offer.reason = origin?.offerable
        ? {
            ...offer.reason,
            text: fill(REASON_NEXT, { emoji: origin.emoji, name: origin.name.toLowerCase() }),
            basis: [{ kind: 'pedido', id: source, source: 'contexto' }],
          }
        : { ...offer.reason, text: REASON_NEXT_ANONYMOUS, basis: [] }
    }
    return offer
  }
  return null
}

/** La oferta de un momento, o null (204) si no hay nada que ofrecer. */
export function makeOffer(snapshot, state, now, { moment, context = {} }) {
  switch (moment) {
    case 'vertical_por_probar':
      return verticalToTry(snapshot, state, now)
    case 'recompra':
      return repeatOffer(snapshot, state, now)
    case 'volver':
      return winbackOffer(snapshot, state, now)
    case 'carrito':
      return complementOffer(snapshot, moment, context.product ? [context.product] : (context.cart ?? []), state.userId)
    case 'checkout':
      return complementOffer(snapshot, moment, context.cart ?? [], state.userId)
    case 'proximo_pedido':
      return complementOffer(snapshot, moment, context.items ?? [], state.userId)
    case 'plan':
      return guardedPlan(snapshot.planOffers[context.occasion])
    case 'sin_resultado':
      return snapshot.noResult[normalize(context.query)] ?? null
    default:
      return null
  }
}

/** Un kit grabado ya pasó las guardias del backend (el de un carrete puede traer alcohol, con su marca +18). */
const guardedPlan = (offer) => (offer ? clone(offer) : null)
