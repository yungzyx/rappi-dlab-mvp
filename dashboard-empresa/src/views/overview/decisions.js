// Las 4 preguntas del Resumen, cada una con su cifra, su contexto (comparación o tendencia) y una acción sugerida.
// Funciones puras sobre las respuestas de /analytics: `{ figure, unit, context, delta?, action? }`.
import { AGENT_NAME } from '../../lib/agentName.js'
import { formatDate, formatNumber, formatPct, formatPoints, formatSignedPct } from '../../lib/format.js'
import { comboLabel, demandLabel, verticalLabel } from '../../lib/labels.js'
import { biggestStep } from '../customers/ladder.js'
import {
  MIN_SHOWN_FOR_RATE,
  momentExtremes,
  momentLabel,
  offerTotals,
  suggestionTotals,
  topSuggestion,
} from '../mochi/offers.js'
import { COMPARE_WEEKS, weeklySeries } from './weekly.js'

const people = (n) => `${formatNumber(n)} ${n === 1 ? 'persona' : 'personas'}`

/** ¿Dónde está la venta cruzada? La tabla de Rappi: el paso donde está la mayoría de los usuarios. */
export function crossSellDecision(combos) {
  const step = biggestStep(combos.rappi.filas)
  if (!step) return null
  const from = comboLabel(step.from.combo)
  const added = comboLabel(step.added)
  const single = !step.from.combo.includes('+')
  return {
    figure: formatPct(step.from.pct_usuarios),
    unit: `de los usuarios de Rappi (${formatNumber(step.from.usuarios)}) ${single ? 'solo pide' : 'pide'} en ${from}`,
    context: `Vuelven al mes siguiente el ${formatPct(step.fromPct, 0)}; quienes además piden en ${added}, el ${formatPct(step.toPct, 0)} (${formatPoints(step.gain, 0)}). Es una correlación, no un efecto.`,
    action: `Que ${AGENT_NAME} ofrezca ${added} a quien ${single ? 'solo ' : ''}pide en ${from} («vertical por probar») y medirlo contra un grupo de control.`,
  }
}

/** ¿A quién estamos perdiendo? En riesgo según su propio ritmo, perdidos y a cuántos invitar a volver. */
export function churnDecision(kpis, winback) {
  const atRisk = kpis.en_riesgo ?? 0
  const lost = kpis.perdidos ?? 0
  if (!atRisk && !lost) {
    return {
      figure: '0',
      unit: 'personas en riesgo',
      context: 'Nadie pasó el doble de su ritmo sin pedir: el ritmo necesita al menos dos compras por persona.',
    }
  }
  return {
    figure: formatNumber(atRisk),
    unit: `${atRisk === 1 ? 'persona' : 'personas'} en riesgo, según su propio ritmo`,
    context: `Pasaron el doble de su ritmo sin pedir y todavía se pueden recuperar. Otras ${formatNumber(lost)} pasaron el triple y se dan por perdidas.`,
    action:
      winback.califican > 0
        ? `Invitar a volver con «¿Volvemos a…?» de ${AGENT_NAME}: ${winback.dia ? `al ${formatDate(winback.dia)}` : 'hoy'} califican ${people(winback.califican)} que dejaron algo que pedían con ritmo. Fuera de la app, solo a quien aceptó avisos.`
        : 'Recordarles su concepto top en su ritmo; fuera de la app, solo a quien aceptó avisos.',
  }
}

/** ¿Funciona Mochi? Aceptación de sus ofertas, con el momento que más y el que menos acepta (o el paso a pedido). */
export function mochiDecision(offers, suggestions) {
  const totals = offerTotals(offers.momentos)
  if (!totals.shown) {
    return {
      figure: '0',
      unit: `ofertas de ${AGENT_NAME} mostradas`,
      context: `${AGENT_NAME} todavía no hizo ofertas en esta fuente.`,
    }
  }
  if (totals.rate === null) {
    return {
      figure: formatNumber(totals.shown),
      unit: totals.shown === 1 ? `oferta de ${AGENT_NAME} mostrada` : `ofertas de ${AGENT_NAME} mostradas`,
      context: `${formatNumber(totals.accepted)} ${totals.accepted === 1 ? 'aceptada' : 'aceptadas'}; la tasa aparece desde ${MIN_SHOWN_FOR_RATE} mostradas.`,
    }
  }
  const { best, worst } = momentExtremes(offers.momentos)
  const cross = suggestionTotals(suggestions)
  const accepted = `${formatNumber(totals.accepted)} ${totals.accepted === 1 ? 'aceptada' : 'aceptadas'}`
  let context = `${accepted} de ${formatNumber(totals.shown)} mostradas a ${people(offers.personas)}.`
  if (best && worst) {
    context += ` Por momento: «${momentLabel(best.momento)}» acepta el ${formatPct(best.aceptacion_pct)} y «${momentLabel(worst.momento)}», el ${formatPct(worst.aceptacion_pct)}.`
  } else if (cross.convertRate !== null) {
    context += ` De las sugerencias entre verticales aceptadas, el ${formatPct(cross.convertRate)} termina en pedido.`
  }
  return {
    figure: formatPct(totals.rate),
    unit: `de las ofertas de ${AGENT_NAME} se aceptan`,
    context,
    action: mochiAction(offers.momentos, worst, best, suggestions),
  }
}

