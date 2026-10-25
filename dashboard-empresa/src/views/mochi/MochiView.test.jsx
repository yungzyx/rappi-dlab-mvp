import { act, fireEvent, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import App from '../../App.jsx'
import { apiDown, renderWithData, resetApi, serveFixtures, serveFixturesWith } from '../../test/fixtureApi.js'
import { MochiView } from './MochiView.jsx'

const NOT_EVIDENCE = 'uso del MVP, pocas personas: no es evidencia'
const OFFLINE = 'La API no responde: el uso del MVP solo se ve con la base viva.'

const cells = (row) =>
  within(row)
    .getAllByRole('cell')
    .map((cell) => cell.textContent)
const bodyRows = (table) => within(table).getAllByRole('row').slice(1)
// El momento va en negrita y debajo dice dónde se hace la oferta.
const momentName = (row) => within(row).getAllByRole('cell')[0].querySelector('strong').textContent
const offersWith = (momentos, personas = 1) => ({ offers: { source: 'prototype', data: { personas, momentos } } })

describe('MochiView', () => {
  beforeEach(() => {
    window.history.replaceState(null, '', '/')
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    vi.spyOn(console, 'error').mockImplementation(() => {}) // el límite de error de un bloque lo registra
  })

  afterEach(resetApi)

  test('offers by moment: «Plan» with its accepted ones in the third cell, and a dash under the minimum', async () => {
    serveFixtures()
    await renderWithData(<MochiView source="prototype" />)

    const offers = await screen.findByRole('table', { name: 'Ofertas del agente por momento' })
    const [plan, cart] = bodyRows(offers)
    expect(momentName(plan)).toBe('Plan')
    expect(cells(plan).slice(1)).toEqual(['1', '1', '—'])
    expect(momentName(cart)).toBe('Carro')
    // Lo que busca `make mvp-check`: la fila cuyo nombre empieza con «Plan ».
    expect(within(offers).getByRole('row', { name: /^Plan / })).toBe(plan)
    expect(within(plan).getByText('Un kit para una ocasión que la persona elige (carrete, asado)')).toBeTruthy()
  })

  test('each moment has its Spanish label, and a rate the backend computes is shown', async () => {
    serveFixturesWith(
      offersWith([
        { momento: 'checkout', mostradas: 12, aceptadas: 3, aceptacion_pct: 25 },
        { momento: 'perfil', mostradas: 3, aceptadas: 1, aceptacion_pct: null },
        { momento: 'recompra', mostradas: 2, aceptadas: 1, aceptacion_pct: null },
        { momento: 'volver', mostradas: 3, aceptadas: 1, aceptacion_pct: null },
        { momento: 'sin_momento', mostradas: 1, aceptadas: 0, aceptacion_pct: null },
      ]),
    )
    await renderWithData(<MochiView source="prototype" />)

    const offers = await screen.findByRole('table', { name: 'Ofertas del agente por momento' })
    expect(bodyRows(offers).map(momentName)).toEqual([
      'Antes de pagar',
      'Perfil de gusto',
      'Recompra',
      'Volver a pedir',
      'Sin momento',
    ])
    expect(within(offers).getByText('25,0%')).toBeTruthy()
  })

  test('prototype sections carry the not-evidence label', async () => {
    serveFixtures()
    await renderWithData(<MochiView source="prototype" />)

    expect(screen.getAllByText(NOT_EVIDENCE)).toHaveLength(2)
    expect(screen.queryByText(/datos simulados/i)).toBeNull()
  })

  test('synthetic: the simulator has no moment, so the cross suggestions carry the section', async () => {
    serveFixtures()
    await renderWithData(<MochiView source="synthetic" />)

    expect(await screen.findByText('Los datos simulados no registran el momento de la oferta')).toBeTruthy()
    expect(screen.queryByRole('table', { name: 'Ofertas del agente por momento' })).toBeNull()
    const suggestions = screen.getByRole('table', { name: 'Sugerencias entre verticales' })
    expect(cells(bodyRows(suggestions)[0])).toEqual([
      '🥤 Bebidas gaseosasen Conveniencia',
      '212 de 944',
      '22,5%',
      '150 (71%)',
    ])
    expect(bodyRows(suggestions)).toHaveLength(8)
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Ver las 30' })))
    expect(bodyRows(suggestions)).toHaveLength(30)
    expect(screen.queryByText(NOT_EVIDENCE)).toBeNull()
  })

  test('synthetic offers with real moments still show them as a table', async () => {
    serveFixturesWith({
      offers: {
        source: 'synthetic',
        data: { personas: 9, momentos: [{ momento: 'plan', mostradas: 20, aceptadas: 5, aceptacion_pct: 25 }] },
      },
    })
    await renderWithData(<MochiView source="synthetic" />)

    const offers = await screen.findByRole('table', { name: 'Ofertas del agente por momento' })
    expect(within(offers).getByText('Plan')).toBeTruthy()
  })

  test('services without catalog: offered and opened, and the catalog hook when there is one', async () => {
    serveFixtures()
    await renderWithData(<MochiView source="synthetic" />)

    const services = screen.getByRole('table', { name: 'Servicios sin catálogo' })
    expect(cells(bodyRows(services)[0])).toEqual(['✈️ RappiTravel', '442', '157 (36%)', '—'])
  })

  test('a service with a catalog hook shows how many accepted it', async () => {
    const travel = { servicio: 'rappitravel', nombre: '✈️ RappiTravel', ofrecido: 556, abierto: 186, desde_home: 0 }
    serveFixturesWith({
      services: { source: 'synthetic', data: [{ ...travel, ganchos_mostrados: 556, ganchos_aceptados: 126 }] },
    })
    await renderWithData(<MochiView source="synthetic" />)

    const services = screen.getByRole('table', { name: 'Servicios sin catálogo' })
    expect(cells(bodyRows(services)[0])).toEqual(['✈️ RappiTravel', '556', '186 (33%)', '126 de 556'])
  })

  test('the motor against a simple rule, or why there is no evaluation yet', async () => {
    serveFixturesWith({
      motor: {
        source: 'synthetic',
        data: {
          pesos: {},
          lambda_cruzada: 1,
          fecha: '2026-10-22T05:59:02+00:00',
          evaluacion: {
            proximo_vertical: { combinado: { hit1: 0.9663, personas: 505 }, orden_fijo: { hit1: 0.8396 } },
            compra_cruzada: { mezcla: { precision3: 0.1294 }, lo_mas_pedido: { precision3: 0.1294 } },
          },
        },
      },
    })
    await renderWithData(<MochiView source="synthetic" />)

    const motor = screen.getByRole('table', { name: 'El motor contra una regla simple' })
    const [next] = bodyRows(motor)
    expect(cells(next).slice(1)).toEqual(['96,6%', '84,0%Orden fijo', '+12,6 puntos'])
    expect(screen.getByText(/prueba la mecánica del motor, no su efecto/)).toBeTruthy()
    resetApi()

    serveFixtures() // los guardados: el motor corrió sin 84 días de pedidos
    await renderWithData(<MochiView source="synthetic" />)
    expect(screen.getByText('Sin evaluación todavía')).toBeTruthy()
  })

  test('what they search and do not find: grouped demand with its action, what rises and thin assortment', async () => {
    serveFixtures()
    await renderWithData(<MochiView source="synthetic" />)

    const demand = screen.getByRole('table', { name: 'Demanda no satisfecha por concepto y vertical' })
    expect(within(bodyRows(demand)[0]).getByText('🇵🇪 Comida peruana')).toBeTruthy()
    const rising = screen.getByRole('table', { name: 'Conceptos que suben' })
    expect(bodyRows(rising).length).toBeLessThanOrEqual(5)
    expect(within(rising).getAllByText('sin surtido').length).toBeGreaterThan(0) // la comida peruana sube sin surtido
    const thin = screen.getByRole('table', { name: 'Poco surtido para lo que se busca' })
    expect(cells(bodyRows(thin)[0])[0]).toBe('🦴 Accesorios para mascotasen Turbo')
  })

  test('without grouped demand (prototype), the unmet searches by vertical and concept', async () => {
    serveFixturesWith({
      unmet: {
        source: 'prototype',
        data: {
          personas: 1,
          busquedas: 2,
          sin_resultado: 2,
          por_vertical: [{ vertical: null, concepto: null, sin_resultado: 2 }],
        },
      },
    })
    await renderWithData(<MochiView source="prototype" />)

    const unmet = await screen.findByRole('table', { name: 'Búsquedas sin resultado por vertical y concepto' })
    expect(cells(bodyRows(unmet)[0])).toEqual(['Sin vertical', 'Sin concepto reconocido', '2'])
    expect(screen.getByText('2 de 2')).toBeTruthy()
  })

  test('with the API down and the prototype source no saved figures appear', async () => {
    window.history.replaceState(null, '', '/?vista=mochi&fuente=prototipo')
    apiDown()
    await renderWithData(<App />)

    expect((await screen.findAllByText(OFFLINE)).length).toBeGreaterThan(1)
    expect(screen.queryByRole('table', { name: 'Ofertas del agente por momento' })).toBeNull()
    expect(screen.queryByText('Modo sin conexión (datos guardados):')).toBeNull() // no hay nada guardado que avisar
  })

  test('a response from the other source is discarded instead of shown', async () => {
    const synthetic = (await import('../../fixtures/offers.synthetic.json')).default
    serveFixturesWith({ offers: synthetic }) // la API contesta «simulado» también a ?source=prototype
    await renderWithData(<MochiView source="prototype" />)

    expect(screen.getAllByText(OFFLINE).length).toBeGreaterThan(0)
    expect(screen.queryByRole('table', { name: 'Ofertas del agente por momento' })).toBeNull()
  })

  test('switching source refetches and never mixes', async () => {
    window.history.replaceState(null, '', '/?vista=mochi')
    serveFixtures()
    await renderWithData(<App />)
    expect(screen.getByRole('table', { name: 'Sugerencias entre verticales' })).toBeTruthy()

    await act(async () => fireEvent.click(screen.getByRole('radio', { name: 'Prototipo' })))

    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/analytics/offers?source=prototype'),
      expect.anything(),
    )
    expect(await screen.findByRole('table', { name: 'Ofertas del agente por momento' })).toBeTruthy()
    expect(screen.queryByRole('table', { name: 'Sugerencias entre verticales' })).toBeNull()
  })
})
