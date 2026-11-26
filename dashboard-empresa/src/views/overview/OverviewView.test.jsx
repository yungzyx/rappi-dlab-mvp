import { act, fireEvent, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { renderWithData, resetApi, serveFixtures, serveFixturesWith } from '../../test/fixtureApi.js'
import syntheticExperiments from '../../fixtures/experimentos.synthetic.json'
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

  describe('the pilot status', () => {
    const experiments = (source, changes) => {
      const body = structuredClone(syntheticExperiments)
      Object.assign(
        body.data.experimentos.find((item) => item.id === 'ofertas_control'),
        changes,
      )
      return { experimentos: { ...body, source } }
    }
    const hero = () => screen.getByRole('navigation', { name: 'Las tres hipótesis' })
    const progress = () => hero().querySelector('.pilot')

    test('with the simulated groups it never shows a pilot, with the control group on or off', async () => {
      for (const control of [0, 10]) {
        serveFixturesWith(experiments('synthetic', { control_pct: control }))
        const { unmount } = await renderWithData(<OverviewView source="synthetic" onNavigate={() => {}} />)
        expect(within(hero()).getByText(/los grupos simulados no son un piloto/)).toBeTruthy()
        expect(within(hero()).queryByText(/apagado/)).toBeNull()
        expect(within(hero()).queryByText(/Llegó al mínimo|del mínimo/)).toBeNull()
        expect(progress()).toBeNull()
        unmount()
        resetApi()
      }
    })

    test('with the prototype, the control group off and nobody in a group, there is nothing to measure', async () => {
      const empty = [
        { variante: 'tratamiento', personas: 0 },
        { variante: 'control', personas: 0 },
      ]
      serveFixturesWith(experiments('prototype', { control_pct: 0, variantes: empty }))
      await renderWithData(<OverviewView source="prototype" onNavigate={() => {}} />)
      expect(within(hero()).getByText(/el grupo de control está apagado, todavía no hay qué medir/)).toBeTruthy()
    })

    test('with the prototype and groups already there, the progress shows even with the control group off', async () => {
      serveFixturesWith(experiments('prototype', { control_pct: 0 }))
      await renderWithData(<OverviewView source="prototype" onNavigate={() => {}} />)
      expect(within(hero()).queryByText(/todavía no hay qué medir/)).toBeNull()
      expect(within(hero()).getByText(/no entran personas nuevas, el grupo de control está apagado/)).toBeTruthy()
      expect(progress()).toBeTruthy()
      expect(within(hero()).getByText('H1')).toBeTruthy()
    })
  })

  test('"Por vertical": the verticals side by side, with their change and the ones left out', async () => {
    serveFixturesWith({
      verticales: {
        source: 'synthetic',
        data: {
          verticales: [
            {
              vertical: 'restaurantes',
              personas_30d: 756,
              pedidos_30d: 1271,
              cambio_personas_pct: -4,
              cambio_pedidos_pct: null,
              abandono_carrito_pct: 28.1,
              sin_resultado_pct: 27.1,
              combinan_pct: 22.3,
            },
            {
              vertical: 'turbo',
              personas_30d: 203,
              pedidos_30d: 394,
              cambio_personas_pct: 5,
              cambio_pedidos_pct: -4,
              abandono_carrito_pct: null,
              sin_resultado_pct: null,
              combinan_pct: 64.9,
            },
          ],
          bajo_el_minimo: 1,
          minimo_personas: 20,
          dias: 30,
          dias_combinacion: 60,
          minimo_casos: 10,
        },
      },
    })
    await renderWithData(<OverviewView source="synthetic" tab="verticales" onNavigate={() => {}} />)

    expect(screen.getByRole('heading', { name: 'Por vertical' })).toBeTruthy()
    const [, restaurants, turbo] = screen.getAllByRole('row')
    expect(within(restaurants).getByText('Restaurantes')).toBeTruthy()
    expect(within(restaurants).getByText('756')).toBeTruthy()
    expect(within(restaurants).getByText('−4%')).toBeTruthy()
    expect(within(restaurants).getByText('28,1%')).toBeTruthy()
    expect(within(turbo).getByText('+5%')).toBeTruthy()
    expect(within(turbo).getAllByText('—')).toHaveLength(2) // sin casos suficientes para esas dos tasas
    expect(screen.getByText('1 vertical no llega a 20 personas y no se muestra.')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Descargar CSV de Verticales lado a lado' })).toBeTruthy()
  })

  test('"Por vertical" says so when no vertical reaches the minimum', async () => {
    serveFixtures() // el recorrido corto del prototipo: nadie llega al mínimo
    await renderWithData(<OverviewView source="prototype" tab="verticales" onNavigate={() => {}} />)
    expect(screen.getByText('Ninguna vertical llega al mínimo')).toBeTruthy()
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
