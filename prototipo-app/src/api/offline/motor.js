// El motor multivertical, simplificado para la demo sin conexión: la afinidad propia (motor/model.py), el orden de
// los accesos de la Home (motor/home.py) y el paso de la escalera fina (motor/combos.py y motor/predict.py). Lo que
// se aprende de la población (transiciones, popularidad, retención aprendida) no está: solo la persona y la tabla de
// Rappi con el supuesto del rendimiento decreciente (combos.toml, que llega en la muestra como `meta.combos`).

const DAY_MS = 86_400_000

// motor/model.py
export const DEFAULT_ORDER = [
  ...['restaurantes', 'turbo', 'supermercado', 'farmacia', 'mall', 'licores', 'conveniencia', 'chocolateria'],
]
const AFFINITY_WEIGHTS = { order: 5, cart_add: 1.5, vertical_open: 1, view_store: 1, search: 0.5, view_item: 0.3 }
const AFFINITY_HALF_LIFE_DAYS = 30
const AFFINITY_WINDOW_DAYS = 180
// motor/home.py
export const HOME_FIXED = ['restaurantes', 'turbo']
export const HOME_ORDERABLE = ['supermercado', 'farmacia', 'mall', 'licores', 'conveniencia', 'chocolateria']
const REASON_ORDERS = 'Porque pides seguido en {vertical}.'
const REASON_VISITS = 'Porque entras seguido a {vertical}.'
// motor/predict.py
const CURRENT_COMBO_DAYS = 30
const LAPSED_COMBO_DAYS = 90
export const NONE_COMBO = 'ninguna'
const SERVICE_COMBO = 'favor'
// offers/guards.py: las verticales de las que el agente no propone por su cuenta.
export const OFFER_BLOCKED_VERTICALS = ['farmacia', 'licores']

/** «de el súper» → «del súper» y «a el súper» → «al súper» (text.py: contract_articles). */
export const contractArticles = (text) => text.replace(/\b(de|a) el\b/g, (_, word) => (word === 'de' ? 'del' : 'al'))

const isProposal = (order) => order.mode === 'propuesta'
const isTaught = (event) => event.payload?.mode !== 'actual' // lo hecho en «Rappi hoy» no enseña

/** Las señales de afinidad (motor/data.py: load_signals): sus pedidos `propuesta` y sus eventos con vertical. */
export function signalsOf(state) {
  return [
    ...state.orders.filter(isProposal).map((o) => ({ ts: o.ts, kind: 'order', vertical: o.vertical })),
    ...state.events
      .filter((e) => e.vertical && e.type in AFFINITY_WEIGHTS && e.type !== 'order' && isTaught(e))
      .map((e) => ({ ts: e.ts, kind: e.type, vertical: e.vertical })),
  ]
}

/** vertical → Σ peso × 0,5^(días/30), en los últimos 180 días (model.py: affinity). */
export function affinity(signals, now) {
  const scores = {}
  for (const s of signals) {
    const age = (now - s.ts) / DAY_MS
    if (age < 0 || age > AFFINITY_WINDOW_DAYS) continue
    scores[s.vertical] = (scores[s.vertical] ?? 0) + AFFINITY_WEIGHTS[s.kind] * 0.5 ** (age / AFFINITY_HALF_LIFE_DAYS)
  }
  return scores
}

/** Los 8 verticales por afinidad normalizada (model.py: rank_verticals, sin transiciones ni popularidad). */
export function rankVerticals(aff) {
  const total = Object.values(aff).reduce((a, b) => a + b, 0)
  return DEFAULT_ORDER.map((vertical) => ({ vertical, score: total ? (aff[vertical] ?? 0) / total : 0 })).sort(
    (a, b) => b.score - a.score || DEFAULT_ORDER.indexOf(a.vertical) - DEFAULT_ORDER.indexOf(b.vertical),
  )
}

/** `GET /profile/{id}/verticales` (motor/home.py: home_verticals). `labels`: nombres de las verticales. */
export function homeVerticals(state, now, labels) {
  const ranked = rankVerticals(affinity(signalsOf(state), now))
  const used = ranked.filter((s) => HOME_ORDERABLE.includes(s.vertical) && s.score > 0).map((s) => s.vertical)
  const ids = [...used, ...HOME_ORDERABLE.filter((v) => !used.includes(v))]
  const score = Object.fromEntries(ranked.map((s) => [s.vertical, s.score]))
  const order = ids.map((id) => ({ id, score: Math.round(score[id] * 10_000) / 10_000, reason: null }))
  if (used.length) {
    const ordered = state.orders.some((o) => isProposal(o) && o.vertical === used[0])
    const template = ordered ? REASON_ORDERS : REASON_VISITS
    order[0].reason = {
      text: contractArticles(template.replace('{vertical}', labels[used[0]] ?? used[0])),
      basis: [{ kind: 'afinidad_vertical', id: used[0], source: 'eventos' }],
    }
  }
  return { fixed: HOME_FIXED, order, personalized: used.length > 0 }
}

// ── La escalera fina (motor/combos.py) ───────────────────────────────────────

const groupOf = (combos, vertical) => Object.keys(combos.groups).find((g) => combos.groups[g].includes(vertical))
const isService = (combos, member) => combos.service_keys.includes(member)
const membersOf = (fine) => (fine === NONE_COMBO ? [] : fine.split('+'))

/** El nombre de una combinación fina: verticales y servicios en el orden de `fine_order`, unidos por «+». */
export function fineKey(combos, members) {
  const present = new Set(members)
  return combos.fine_order.filter((m) => present.has(m)).join('+') || NONE_COMBO
}

