// «Ver cómo funciona» (solo en el panel en un solo HTML, `npm run panel:html`): un recorrido corto de una persona en la
// app, aplicado como eventos de ejemplo sobre las respuestas grabadas de la fuente del prototipo. Es una demostración:
// las cifras que cambian no son datos reales. Funciones puras: cada paso recibe las respuestas y devuelve otras nuevas.
import { AGENT_NAME } from '../lib/agentName.js'

const round = (value, decimals) => Math.round(value * 10 ** decimals) / 10 ** decimals
// La misma regla que la API: la tasa aparece desde 10 mostradas.
const rate = (accepted, shown) => (shown >= 10 ? round((accepted * 100) / shown, 1) : null)

/** Una respuesta con su `data` copiada y cambiada por `change` (no toca la original). */
function edit(body, change) {
  const data = structuredClone(body.data)
  change(data)
  return { ...body, data }
}

function offer(responses, moment, { shown = 0, accepted = 0, newPerson = false }) {
  return edit(responses['offers.prototype'], (data) => {
    let row = data.momentos.find((item) => item.momento === moment)
    if (!row) {
      row = { momento: moment, mostradas: 0, aceptadas: 0, aceptacion_pct: null }
      data.momentos.push(row)
    }
    row.mostradas += shown
    row.aceptadas += accepted
    row.aceptacion_pct = rate(row.aceptadas, row.mostradas)
    if (newPerson) data.personas += 1
  })
}

function kpis(responses, { activeUsers = 0, orders = 0 }) {
  return edit(responses['kpis.prototype'], (data) => {
    data.usuarios_activos += activeUsers
    data.pedidos_30d += orders
    data.frecuencia = data.usuarios_activos ? round(data.pedidos_30d / data.usuarios_activos, 2) : null
  })
}

function unmetSearch(responses, vertical) {
  return edit(responses['unmet.prototype'], (data) => {
    data.personas += 1
    data.busquedas += 1
    data.sin_resultado += 1
    let row = data.por_vertical.find((item) => item.vertical === vertical && item.concepto === null)
    if (!row) {
      row = { vertical, concepto: null, sin_resultado: 0 }
      data.por_vertical.push(row)
    }
    row.sin_resultado += 1
    data.por_vertical.sort((a, b) => b.sin_resultado - a.sin_resultado)
  })
}

/**
 * Los pasos, en orden. Cada uno dice qué pasa en la app, dónde mirarlo en el panel (`view` y `section`, el id del título
 * de la sección) y qué respuestas cambia (`apply`). Los pasos se acumulan: el 3 parte de lo que dejó el 2.
 */
export const TOUR = [
  {
    title: `${AGENT_NAME} le hace una oferta`,
    text: `Una persona nueva abre la app y ${AGENT_NAME} le ofrece el kit «Carrete», el momento «Plan». En la tabla por momento, «Plan» suma una mostrada.`,
    view: 'mochi',
    section: 'ofertas',
    apply: (responses) => ({
      ...responses,
      'offers.prototype': offer(responses, 'plan', { shown: 1, newPerson: true }),
      'kpis.prototype': kpis(responses, { activeUsers: 1 }),
    }),
  },
  {
    title: 'La acepta',
    text: 'Agrega el kit al carro: para el panel, la oferta quedó aceptada. «Plan» suma una aceptada y, desde 10 mostradas, cambia su tasa.',
    view: 'mochi',
    section: 'ofertas',
    apply: (responses) => ({ ...responses, 'offers.prototype': offer(responses, 'plan', { accepted: 1 }) }),
  },
  {
    title: 'Paga el pedido',
    text: 'Queda un pedido. En «Cómo va», la frecuencia de 30 días cuenta ese pedido y a la persona nueva.',
    view: 'resumen',
    section: 'como-va',
    apply: (responses) => ({ ...responses, 'kpis.prototype': kpis(responses, { orders: 1 }) }),
  },
  {
    title: 'Busca algo que no hay',
    text: 'Busca «sushi de chocolate» y no encuentra nada. «Qué buscan y no encuentran» suma una búsqueda sin resultado en Restaurantes, sin el texto que escribió.',
    view: 'mochi',
    section: 'busquedas',
    apply: (responses) => ({ ...responses, 'unmet.prototype': unmetSearch(responses, 'restaurantes') }),
  },
]

/** Las respuestas después de los primeros `steps` pasos, a partir de las grabadas (que no cambian). */
export function responsesAfter(recorded, steps) {
  return TOUR.slice(0, steps).reduce((responses, step) => step.apply(responses), recorded)
}
