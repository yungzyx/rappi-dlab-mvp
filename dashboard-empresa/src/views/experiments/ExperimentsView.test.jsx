import { screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { renderWithData, resetApi, serveFixtures, serveFixturesWith } from '../../test/fixtureApi.js'
import { ExperimentsView } from './ExperimentsView.jsx'

const NOT_EVIDENCE = 'Prototipo · no es evidencia'
const cells = (row) =>
  within(row)
    .getAllByRole('cell')
    .map((cell) => cell.textContent)
const bodyRows = (table) => within(table).getAllByRole('row').slice(1)

const offers = (mostradas, retenidas, aceptadas, pedidos, expuestas = mostradas + retenidas > 0 ? 1 : 0) => ({
  mostradas,
  retenidas,
  aceptadas,
  personas_con_oferta: expuestas,
  pedidos_despues: pedidos,
})

// La retención del grupo de control: la cohorte con su mes siguiente completo, bajo el mínimo del plan de piloto.
const retention = (overrides = {}) => ({
  variantes: [
    {
      variante: 'tratamiento',
      personas: 3,
      retencion_m1_pct: 33.3,
      suma_vertical_pct: 66.7,
      expuestas: 2,
      expuestas_pct: 66.7,
    },
    { variante: 'control', personas: 1, retencion_m1_pct: 100, suma_vertical_pct: 0, expuestas: 1, expuestas_pct: 100 },
  ],
  diferencia: {
    retencion_m1: { puntos: -66.7, ic95: null },
    suma_vertical: { puntos: 66.7, ic95: null },
  },
  minimo: { tratamiento: 7836, control: 871 },
  efecto_minimo_puntos: 5,
  base_pct: 47,
  concluyente: false,
  ...overrides,
})

// La respuesta de la API con el grupo de control encendido (10%) y personas en las dos variantes.
const withControl = (overrides = {}) => ({
  experimentos: {
    source: 'prototype',
    data: {
      experimentos: [
        {
          id: 'modo_app',
          al_azar: false,
          nota: 'No es al azar: describe, no mide efecto.',
          variantes: [
            { variante: 'propuesta', personas: 4, con_pedido: 3, verticales_por_persona: 2.33 },
            { variante: 'actual', personas: 2, con_pedido: 1, verticales_por_persona: 1 },
          ],
        },
        {
          id: 'ofertas_control',
          al_azar: true,
          control_pct: 10,
          nota: 'Al azar.',
          variantes: [
            {
              variante: 'tratamiento',
              personas: 5,
              con_pedido: 4,
              verticales_por_persona: 1.5,
              ofertas: offers(9, 0, 3, 6, 4),
            },
            {
              variante: 'control',
              personas: 1,
              con_pedido: 0,
              verticales_por_persona: null,
              ofertas: offers(0, 2, 0, 0),
            },
          ],
          retencion: retention(),
          ...overrides,
        },
      ],
    },
  },
})

describe('ExperimentsView', () => {
  beforeEach(() => {
    window.history.replaceState(null, '', '/')
    vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  afterEach(resetApi)

  test('the app mode says it describes and does not measure an effect, with its variants', async () => {
    serveFixtures()
    await renderWithData(<ExperimentsView source="synthetic" />)

    const mode = await screen.findByRole('table', { name: 'Modo de la app' })
    expect(screen.getByRole('heading', { name: /Modo de la app/ }).textContent).toContain('describe, no mide efecto')
    const [proposal, today] = bodyRows(mode)
    expect(cells(proposal)).toEqual(['Propuesta (con Mochi)', '40', '1640,0%', '1,5']) // 16 de 40 (40,0%)
    expect(cells(today)).toEqual(['"Rappi hoy"', '0', '0', '—'])
  })

  test('with the control group off and nobody assigned, it says so instead of an empty table', async () => {
    serveFixtures()
    await renderWithData(<ExperimentsView source="synthetic" />)

    expect(await screen.findByText('El grupo de control está apagado')).toBeTruthy()
    expect(screen.getByText(/Con OFFERS_CONTROL_PCT en 0 nadie tiene variante/)).toBeTruthy()
    expect(screen.queryByRole('table', { name: 'Grupo de control de las ofertas de Mochi' })).toBeNull()
    expect(screen.queryByTestId('tamano-grupos')).toBeNull()
  })

  test('the control group shows each group size, the warning and the offers by variant', async () => {
    serveFixturesWith(withControl())
    await renderWithData(<ExperimentsView source="prototype" />)

    const table = await screen.findByRole('table', { name: 'Grupo de control de las ofertas de Mochi' })
    expect(screen.getByRole('heading', { name: /Grupo de control/ }).textContent).toContain('al azar')
    expect(screen.getByTestId('tamano-grupos').textContent).toBe(
      'Grupos: 5 en tratamiento y 1 en control. Para medir +5 puntos de retención M+1 harían falta 7.836 en ' +
        'tratamiento y 871 en control (plan de piloto, sobre el 47% de "solo Restaurantes" en la tabla de Rappi, un ' +
        'supuesto). Con menos personas por grupo, la diferencia entre ellos no es concluyente.',
    )
    const [treated, control] = bodyRows(table)
    expect(cells(treated)).toEqual(['Tratamiento (ve las ofertas)', '5', '480,0%', '1,5', '9', '0', '480,0%', '3', '6'])
    expect(cells(control)).toEqual(['Control (no las ve)', '1', '00,0%', '—', '0', '2', '1100,0%', '0', '0'])
    expect(screen.getAllByText(NOT_EVIDENCE)).toHaveLength(3) // la población rotulada, en cada sección
  })

  test('the people with an offer are counted the same in both groups, and an empty group has no share', async () => {
    const control = { variante: 'control', personas: 0, con_pedido: 0, verticales_por_persona: null }
    const [treated] = withControl().experimentos.data.experimentos[1].variantes
    serveFixturesWith(withControl({ variantes: [treated, { ...control, ofertas: offers(0, 0, 0, 0) }] }))
    await renderWithData(<ExperimentsView source="prototype" />)

    const table = await screen.findByRole('table', { name: 'Grupo de control de las ofertas de Mochi' })
    const note = screen.getByTestId('expuestas-nota').textContent
    expect(note).toContain('Los dos grupos se cuentan igual, con lo que anota la API')
    expect(note).not.toMatch(/no se comparan/)
    const column = within(table)
      .getAllByRole('columnheader')
      .map((cell) => cell.textContent)
      .indexOf('Personas con oferta')
    expect(within(bodyRows(table)[1]).getAllByRole('cell')[column].textContent).toBe('0') // sin personas, sin %
  })

  test('the control group shows M+1 retention by group and the difference, neutral under the minimum', async () => {
    serveFixturesWith(withControl())
    await renderWithData(<ExperimentsView source="prototype" />)

    const table = await screen.findByRole('table', { name: 'Retención M+1 por grupo' })
    const [treated, control, difference] = bodyRows(table)
    expect(cells(treated)).toEqual(['Tratamiento (ve las ofertas)', '3', '266,7%', '33,3%', '66,7%'])
    expect(cells(control)).toEqual(['Control (no las ve)', '1', '1100,0%', '100,0%', '0,0%'])
    expect(cells(difference)).toEqual(['Diferencia (tratamiento − control)', '—', '—', '−66,7 puntos', '+66,7 puntos'])
    // La parte expuesta es de la misma cohorte y antes de M+1: la que sirve para el efecto entre expuestos.
    expect(screen.getByTestId('expuestas-cohorte-nota').textContent).toMatch(
      /^Con oferta elegible antes de M\+1: de esta misma.*puede no haberla visto/,
    )
    expect(within(table).queryByText(/IC 95 %/)).toBeNull() // bajo el mínimo, sin intervalo
    expect(screen.getByTestId('retencion-nota').textContent).toBe(
      'No es concluyente: los grupos no llegan al mínimo del plan de piloto.',
    )
  })

  test('once each group reaches the minimum, the difference reads with its interval', async () => {
    const diferencia = {
      retencion_m1: { puntos: -66.7, ic95: [-100, -13.3] },
      suma_vertical: { puntos: 66.7, ic95: [13.3, 100] },
    }
    serveFixturesWith(withControl({ retencion: retention({ concluyente: true, diferencia }) }))
    await renderWithData(<ExperimentsView source="prototype" />)

    expect((await screen.findByTestId('retencion-nota')).textContent).toBe(
      'Cada grupo llega al mínimo del plan de piloto: la diferencia se lee con su intervalo.',
    )
    const table = screen.getByRole('table', { name: 'Retención M+1 por grupo' })
    expect(cells(bodyRows(table)[2]).slice(3)).toEqual([
      '−66,7 puntosIC 95 %: −100,0 a −13,3',
      '+66,7 puntosIC 95 %: 13,3 a 100,0',
    ])
  })

  test('without anyone with their next month complete, it says so instead of the retention table', async () => {
    const empty = retention({
      variantes: ['tratamiento', 'control'].map((variante) => ({
        variante,
        personas: 0,
        retencion_m1_pct: null,
        suma_vertical_pct: null,
        expuestas: 0,
        expuestas_pct: null,
      })),
      diferencia: null,
    })
    serveFixturesWith(withControl({ retencion: empty }))
    await renderWithData(<ExperimentsView source="prototype" />)

    expect((await screen.findByTestId('retencion-nota')).textContent).toMatch(/^Nadie tiene todavía su mes siguiente/)
    expect(screen.queryByRole('table', { name: 'Retención M+1 por grupo' })).toBeNull()
  })

  test('without a minimum (a group still empty), the sizes keep the plain warning', async () => {
    serveFixturesWith(withControl({ retencion: retention({ minimo: null }) }))
    await renderWithData(<ExperimentsView source="prototype" />)

    expect((await screen.findByTestId('tamano-grupos')).textContent).toBe(
      'Grupos: 5 en tratamiento y 1 en control. Con menos personas por grupo, la diferencia entre ellos no es concluyente.',
    )
  })

  test('with the control group on but nobody assigned yet, it says how people get a variant', async () => {
    const nobody = { personas: 0, con_pedido: 0, verticales_por_persona: null, ofertas: offers(0, 0, 0, 0) }
    serveFixturesWith(
      withControl({
        variantes: [
          { variante: 'tratamiento', ...nobody },
          { variante: 'control', ...nobody },
        ],
      }),
    )
    await renderWithData(<ExperimentsView source="prototype" />)

    expect(await screen.findByText('Nadie tiene variante todavía')).toBeTruthy()
    expect(screen.queryByText('El grupo de control está apagado')).toBeNull()
  })
})
