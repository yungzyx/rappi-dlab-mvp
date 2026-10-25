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
  perfil: 'Perfil de gusto',
  pregunta: 'Pregunta',
  para_ti: 'Para ti',
  sin_momento: 'Sin momento',
}

export const momentLabel = (moment) => MOMENTS[moment] ?? moment

// Dónde se hace cada oferta, en una línea: es el «en qué momento» que necesita RappiAds.
const MOMENT_HINTS = {
  plan: 'Un kit para una ocasión que la persona elige (carrete, asado)',
  carrito: 'Un complemento al agregar algo al carro',
  checkout: 'Algo que falta, antes de pagar',
  proximo_pedido: 'Para el próximo pedido, en el seguimiento',
  sin_resultado: 'Cuando una búsqueda no encontró nada',
  vertical_por_probar: 'Una vertical que la persona todavía no usa',
  recompra: '«¿Repetimos?» cuando le toca según su ciclo',
  volver: '«¿Volvemos a…?» a algo que dejó de pedir',
  perfil: 'Los peldaños de su perfil de gusto',
  pregunta: `Al preguntarle a ${AGENT_NAME}`,
  para_ti: 'En «Para ti», al abrir el buscador',
  sin_momento: 'Sin registro de dónde se hizo',
}

export const momentHint = (moment) => MOMENT_HINTS[moment] ?? null

const sum = (rows, key) => rows.reduce((total, row) => total + (row[key] ?? 0), 0)

// Una tasa necesita el mínimo en su denominador: con 4 aceptadas, «50% llega a pedido» no dice nada.
const rate = (part, whole) => (whole >= MIN_SHOWN_FOR_RATE ? (part * 100) / whole : null)

/** Totales de las ofertas: `{ shown, accepted, rate }` (`rate` null bajo el mínimo de mostradas). */
export function offerTotals(moments) {
  const shown = sum(moments, 'mostradas')
  const accepted = sum(moments, 'aceptadas')
  return { shown, accepted, rate: rate(accepted, shown) }
}

/**
 * El momento que más acepta y el que menos, entre los que tienen tasa (10 o más mostradas). «Sin momento» no cuenta:
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

/**
 * La sugerencia (concepto y vertical) que más se acepta entre las que tienen 50 o más mostradas, o null. Nunca una de
 * Licores ni de Farmacia: el panel no recomienda empujar lo que Mochi no ofrece por su cuenta.
 */
export function topSuggestion(rows) {
  return (
    rows
      .filter((row) => row.mostradas >= MIN_SHOWN_FOR_TOP && row.aceptacion_pct !== null)
      .filter((row) => !NOT_PROPOSED.has(row.vertical))
      .sort((a, b) => b.aceptacion_pct - a.aceptacion_pct || b.mostradas - a.mostradas)[0] ?? null
  )
}
