import { screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { renderWithData, resetApi, serveFixtures, serveFixturesWith } from '../../test/fixtureApi.js'
import { OverviewView } from './OverviewView.jsx'

const NOT_EVIDENCE = 'uso del MVP, pocas personas: no es evidencia'
const decision = (name) => screen.getByRole('article', { name })

describe('OverviewView', () => {
  beforeEach(() => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  afterEach(resetApi)

  test('the four questions, each with its figure, its source and an action where there is one', async () => {
    serveFixtures()
    await renderWithData(<OverviewView source="synthetic" onNavigate={() => {}} />)

    const crossSell = decision('¿Dónde está la venta cruzada?')
    expect(within(crossSell).getByText('62,6%')).toBeTruthy()
    expect(within(crossSell).getByText('Dato de Rappi')).toBeTruthy()
    expect(within(crossSell).getByText(/Es una correlación, no un efecto\./)).toBeTruthy()

    const churn = decision('¿A quién estamos perdiendo?')
    expect(within(churn).getByText('280')).toBeTruthy()
    expect(within(churn).getByText(/Otras 564 pasaron el triple/)).toBeTruthy()
    expect(within(churn).getByText('Simulado')).toBeTruthy()

    const mochi = decision('¿Funciona lo que ofrece Mochi?')
    expect(within(mochi).getByText('43,8%')).toBeTruthy()

    const demand = decision('¿Qué buscan y no encuentran?')
    expect(within(demand).getByText('23,5%')).toBeTruthy() // la última semana completa al corte
    expect(within(demand).getByText('+4,0 puntos')).toBeTruthy()
    expect(
      within(demand).getByText(
        /🇵🇪 Comida peruana en Restaurantes, 708 personas en total \(\+31% en las últimas 4 semanas\)/,
      ),
    ).toBeTruthy()
    expect(within(demand).getByText(/^Revisar primero el buscador/)).toBeTruthy()

    // Solo la del dato de Rappi es una sugerencia; con datos simulados, un ejemplo de la mecánica.
    expect(within(decision('¿Dónde está la venta cruzada?')).getByText('Acción sugerida')).toBeTruthy()
    expect(screen.getAllByText('Ejemplo de acción (datos simulados)')).toHaveLength(3)
    expect(screen.queryByText(NOT_EVIDENCE)).toBeNull()
  })

  test('how it is going: weekly figures against 4 weeks before, and the full series on demand', async () => {
    serveFixtures()
    await renderWithData(<OverviewView source="synthetic" onNavigate={() => {}} />)

    const active = screen.getByRole('article', { name: 'Personas activas' })
    expect(within(active).getByText('558')).toBeTruthy()
    expect(within(active).getByText('−1%')).toBeTruthy()
    expect(within(active).getByRole('img', { name: 'Personas activas, últimas 12 semanas completas' })).toBeTruthy()
    expect(within(screen.getByRole('article', { name: 'Frecuencia (30 días)' })).getByText('1,50')).toBeTruthy()
    expect(screen.getByRole('table', { name: 'Serie semanal' })).toBeTruthy()
    expect(screen.getByText('Ver la serie semanal completa')).toBeTruthy()
  })

  test('with the prototype each card from it carries the MVP label, and Rappi data does not', async () => {
    serveFixtures()
    await renderWithData(<OverviewView source="prototype" onNavigate={() => {}} />)

    expect(within(decision('¿Dónde está la venta cruzada?')).queryByText(NOT_EVIDENCE)).toBeNull()
    for (const name of [
      '¿A quién estamos perdiendo?',
      '¿Funciona lo que ofrece Mochi?',
      '¿Qué buscan y no encuentran?',
    ]) {
      expect(within(decision(name)).getByText(NOT_EVIDENCE)).toBeTruthy()
    }
    // y una en «Cómo va»
    expect(screen.getAllByText(NOT_EVIDENCE)).toHaveLength(4)
    expect(
      within(decision('¿Funciona lo que ofrece Mochi?')).getByText('la tasa aparece desde 10 mostradas.', {
        exact: false,
      }),
    ).toBeTruthy()
  })

  test('a card whose data fails says so without taking down the others', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    serveFixturesWith({ offers: { source: 'synthetic', data: null } }) // respuesta no válida → lo guardado
    await renderWithData(<OverviewView source="prototype" onNavigate={() => {}} />)

    expect(within(decision('¿Dónde está la venta cruzada?')).getByText('62,6%')).toBeTruthy()
    expect(
      within(decision('¿Funciona lo que ofrece Mochi?')).getByText('No se pudieron cargar estos datos'),
    ).toBeTruthy()
  })
})
