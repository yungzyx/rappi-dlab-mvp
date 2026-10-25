import { describe, expect, test } from 'vitest'
import combos from '../../fixtures/combos.synthetic.json'
import { churnDecision, crossSellDecision, demandDecision, mochiDecision } from './decisions.js'

const moment = (momento, mostradas, aceptadas, aceptacion_pct = null) => ({
  momento,
  mostradas,
  aceptadas,
  aceptacion_pct,
})

describe('crossSellDecision', () => {
  test('leads with where most of Rappi users are and the retention of the next step', () => {
    const decision = crossSellDecision(combos.data)

    expect(decision.figure).toBe('62,6%')
    expect(decision.unit).toBe('de los usuarios de Rappi (739.000) solo pide en Restaurantes')
    expect(decision.context).toBe(
      'Vuelven al mes siguiente el 47%; quienes además piden en Turbo, el 82% (+35 puntos). Es una correlación, no un efecto.',
    )
    expect(decision.action).toMatch(/^Que Mochi ofrezca Turbo a quien solo pide en Restaurantes/)
    expect(decision.action).toMatch(/grupo de control\.$/)
  })

  test('without a step there is nothing to say', () => {
    expect(crossSellDecision({ rappi: { filas: [] } })).toBeNull()
  })
})

describe('churnDecision', () => {
  test('people at risk, the lost ones as comparison, and who to invite back', () => {
    const decision = churnDecision({ en_riesgo: 280, perdidos: 564 }, { califican: 137 })

    expect(decision.figure).toBe('280')
    expect(decision.context).toMatch(/Otras 564 pasaron el triple y se dan por perdidas/)
    expect(decision.action).toMatch(/hoy califican 137 personas que dejaron algo que pedían con ritmo/)
    // Con datos simulados, la fecha del último pedido simulado y no «hoy».
    expect(churnDecision({ en_riesgo: 1, perdidos: 0 }, { califican: 2, dia: '2026-10-17' }).action).toMatch(
      /al 17-10-2026 califican 2 personas/,
    )
  })

  test('without anyone to invite back, the reminder in their rhythm', () => {
    expect(churnDecision({ en_riesgo: 3, perdidos: 0 }, { califican: 0 }).action).toMatch(/^Recordarles su concepto/)
  })

  test('nobody at risk yet says why, with no action', () => {
    const decision = churnDecision({ en_riesgo: 0, perdidos: 0 }, { califican: 0 })

    expect(decision.figure).toBe('0')
    expect(decision.context).toMatch(/dos compras/)
    expect(decision.action).toBeUndefined()
  })
})

describe('mochiDecision', () => {
  test('the acceptance with the best and worst moment, and a moment that never converts is flagged', () => {
    const offers = {
      personas: 25,
      momentos: [
        moment('plan', 68, 0, 0),
        moment('carrito', 7, 0),
        moment('pregunta', 26, 2, 7.7),
        moment('para_ti', 101, 2, 2),
      ],
    }

    const decision = mochiDecision(offers, [])

    expect(decision.figure).toBe('2,0%') // 4 de 202
    expect(decision.context).toBe(
      '4 aceptadas de 202 mostradas a 25 personas. Por momento: «Pregunta» acepta el 7,7% y «Plan», el 0,0%.',
    )
    expect(decision.action).toBe('Revisar «Plan»: 68 mostradas y ninguna aceptada.')
  })

  test('without moments (simulated), the conversion of cross suggestions and the one that works best', () => {
    const offers = { personas: 1601, momentos: [moment('sin_momento', 3578, 813, 22.7)] }
    const suggestions = [
      {
        concepto: '🍺 Cerveza',
        vertical: 'licores',
        mostradas: 100,
        aceptadas: 30,
        convertidas: 20,
        aceptacion_pct: 30,
      },
      { concepto: '☕ Café', vertical: 'turbo', mostradas: 50, aceptadas: 20, convertidas: 10, aceptacion_pct: 40 },
    ]

    const decision = mochiDecision(offers, suggestions)

    expect(decision.figure).toBe('22,7%')
    expect(decision.context).toBe(
      '813 aceptadas de 3.578 mostradas a 1.601 personas. De las sugerencias entre verticales aceptadas, el 60,0% termina en pedido.',
    )
    expect(decision.action).toBe(
      'Empujar ☕ Café en Turbo: la sugerencia entre verticales que más se acepta (20 de 50, 40,0%).',
    )
  })

  test('under 10 shown only the counts', () => {
    const decision = mochiDecision({ personas: 1, momentos: [moment('plan', 1, 1)] }, [])

    expect(decision.figure).toBe('1')
    expect(decision.unit).toBe('oferta de Mochi mostrada')
    expect(decision.context).toBe('1 aceptada; la tasa aparece desde 10 mostradas.')
  })

  test('no offers yet', () => {
    expect(mochiDecision({ personas: 0, momentos: [] }, []).context).toBe(
      'Mochi todavía no hizo ofertas en esta fuente.',
    )
  })
})

