// "Qué cambió": lo que más se movió, para leer el panel por excepción. Sale de lo que la API ya entrega (la serie
// semanal, lo que buscan y no encuentran, y lo que sube): ninguna cifra nueva, solo cuáles mirar primero.
import { formatNumber, formatSignedPct } from '../../lib/format.js'
import { COMPARE_WEEKS, WEEKLY_SERIES, weeklySeries } from './weekly.js'

// Bajo esto, un indicador semanal no se destaca: 5 % en un conteo, 1 punto en una tasa.
const MIN_COUNT_CHANGE = 5
const MIN_RATE_CHANGE = 1
// Una demanda que crece se destaca desde +20 %.
const MIN_GROWTH = 20
// A dónde lleva cada indicador semanal (vista y sección); los del Resumen ya están a la vista.
const WEEKLY_TARGETS = { sin_resultado_pct: ['mochi', 'busquedas'] }

/** Lo que empeora va primero; después lo que mejora y, al final, la demanda que crece (no es bueno ni malo). */
const RANK = { bad: 0, good: 1, muted: 2 }

function weeklyChanges(rows, asOf) {
  return WEEKLY_SERIES.flatMap((series) => {
    const { latest, change, formatChange } = weeklySeries(rows, series, asOf)
    if (!latest || change === null) return []
    if (Math.abs(change) < (series.rate ? MIN_RATE_CHANGE : MIN_COUNT_CHANGE)) return []
    return [
      {
        key: series.key,
        tone: (change > 0 ? 'up' : 'down') === series.goodWhen ? 'good' : 'bad',
        direction: change > 0 ? 'up' : 'down',
        title: series.title,
        figure: series.format(latest.value),
        change: formatChange(change),
        detail: `frente a hace ${COMPARE_WEEKS} semanas`,
        // Una tasa se mueve en puntos y un conteo en %: 1 punto pesa como 3 %.
        size: Math.abs(change) * (series.rate ? 3 : 1),
        target: WEEKLY_TARGETS[series.key] ?? null,
      },
    ]
  })
}

/** Lo que más personas buscan sin encontrar y además crece. */
function unmetChanges(opportunities) {
  return opportunities
    .filter((row) => row.crecimiento_pct >= MIN_GROWTH)
    .sort((a, b) => b.usuarios - a.usuarios)
    .slice(0, 1)
    .map((row) => ({
      key: `falta-${row.concept_id ?? row.que}`,
      tone: 'muted',
      direction: 'up',
      title: `${row.que}: lo buscan y no lo encuentran`,
      figure: `${formatNumber(row.usuarios)} personas`,
      change: formatSignedPct(row.crecimiento_pct),
      detail: `en las últimas ${COMPARE_WEEKS} semanas`,
      size: row.crecimiento_pct,
      target: ['mochi', 'busquedas'],
    }))
}

/** El concepto cuya demanda más crece (que no sea el mismo que ya salió como búsqueda sin resultado). */
function demandChanges(trends, taken) {
  return trends
    .filter((row) => row.crecimiento_pct >= MIN_GROWTH && !taken.has(`falta-${row.concept_id}`))
    .sort((a, b) => b.crecimiento_pct - a.crecimiento_pct)
    .slice(0, 1)
    .map((row) => ({
      key: `sube-${row.concept_id}`,
      tone: 'muted',
      direction: 'up',
      title: `${row.concepto}: la demanda crece`,
      figure: `${formatNumber(row.recientes)} señales`,
      change: formatSignedPct(row.crecimiento_pct),
      detail: `${formatNumber(row.anteriores)} en las ${COMPARE_WEEKS} semanas anteriores`,
      size: row.crecimiento_pct,
      target: ['mochi', 'busquedas'],
    }))
}

/**
 * Hasta `limit` cambios, de más a menos urgente: [{ key, tone, direction, title, figure, change, detail, target }].
 * `tone`: 'bad' (empeora), 'good' (mejora) o 'muted' (demanda que crece: sin juicio). `target`: [vista, sección] del
 * detalle, o null si ya está en el Resumen.
 */
export function notableChanges({ weekly, asOf, trends, opportunities, limit = 4 }) {
  const unmet = unmetChanges(opportunities)
  const taken = new Set(unmet.map((item) => item.key))
  return [...weeklyChanges(weekly, asOf), ...unmet, ...demandChanges(trends, taken)]
    .sort((a, b) => RANK[a.tone] - RANK[b.tone] || b.size - a.size)
    .slice(0, limit)
}