/** La combinación gruesa (rest, turbo, retail) de unos verticales del catálogo. */
function coarseKey(combos, verticals) {
  const groups = new Set(verticals.map((v) => groupOf(combos, v)))
  return (
    Object.keys(combos.groups)
      .filter((g) => groups.has(g))
      .join('+') || NONE_COMBO
  )
}

const coarseOfFine = (combos, fine) =>
  coarseKey(
    combos,
    membersOf(fine).filter((m) => !isService(combos, m)),
  )

/** Π (1 − f) del supuesto propio: la j-ésima vertical de un grupo (j ≥ 2) y cada servicio (fine_churn_factor). */
export function churnFactor(combos, fine) {
  const { reduction_base: base, decay, service } = combos.diminishing
  const members = membersOf(fine)
  const counts = {}
  for (const m of members) if (!isService(combos, m)) counts[groupOf(combos, m)] = (counts[groupOf(combos, m)] ?? 0) + 1
  let factor = 1
  for (const k of Object.values(counts)) for (let j = 2; j <= k; j += 1) factor *= 1 - base * decay ** (j - 2)
  const services = members.filter((m) => isService(combos, m))
  if (services.length === members.length && services.includes(SERVICE_COMBO))
    services.splice(services.indexOf(SERVICE_COMBO), 1)
  return factor * (1 - service) ** services.length
}

/** `[retención esperada, ¿pesó el supuesto?]` de una combinación fina, sin lo aprendido (_fine_expectation). */
export function fineExpectation(combos, fine) {
  const members = membersOf(fine)
  const catalog = members.filter((m) => !isService(combos, m))
  let prior = null
  if (catalog.length) prior = combos.retention[coarseKey(combos, catalog)] ?? null
  else if (members.includes(SERVICE_COMBO)) prior = combos.retention[SERVICE_COMBO] ?? null
  else if (!members.length) prior = combos.retention[NONE_COMBO] ?? null
  const factor = churnFactor(combos, fine)
  if (prior === null || factor >= 1) return [prior, false]
  const reduced = 1 - (1 - prior) * factor
  return [reduced, reduced > prior]
}

/**
 * El paso que más retención esperada suma (next_fine_step): `candidates` en el orden de preferencia de la persona,
 * que desempata; una vertical del catálogo que suma algo va antes que cualquier servicio; Farmacia y Licores nunca.
 * `{ vertical, current, target, gain, usedAssumption }` o null.
 */
export function nextFineStep(combos, fine, candidates) {
  if (fine === NONE_COMBO) return null
  const [current, currentUsed] = fineExpectation(combos, fine)
  if (current === null) return null
  const have = new Set(membersOf(fine))
  const group = coarseOfFine(combos, fine)
  const best = {}
  for (const vertical of candidates) {
    if (have.has(vertical) || combos.own_signals_only.includes(vertical)) continue
    const target = fineKey(combos, [...have, vertical])
    let expected, targetUsed
    if (coarseOfFine(combos, target) === group) {
      const ratio = churnFactor(combos, target) / churnFactor(combos, fine)
      ;[expected, targetUsed] = [1 - (1 - current) * ratio, ratio < 1]
    } else {
      ;[expected, targetUsed] = fineExpectation(combos, target)
    }
    if (expected === null || expected <= current) continue
    const kind = isService(combos, vertical) ? 'service' : 'catalog'
    const step = {
      vertical,
      current: fine,
      target,
      gain: expected - current,
      usedAssumption: currentUsed || targetUsed,
    }
    if (!best[kind] || step.gain > best[kind].gain) best[kind] = step
  }
  return best.catalog ?? best.service ?? null
}

/**
 * La combinación fina de la persona (predict.py: current_fine): las verticales de sus pedidos `propuesta` de los
 * últimos 30 días (90 si no pidió en 30) y los servicios que abrió en ese tiempo (`service_opened`, salvo en «Rappi
 * hoy»). Sin pedidos, «ninguna».
 */
export function currentFine(combos, state, now) {
  const byPayload = Object.fromEntries(Object.entries(combos.services).map(([key, payload]) => [payload, key]))
  for (const days of [CURRENT_COMBO_DAYS, LAPSED_COMBO_DAYS]) {
    const inWindow = (ts) => ts > now - days * DAY_MS && ts <= now
    const verticals = state.orders.filter((o) => isProposal(o) && inWindow(o.ts)).map((o) => o.vertical)
    if (!verticals.length) continue
    const services = state.events
      .filter((e) => e.type === 'service_opened' && inWindow(e.ts) && isTaught(e))
      .map((e) => byPayload[e.payload?.servicio])
      .filter(Boolean)
    return fineKey(combos, [...verticals, ...services])
  }
  return NONE_COMBO
}

/** El paso de la persona (predict.py: target_step): candidatos en su orden de afinidad y al final los servicios. */
export function targetStep(combos, state, now) {
  const fine = currentFine(combos, state, now)
  if (fine === NONE_COMBO) return null
  const ranked = rankVerticals(affinity(signalsOf(state), now)).map((s) => s.vertical)
  const candidates = [
    ...ranked.filter((v) => !OFFER_BLOCKED_VERTICALS.includes(v) && !combos.own_signals_only.includes(v)),
    ...combos.service_keys,
  ]
  return nextFineStep(combos, fine, candidates)
}

/** La señal `combinacion` de la `basis` (predict.py: step_signal), sin nombrar Farmacia ni Licores. */
export function stepSignal(combos, step) {
  const nameable = (fine) =>
    fine === NONE_COMBO
      ? fine
      : membersOf(fine)
          .filter((m) => !combos.own_signals_only.includes(m))
          .join('+') || NONE_COMBO
  return {
    kind: 'combinacion',
    id: `${nameable(step.current)}→${nameable(step.target)}`,
    source: step.usedAssumption ? 'rappi+supuesto' : 'rappi',
  }
}