describe('demandDecision', () => {
  const weekly = [
    { semana: '2026-09-01', sin_resultado_pct: 10 },
    { semana: '2026-09-08', sin_resultado_pct: 12 },
    { semana: '2026-09-15', sin_resultado_pct: 13 },
    { semana: '2026-09-22', sin_resultado_pct: 15 },
    { semana: '2026-09-29', sin_resultado_pct: 14 },
    { semana: '2026-10-06', sin_resultado_pct: 99 }, // parcial al corte: no cuenta
  ]
  const kpis = { busquedas_sin_resultado_pct: 22.3 }

  test('the last complete week against 4 weeks before, and the top unmet demand with its action', () => {
    const opportunities = [
      {
        que: '🥞 Desayunos',
        concept_id: 'desayuno',
        vertical: 'restaurantes',
        usuarios: 384,
        recientes: 168,
        crecimiento_pct: 44,
        accion: 'Oportunidad: sumar comercios o categoría',
      },
      {
        que: '🇵🇪 Comida peruana',
        concept_id: 'peruana',
        vertical: 'restaurantes',
        usuarios: 708,
        recientes: 406,
        crecimiento_pct: 31,
        accion: 'Oportunidad: sumar comercios o categoría',
      },
    ]

    const decision = demandDecision({ kpis, weekly, asOf: '2026-10-07', opportunities, unmet: { por_vertical: [] } })

    expect(decision.figure).toBe('14,0%')
    expect(decision.delta).toEqual({ value: 4, goodWhen: 'down', suffix: 'vs hace 4 semanas' })
    expect(decision.context).toBe(
      'Lo que más falta: 🇵🇪 Comida peruana en Restaurantes, 708 personas en total (+31% en las últimas 4 semanas).',
    )
    expect(decision.action).toMatch(/^Revisar primero el buscador .*sumar comercios\.$/)
  })

  test('without grouped demand (prototype), the top unmet search; without weeks, the 30-day rate', () => {
    const unmet = { por_vertical: [{ vertical: 'supermercado', concepto: null, sin_resultado: 2 }] }

    const decision = demandDecision({ kpis, weekly: [], asOf: null, opportunities: [], unmet })

    expect(decision.figure).toBe('22,3%')
    expect(decision.delta).toBeNull()
    expect(decision.context).toBe(
      'Lo que más falta: una búsqueda sin concepto reconocido en Supermercado (2 sin resultado).',
    )
  })

  test('nothing missing', () => {
    const decision = demandDecision({ kpis, weekly: [], asOf: null, opportunities: [], unmet: { por_vertical: [] } })

    expect(decision.context).toBe(
      'Ninguna búsqueda sin resultado que se pueda mostrar (los conceptos sensibles no se muestran).',
    )
    expect(decision.action).toBeUndefined()
  })
})
