// Cuentas de las ofertas de Mochi (/analytics/offers, por momento) y de sus sugerencias entre verticales
// (/analytics/suggestions, por concepto y vertical). Aceptada: la oferta se agregó al carro.
import { AGENT_NAME } from '../../lib/agentName.js'

/** Con menos mostradas que esto (una demo en vivo) un % no dice nada: se muestran solo las cuentas. */
export const MIN_SHOWN_FOR_RATE = 10

const MOMENTS = {
  plan: 'Plan',
  carrito: 'Carro',
  checkout: 'Antes de pagar',
  proximo_pedido: 'Próximo pedido',
  sin_resultado: 'Sin resultado',
  vertical_por_probar: 'Vertical por probar',
  recompra: 'Recompra',
  volver: 'Volver a pedir',
  ontop: 'OnTop de Turbo',
  perfil: 'Perfil de gusto',
  pregunta: 'Pregunta',
  para_ti: 'Para ti',
  sin_momento: 'Sin momento',
}

export const momentLabel = (moment) => MOMENTS[moment] ?? moment

// Dónde se hace cada oferta, en una línea: es el "en qué momento" que necesita RappiAds.
const MOMENT_HINTS = {
  plan: 'Un kit para una ocasión que la persona elige (carrete, asado)',
  carrito: 'Un complemento al agregar algo al carro',
  checkout: 'Algo que falta, antes de pagar',
  proximo_pedido: 'Para el próximo pedido, en el seguimiento',
  sin_resultado: 'Cuando una búsqueda no encontró nada',
  vertical_por_probar: 'Una vertical que la persona todavía no usa',
  recompra: '"¿Repetimos?" cuando le toca según su ciclo',
  volver: '"¿Volvemos a…?" a algo que dejó de pedir',
  ontop: '"Turbo: suma esto antes de…" mientras llega otro pedido',
  perfil: 'Los peldaños de su perfil de gusto',
  pregunta: `Al preguntarle a ${AGENT_NAME}`,
  para_ti: 'En "Para ti", al abrir el buscador',
  sin_momento: 'Sin registro de dónde se hizo',
}

export const momentHint = (moment) => MOMENT_HINTS[moment] ?? null

// Los momentos con botón para rechazar la oferta ("Ahora no" en el carro, "Después" en los otros tres). En los demás el
// rechazo no se mide: un 0 se leería como "nadie la rechazó".
export const REJECTABLE_MOMENTS = new Set(['carrito', 'vertical_por_probar', 'recompra', 'volver'])

// Los momentos con un botón que abre una vertical ("Ver …" en el carro, "Abrir …" en la vertical por probar, "Ver en …"
// sin resultado, los peldaños del perfil de gusto): ahí se cuentan las abiertas. En los demás, como el rechazo, "—".
export const OPENABLE_MOMENTS = new Set(['carrito', 'vertical_por_probar', 'sin_resultado', 'perfil'])

const sum = (rows, key) => rows.reduce((total, row) => total + (row[key] ?? 0), 0)

// Una tasa necesita el mínimo en su denominador: con 4 aceptadas, "50% llega a pedido" no dice nada.
const rate = (part, whole) => (whole >= MIN_SHOWN_FOR_RATE ? (part * 100) / whole : null)

/** Totales de las ofertas: `{ shown, accepted, rate }` (`rate` null bajo el mínimo de mostradas). */
export function offerTotals(moments) {
  const shown = sum(moments, 'mostradas')
  const accepted = sum(moments, 'aceptadas')
  return { shown, accepted, rate: rate(accepted, shown) }
}

/**
 * El momento que más acepta y el que menos, entre los que tienen tasa (10 o más mostradas). "Sin momento" no cuenta:
 * no dice dónde se hizo la oferta. `{ best, worst }`, cada uno null si no hay; `worst` es null si es el mismo que `best`.
 */
export function momentExtremes(moments) {
  const rated = moments
    .filter((row) => row.momento !== 'sin_momento' && row.aceptacion_pct !== null && row.aceptacion_pct !== undefined)
    .sort((a, b) => b.aceptacion_pct - a.aceptacion_pct)
  const best = rated[0] ?? null
  const worst = rated.length > 1 ? rated.at(-1) : null
  return { best, worst }
}

/**
 * Totales de las sugerencias entre verticales: mostradas, aceptadas, convertidas y sus tasas (la aceptación sobre las
 * mostradas, la conversión sobre las aceptadas; null bajo el mínimo).
 */
export function suggestionTotals(rows) {
  const shown = sum(rows, 'mostradas')
  const accepted = sum(rows, 'aceptadas')
  const converted = sum(rows, 'convertidas')
  return {
    shown,
    accepted,
    converted,
    acceptRate: rate(accepted, shown),
    convertRate: rate(converted, accepted),
  }
}

/** Para nombrar una ganadora hacen falta más casos que para mostrar una tasa: con 11 mostradas gana el azar. */
export const MIN_SHOWN_FOR_TOP = 50

// Verticales que Mochi no propone por su cuenta (offers/guards.py): sus filas son respuestas a lo que la persona pidió y
// no pueden ser la sugerencia que el panel recomienda empujar.
const NOT_PROPOSED = new Set(['licores', 'farmacia'])

/** Una ganadora tiene que distinguirse de la siguiente con p menor que esto; si no, la diferencia es ruido. */
export const MAX_P_FOR_TOP = 0.05

// erfc(x) para x ≥ 0 (Abramowitz y Stegun 7.1.26, error menor que 1,5e-7): basta para comparar p con 0,05.
function erfc(x) {
  const t = 1 / (1 + 0.3275911 * x)
  const poly = t * (0.254829592 + t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429))))
  return poly * Math.exp(-x * x)
}

/** p bilateral de la prueba z de dos proporciones: `a` aceptadas de `n` mostradas contra `b` de `m`. */
export function twoProportionP(a, n, b, m) {
  const pooled = (a + b) / (n + m)
  const se = Math.sqrt(pooled * (1 - pooled) * (1 / n + 1 / m))
  if (se === 0) return 1
  return erfc(Math.abs(a / n - b / m) / se / Math.SQRT2)
}

/**
 * La sugerencia (concepto y vertical) que más se acepta entre las que tienen 50 o más mostradas, o null. Nunca una de
 * Licores ni de Farmacia: el panel no recomienda empujar lo que Mochi no ofrece por su cuenta. Solo gana si se
 * distingue de la siguiente (prueba de dos proporciones, p < 0,05); sola o empatada con el azar, no hay ganadora.
 */
export function topSuggestion(rows) {
  const [top, next] = rows
    .filter((row) => row.mostradas >= MIN_SHOWN_FOR_TOP && row.aceptacion_pct !== null)
    .filter((row) => !NOT_PROPOSED.has(row.vertical))
    .sort((a, b) => b.aceptacion_pct - a.aceptacion_pct || b.mostradas - a.mostradas)
  if (!top || !next) return null
  return twoProportionP(top.aceptadas, top.mostradas, next.aceptadas, next.mostradas) < MAX_P_FOR_TOP ? top : null
}
