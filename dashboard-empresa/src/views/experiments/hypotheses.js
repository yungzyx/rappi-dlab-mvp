// Las tres hipótesis del piloto (docs/plan-piloto.md) en el orden del gerente: H1 retención M+1, H2 frecuencia y
// Restaurantes → Turbo, H3 "¿Encontraste lo que buscabas?". Salen del experimento `ofertas_control` de
// /analytics/experimentos: por grupo si los dos tienen personas; si no, la población completa, que describe y no mide.
import { formatNumber } from '../../lib/format.js'

export const TREATMENT = 'tratamiento'
export const CONTROL = 'control'
// p de una cola bajo el que la H3 dice que sube con Mochi (α = 0,05).
const ALPHA = 0.05

/** El experimento del grupo de control, o undefined si la respuesta no lo trae. */
export const offersExperiment = (data) => data.experimentos.find((item) => item.id === 'ofertas_control')

/** Si la respuesta trae las hipótesis (una foto grabada antes del 13-11 no las trae). */
export const hasHypotheses = (experiment) => Boolean(experiment?.poblacion && experiment.rest_a_turbo)

/** 'grupos' si tratamiento y control tienen personas (se comparan); si no, 'poblacion' (solo describe). */
export function hypothesesMode(experiment) {
  const people = Object.fromEntries(experiment.variantes.map((row) => [row.variante, row.personas]))
  return people[TREATMENT] > 0 && people[CONTROL] > 0 ? 'grupos' : 'poblacion'
}

/** La fila de una variante en una lista `{variante, …}`, o {} si no está. */
export const byVariant = (rows, variant) => rows?.find((row) => row.variante === variant) ?? {}

/** Con signo y en es-CL: 0.25 → "+0,25", −1 → "−1,00". */
export function formatSigned(value, decimals = 2) {
  if (value === null || value === undefined) return formatNumber(value)
  return `${value > 0 ? '+' : ''}${formatNumber(value, decimals)}`
}

/**
 * Lo que dice la tarjeta de una hipótesis: `{tone, label}`. Sin grupos, que describe; con los simulados, sin veredicto
 * (la regla de #79: el generador fija el resultado); bajo el mínimo, que no es concluyente; con el mínimo, lo que dice
 * el intervalo de 95 % (`ic95`, en las unidades de la diferencia).
 */
export function verdict({ mode, source, conclusive, ic95 }) {
  if (mode === 'poblacion') return { tone: 'warn', label: 'Sin grupo de control: describe, no mide un efecto' }
  if (source === 'synthetic') return { tone: 'muted', label: 'Simulado: sin veredicto' }
  if (!conclusive || !ic95) return { tone: 'muted', label: 'No es concluyente' }
  if (ic95[0] > 0) return { tone: 'good', label: 'Sube con el tratamiento' }
  if (ic95[1] < 0) return { tone: 'bad', label: 'Baja con el tratamiento' }
  return { tone: 'muted', label: 'Sin diferencia clara: el intervalo cruza el 0' }
}

/** La H3 se lee con su prueba a una cola (H0: igual; la alternativa: mayor con Mochi), sin umbral. */
export function surveyVerdict({ mode, source, survey }) {
  const base = verdict({ mode, source, conclusive: survey.concluyente, ic95: survey.diferencia?.ic95 })
  if (mode === 'poblacion' || source === 'synthetic' || !survey.concluyente || !survey.diferencia) return base
  const p = survey.diferencia.p_una_cola
  return p < ALPHA
    ? { tone: 'good', label: `Sube en tratamiento (p de una cola ${formatNumber(p, 3)})` }
    : { tone: 'muted', label: `No se sostiene que suba (p de una cola ${formatNumber(p, 3)})` }
}

const MONTHS = [
  'enero',
  'febrero',
  'marzo',
  'abril',
  'mayo',
  'junio',
  'julio',
  'agosto',
  'septiembre',
  'octubre',
  'noviembre',
  'diciembre',
]

/** "2026-09" → "septiembre"; sin mes, "—". */
export function monthName(yearMonth) {
  const match = /^\d{4}-(\d{2})$/.exec(yearMonth ?? '')
  return match ? MONTHS[Number(match[1]) - 1] : formatNumber(null)
}

/** "12 y 10": las personas de tratamiento y control de un `{tratamiento, control}`. */
export const pairOf = (counts) => `${formatNumber(counts[TREATMENT])} y ${formatNumber(counts[CONTROL])}`
