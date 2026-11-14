import { screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { renderWithData, resetApi, serveFixturesWith } from '../../test/fixtureApi.js'
import { ExperimentsView } from './ExperimentsView.jsx'

const rowsOf = (table) =>
  within(table)
    .getAllByRole('row')
    .slice(1)
    .map((row) => within(row).getAllByRole('rowheader')[0].textContent)
const card = (name) => screen.getByRole('article', { name })
const cellsOf = (table) =>
  within(table)
    .getAllByRole('row')
    .slice(1)
    .map((row) =>
      within(row)
        .getAllByRole('cell')
        .map((cell) => cell.textContent),
    )

// La población completa: lo que se ve con el control apagado.
const POPULATION = {
  retencion_m1: { mes: '2026-09', mes_siguiente: '2026-10', personas: 1200, pct: 61.5 },
  frecuencia: { personas: 1500, pedidos: 3000, pedidos_por_persona: 2, dias: 30 },
  rest_a_turbo: { personas: 800, con_turbo: 96, pct: 12, dias: 28 },
  encuesta: { respondidas: 40, si: 30, si_pct: 75 },
  adopcion: { personas: 1500, usaron: 300, usaron_pct: 20, ocultos_pct: 2.5, silenciaron_pct: 4, dias: 30 },
}

/** El experimento `ofertas_control` con `people` personas por grupo (0: nadie asignado) y las hipótesis a medida. */
function offersControl({ people = [0, 0], controlPct = 0, conclusive = false, ...overrides } = {}) {
  const [treated, control] = people
  return {
    id: 'ofertas_control',
    al_azar: true,
    control_pct: controlPct,
    nota: 'Al azar.',
    variantes: [
      { variante: 'tratamiento', personas: treated, con_pedido: 0, verticales_por_persona: null },
      { variante: 'control', personas: control, con_pedido: 0, verticales_por_persona: null },
    ].map((row) => ({
      ...row,
      ofertas: { mostradas: 0, retenidas: 0, aceptadas: 0, personas_con_oferta: 0, pedidos_despues: 0 },
    })),
    retencion: {
      variantes: [
        { variante: 'tratamiento', personas: 30, retencion_m1_pct: 60, suma_vertical_pct: 10 },
        { variante: 'control', personas: 20, retencion_m1_pct: 55, suma_vertical_pct: 5 },
      ].map((row) => ({ ...row, expuestas: 0, expuestas_pct: 0 })),
      diferencia: {
        retencion_m1: { puntos: 5, ic95: conclusive ? [1.2, 8.8] : null },
        suma_vertical: { puntos: 5, ic95: conclusive ? [0.5, 9.5] : null },
      },
      minimo: { tratamiento: 9795, control: 9795 },
      referencia: { efecto_puntos: 5, tratamiento: 1569, control: 1569 },
      efecto_minimo_puntos: 2,
      base_pct: 47,
      concluyente: conclusive,
    },
    frecuencia: {
      variantes: [
        { variante: 'tratamiento', personas_30d: 40, pedidos_30d: 2.5, personas_m1: 30, pedidos_m1: 1.8 },
        { variante: 'control', personas_30d: 35, pedidos_30d: 2.25, personas_m1: 20, pedidos_m1: 1.6 },
      ],
      diferencia: {
        pedidos_30d: { valor: 0.25, ic95: conclusive ? [0.05, 0.45] : null },
        pedidos_m1: { valor: 0.2, ic95: null },
      },
      dias: 30,
    },
    rest_a_turbo: {
      variantes: [
        { variante: 'tratamiento', personas: 25, con_turbo: 5, pct: 20 },
        { variante: 'control', personas: 20, con_turbo: 3, pct: 15 },
      ],
      diferencia: { puntos: 5, relativa_pct: 33.3, ic95: conclusive ? [-2, 12] : null },
      meta_relativa_pct: 10,
      dias: 28,
      minimo: { tratamiento: 7000, control: 7000 },
      concluyente: conclusive,
    },
    encuesta: {
      variantes: [
        { variante: 'tratamiento', respondidas: 120, si: 84, si_pct: 70 },
        { variante: 'control', respondidas: 110, si: 66, si_pct: 60 },
      ],
      diferencia: {
        puntos: 10,
        ic95: conclusive ? [-2.3, 22.3] : null,
        p_una_cola: conclusive ? 0.06 : null,
      },
      minimo: 100,
      concluyente: conclusive,
    },
    adopcion: {
      variantes: [
        {
          variante: 'tratamiento',
          personas: 40,
          usaron: 10,
          ocultos: 2,
          silenciaron: 4,
          usaron_pct: 25,
          ocultos_pct: 5,
          silenciaron_pct: 10,
        },
        {
          variante: 'control',
          personas: 35,
          usaron: 7,
          ocultos: 0,
          silenciaron: 1,
          usaron_pct: 20,
          ocultos_pct: 0,
          silenciaron_pct: 2.9,
        },
      ],
    },
    poblacion: POPULATION,
    ...overrides,
  }
}

const respond = (source, experiment) => ({
  experimentos: { source, data: { experimentos: [experiment] } },
})

describe('Las tres hipótesis', () => {
  beforeEach(() => {
    window.history.replaceState(null, '', '/')
    vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  afterEach(resetApi)

  test('they come first, in the order the business asked for, with adoption below and the mechanics last', async () => {
    serveFixturesWith(respond('synthetic', offersControl()))
    await renderWithData(<ExperimentsView source="synthetic" />)

    const headings = screen.getAllByRole('heading', { level: 2 }).map((heading) => heading.textContent)
    expect(headings).toEqual(['Las tres hipótesis', 'Adopción y apagado', 'Experimentos del MVP'])
    const cards = screen.getAllByRole('article').map((article) => article.getAttribute('aria-labelledby'))
    expect(cards).toEqual(['hipotesis-h1', 'hipotesis-h2', 'hipotesis-h3'])
    expect(card(/Retención M\+1/).textContent).toContain('Meta: +2 puntos sobre el control')
    expect(card(/Restaurantes → Turbo/).textContent).toContain('Meta: +10 % relativo sobre el control')
    expect(card(/Encontraste/).textContent).toContain('Sin umbral')
  })

  test('without a control group each card describes the whole population and says it measures no effect', async () => {
    serveFixturesWith(respond('synthetic', offersControl()))
    await renderWithData(<ExperimentsView source="synthetic" />)

    expect(screen.getByText(/El grupo de control está apagado \(OFFERS_CONTROL_PCT en 0\)/)).toBeTruthy()
    for (const name of [/Retención M\+1/, /Restaurantes → Turbo/, /Encontraste/]) {
      expect(within(card(name)).getByText('Sin grupo de control: describe, no mide un efecto')).toBeTruthy()
      expect(within(card(name)).queryByRole('table')).toBeNull()
    }
    expect(card(/Retención M\+1/).textContent).toContain(
      '61,5%de 1.200 personas que pidieron en septiembre volvieron a pedir en octubre',
    )
    expect(card(/Restaurantes → Turbo/).textContent).toContain('2,00pedidos por persona activa en 30 días')
    expect(card(/Restaurantes → Turbo/).textContent).toContain(
      '12,0%de 800 clientes de Restaurantes (28 días) también pidió en Turbo',
    )
    expect(card(/Encontraste/).textContent).toContain('75,0%respondió "Sí" (de 40 respuestas)')
    // Adopción y apagado: las personas activas de 30 días.
    const adoption = screen.getByRole('heading', { name: 'Adopción y apagado' }).closest('section')
    expect(within(adoption).getByText('Usaron a Mochi').closest('div').textContent).toContain('20,0%')
    // El simulador no genera ocultar ni silenciar: sin cifra, y lo dice.
    expect(within(adoption).getByText('Lo tienen oculto').closest('div').textContent).toBe(
      'Lo tienen oculto—los datos simulados no lo registran',
    )
  })

  test('with the prototype and no groups, adoption shows the hidden and silenced share of active people', async () => {
    serveFixturesWith(respond('prototype', offersControl()))
    await renderWithData(<ExperimentsView source="prototype" />)

    const adoption = screen.getByRole('heading', { name: 'Adopción y apagado' }).closest('section')
    expect(within(adoption).getByText('Lo tienen oculto').closest('div').textContent).toContain('2,5%')
    expect(within(adoption).getByText('Lo silenciaron por hoy').closest('div').textContent).toContain('4,0%')
  })

  test('with the control on but a group still empty, the cards keep describing and say why', async () => {
    serveFixturesWith(respond('prototype', offersControl({ people: [3, 0], controlPct: 10 })))
    await renderWithData(<ExperimentsView source="prototype" />)

    expect(screen.getByText(/Un grupo todavía no tiene personas/)).toBeTruthy()
    expect(within(card(/Retención M\+1/)).getByText(/Sin grupo de control/)).toBeTruthy()
  })

  test('with both groups, each card compares them under the minimum without an interval', async () => {
    serveFixturesWith(respond('prototype', offersControl({ people: [40, 35], controlPct: 50 })))
    await renderWithData(<ExperimentsView source="prototype" />)

    const h1 = within(card(/Retención M\+1/)).getByRole('table', { name: 'Retención M+1 por grupo' })
    expect(rowsOf(h1)).toEqual(['Tratamiento', 'Control', 'Diferencia'])
    expect(cellsOf(h1)).toEqual([['60,0%'], ['55,0%'], ['+5,0 puntos']])
    expect(card(/Retención M\+1/).textContent).toContain(
      '30 y 20 personas con su mes siguiente completo; para +2 puntos harían falta 9.795 y 9.795.',
    )
    const h2 = within(card(/Restaurantes → Turbo/)).getByRole('table')
    expect(cellsOf(h2)).toEqual([
      ['2,5040 personas', '20,0%25 clientes'],
      ['2,2535 personas', '15,0%20 clientes'],
      ['+0,25', '+5,0 puntos+33,3 % relativo'],
    ])
    expect(card(/Restaurantes → Turbo/).textContent).toContain('En M+1: 1,80 contra 1,60 pedidos por persona (+0,20).')
    const h3 = within(card(/Encontraste/)).getByRole('table')
    expect(cellsOf(h3)).toEqual([['70,0%120 respuestas'], ['60,0%110 respuestas'], ['+10,0 puntos']])
    for (const name of [/Retención M\+1/, /Restaurantes → Turbo/, /Encontraste/]) {
      expect(within(card(name)).getByText('No es concluyente')).toBeTruthy()
      expect(within(card(name)).queryByText(/IC 95 %/)).toBeNull()
    }
    // Adopción y apagado, por grupo.
    const adoption = screen.getByRole('table', { name: 'Adopción y apagado por grupo' })
    expect(within(adoption).getAllByRole('row')).toHaveLength(3)
    expect(adoption.textContent).toContain('Lo silenciaron por hoy')
  })

  test('once conclusive, the prototype reads each card with its interval and the one-sided test', async () => {
    serveFixturesWith(respond('prototype', offersControl({ people: [40, 35], controlPct: 50, conclusive: true })))
    await renderWithData(<ExperimentsView source="prototype" />)

    expect(within(card(/Retención M\+1/)).getByText('Sube con el tratamiento')).toBeTruthy()
    expect(card(/Retención M\+1/).textContent).toContain('IC 95 %: 1,2 a 8,8')
    expect(within(card(/Restaurantes → Turbo/)).getByText(/Sin diferencia clara/)).toBeTruthy()
    expect(card(/Restaurantes → Turbo/).textContent).toContain('IC 95 %: 0,05 a 0,45')
    expect(within(card(/Encontraste/)).getByText('No se sostiene que suba (p de una cola 0,060)')).toBeTruthy()
  })

  test('with simulated data there is no verdict nor interval, even with both groups at their minimum', async () => {
    serveFixturesWith(respond('synthetic', offersControl({ people: [40, 35], controlPct: 50, conclusive: true })))
    await renderWithData(<ExperimentsView source="synthetic" />)

    for (const name of [/Retención M\+1/, /Restaurantes → Turbo/, /Encontraste/]) {
      expect(within(card(name)).getByText('Simulado: sin veredicto')).toBeTruthy()
      // La diferencia sí se ve (es la mecánica), pero sin intervalo: la pone un supuesto del generador.
      expect(within(card(name)).getByText('Diferencia')).toBeTruthy()
      expect(within(card(name)).queryByText(/IC 95 %/)).toBeNull()
    }
    expect(screen.queryByText('Sube con el tratamiento')).toBeNull()
    expect(screen.getByText(/salen de supuestos puestos a mano en el generador/)).toBeTruthy()
  })

  test('a saved response from before the hypotheses says so instead of breaking', async () => {
    const old = offersControl()
    delete old.poblacion
    delete old.rest_a_turbo
    serveFixturesWith(respond('synthetic', old))
    await renderWithData(<ExperimentsView source="synthetic" />)

    expect(screen.getAllByText('Esta respuesta no trae las hipótesis')).toHaveLength(2)
    expect(screen.getByRole('heading', { name: 'Experimentos del MVP' })).toBeTruthy()
  })
})
