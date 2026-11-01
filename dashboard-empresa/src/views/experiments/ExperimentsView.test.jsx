import { screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { renderWithData, resetApi, serveFixtures, serveFixturesWith } from '../../test/fixtureApi.js'
import { ExperimentsView } from './ExperimentsView.jsx'

const NOT_EVIDENCE = 'uso del MVP, pocas personas: no es evidencia'
const cells = (row) =>
  within(row)
    .getAllByRole('cell')
    .map((cell) => cell.textContent)
const bodyRows = (table) => within(table).getAllByRole('row').slice(1)

const offers = (mostradas, retenidas, aceptadas, pedidos) => ({
  mostradas,
  retenidas,
  aceptadas,
  personas_con_oferta: mostradas + retenidas > 0 ? 1 : 0,
  pedidos_despues: pedidos,
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
              ofertas: offers(9, 0, 3, 6),
            },
            {
              variante: 'control',
              personas: 1,
              con_pedido: 0,
              verticales_por_persona: null,
              ofertas: offers(0, 2, 0, 0),
            },
          ],
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
      'Grupos: 5 en tratamiento y 1 en control. Con pocas personas por grupo, la diferencia entre ellos no es concluyente.',
    )
    const [treated, control] = bodyRows(table)
    expect(cells(treated)).toEqual(['Tratamiento (ve las ofertas)', '5', '480,0%', '1,5', '9', '0', '3', '6'])
    expect(cells(control)).toEqual(['Control (no las ve)', '1', '00,0%', '—', '0', '2', '0', '0'])
    expect(screen.getByText(NOT_EVIDENCE)).toBeTruthy() // la población rotulada
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
