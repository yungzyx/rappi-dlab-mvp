import { act, fireEvent, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { renderWithData, resetApi, serveFixtures, serveFixturesWith } from '../../test/fixtureApi.js'
import { OverviewView } from './OverviewView.jsx'

const NOT_EVIDENCE = 'Prototipo · no es evidencia'
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

    // Con los simulados, la aceptación la fija el generador: sin cifra ni acción.
    const mochi = decision('¿Funciona lo que ofrece Mochi?')
    expect(within(mochi).getByText(/^En los simulados, la aceptación es un supuesto del generador/)).toBeTruthy()
    expect(within(mochi).queryByText('43,8%')).toBeNull()
    expect(within(mochi).queryByText('Ejemplo de acción (datos simulados)')).toBeNull()

    const demand = decision('¿Qué buscan y no encuentran?')
    expect(within(demand).getByText('21,5%')).toBeTruthy() // la última semana completa al corte
    expect(within(demand).getByText('+1,9 puntos')).toBeTruthy()
    expect(
      within(demand).getByText(
        /🇵🇪 Comida peruana en Restaurantes, 708 personas en total \(\+31% en las últimas 4 semanas\)/,
      ),
    ).toBeTruthy()
    expect(within(demand).getByText(/^Revisar primero el buscador/)).toBeTruthy()

    // Solo la del dato de Rappi es una sugerencia; con datos simulados, un ejemplo de la mecánica.
    expect(within(decision('¿Dónde está la venta cruzada?')).getByText('Acción sugerida')).toBeTruthy()
    expect(screen.getAllByText('Ejemplo de acción (datos simulados)')).toHaveLength(2)
    expect(screen.queryByText(NOT_EVIDENCE)).toBeNull()
  })

  test('how it is going: weekly figures against 4 weeks before, and the weekly series in a chart', async () => {
    serveFixtures()
    await renderWithData(<OverviewView source="synthetic" onNavigate={() => {}} />)

    const active = screen.getByRole('article', { name: 'Personas activas' })
    expect(within(active).getByText('561')).toBeTruthy()
    expect(within(active).getByText('−3%')).toBeTruthy()
    expect(within(active).getByRole('img', { name: 'Personas activas, últimas 12 semanas completas' })).toBeTruthy()
    expect(within(screen.getByRole('article', { name: 'Frecuencia (30 días)' })).getByText('1,50')).toBeTruthy()
    expect(screen.getByRole('table', { name: 'Serie semanal' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Ver tabla de Serie semanal' })).toBeTruthy()
    const picker = screen.getByRole('combobox', { name: 'Indicador' })
    expect(screen.getByRole('img', { name: /^Personas activas: / })).toBeTruthy()
    await act(async () => fireEvent.change(picker, { target: { value: 'pedidos' } }))
    expect(screen.getByRole('img', { name: /^Pedidos: / })).toBeTruthy()
  })

  test('what changed: the changes to look at first, worst first, each linking to its detail', async () => {
    serveFixtures()
    const onNavigate = vi.fn()
    await renderWithData(<OverviewView source="synthetic" onNavigate={onNavigate} />)

    const list = screen.getByRole('heading', { name: 'Qué cambió' }).closest('section').querySelector('.changes')
    const titles = [...list.querySelectorAll('.change-title')].map((node) => node.textContent)
    expect(titles).toEqual([
      'Búsquedas sin resultado',
      'Pedidos',
      '🥢 Despensa asiática: la demanda crece',
      '🇵🇪 Comida peruana: lo buscan y no lo encuentran',
    ])
    expect(within(list).getByText('+1,9 puntos')).toBeTruthy()
    // Personas activas (−3 %) y el abandono (+0,3 puntos) no se movieron lo suficiente.
    expect(within(list).queryByText('Personas activas')).toBeNull()

    fireEvent.click(within(list).getByRole('button', { name: 'Ver el detalle: Búsquedas sin resultado' }))
    expect(onNavigate).toHaveBeenCalledWith('mochi', 'busquedas')
  })

  test('the pilot status says the control group is off when it is', async () => {
    serveFixtures()
    await renderWithData(<OverviewView source="synthetic" onNavigate={() => {}} />)
    const hero = screen.getByRole('navigation', { name: 'Las tres hipótesis' })
    expect(within(hero).getByText(/el grupo de control está apagado, todavía no hay qué medir/)).toBeTruthy()
  })

  test('"Por vertical" is a design with example rows: it says so and offers no download', async () => {
    serveFixtures()
    await renderWithData(<OverviewView source="synthetic" tab="verticales" onNavigate={() => {}} />)
    expect(screen.getByRole('heading', { name: 'Por vertical' })).toBeTruthy()
    expect(screen.getByText('Diseño, aún sin datos.')).toBeTruthy()
    expect(screen.getAllByText('Diseño · filas de ejemplo').length).toBeGreaterThan(0)
    expect(screen.getByText('/analytics/verticales')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Descargar CSV/ })).toBeNull()
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
    // y una en "Qué cambió" y otra en "Cómo va"
    expect(screen.getAllByText(NOT_EVIDENCE)).toHaveLength(5)
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
    // Del prototipo no hay respaldo: el bloque queda vacío y el aviso (con su Reintentar) va una sola vez arriba.
    expect(within(decision('¿Funciona lo que ofrece Mochi?')).getByText('Sin conexión con la API')).toBeTruthy()
  })

  test('the first thing in the summary is a short link to the three hypotheses', async () => {
    serveFixtures()
    const onNavigate = vi.fn()
    await renderWithData(<OverviewView source="synthetic" onNavigate={onNavigate} />)

    const link = screen.getByRole('navigation', { name: 'Las tres hipótesis' })
    expect(link.compareDocumentPosition(screen.getByRole('heading', { name: 'Cómo va' })) & 4).toBeTruthy()
    fireEvent.click(within(link).getByRole('button', { name: /Ver las tres hipótesis/ }))
    expect(onNavigate).toHaveBeenCalledWith('experimentos', 'hipotesis')
  })
})