function mochiAction(moments, worst, best, suggestions) {
  const dead = moments
    .filter((row) => row.momento !== 'sin_momento' && row.mostradas >= MIN_SHOWN_FOR_RATE && row.aceptadas === 0)
    .sort((a, b) => b.mostradas - a.mostradas)[0]
  if (dead)
    return `Revisar «${momentLabel(dead.momento)}»: ${formatNumber(dead.mostradas)} mostradas y ninguna aceptada.`
  if (best && worst) return `Dar más espacio a «${momentLabel(best.momento)}», el momento que más acepta.`
  const top = topSuggestion(suggestions)
  if (top) {
    return `Empujar ${top.concepto} en ${verticalLabel(top.vertical)}: la sugerencia entre verticales que más se acepta (${formatNumber(top.aceptadas)} de ${formatNumber(top.mostradas)}, ${formatPct(top.aceptacion_pct)}).`
  }
  return null
}

/**
 * La acción de la API para una demanda. «Sumar comercios» va después de descartar al buscador: que no aparezca puede ser
 * un sinónimo o una categoría que falta, no que no haya comercios.
 */
function demandAction(apiAction) {
  if (apiAction.startsWith('Oportunidad')) {
    return 'Revisar primero el buscador (un sinónimo o una categoría que falta); si de verdad no hay oferta, sumar comercios.'
  }
  return `${apiAction}.`
}

function growthText(row) {
  if (row.recientes === 0) return 'sin búsquedas en 4 semanas'
  if (row.crecimiento_pct === null || row.crecimiento_pct === undefined) return 'nueva en 4 semanas'
  return `${formatSignedPct(row.crecimiento_pct)} en las últimas 4 semanas`
}

/**
 * ¿Qué buscan y no encuentran? El % sin resultado de la última semana completa contra 4 semanas antes (sin semanas, el
 * de 30 días, sin comparación) y lo que más falta, con su acción.
 */
export function demandDecision({ kpis, weekly, asOf, opportunities, unmet }) {
  const series = weeklySeries(weekly, { key: 'sin_resultado_pct', rate: true }, asOf)
  const base = series.latest
    ? {
        figure: formatPct(series.latest.value),
        unit: `de las búsquedas y preguntas a ${AGENT_NAME} no encontraron nada la última semana`,
        delta:
          series.change === null
            ? null
            : { value: series.change, goodWhen: 'down', suffix: `vs hace ${COMPARE_WEEKS} semanas` },
      }
    : {
        figure: formatPct(kpis.busquedas_sin_resultado_pct),
        unit: `de las búsquedas y preguntas a ${AGENT_NAME} no encontraron nada en 30 días`,
        delta: null,
      }
  const [top] = [...opportunities].sort((a, b) => b.usuarios - a.usuarios)
  if (top) {
    return {
      ...base,
      context: `Lo que más falta: ${demandLabel(top)} en ${verticalLabel(top.vertical)}, ${people(top.usuarios)} en total (${growthText(top)}).`,
      action: demandAction(top.accion),
    }
  }
  const [row] = unmet.por_vertical
  if (row) {
    const what = row.concepto ?? 'una búsqueda sin concepto reconocido'
    const where = row.vertical ? ` en ${verticalLabel(row.vertical)}` : ''
    return {
      ...base,
      context: `Lo que más falta: ${what}${where} (${formatNumber(row.sin_resultado)} sin resultado).`,
      action: 'Revisar si falta el producto o el sinónimo antes de salir a buscar comercios.',
    }
  }
  // `unmet` y `opportunities` no muestran conceptos sensibles; el % sí los cuenta: puede haber sin resultado y nada que mostrar.
  return {
    ...base,
    context: 'Ninguna búsqueda sin resultado que se pueda mostrar (los conceptos sensibles no se muestran).',
  }
}
