import { act, fireEvent, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import App from '../../App.jsx'
import { apiDown, renderWithData, resetApi, serveFixtures, serveFixturesWith } from '../../test/fixtureApi.js'
import { OFFERS_WITHOUT_MOMENT } from '../../test/oldSynthetic.js'
import { MochiView } from './MochiView.jsx'

const NOT_EVIDENCE = 'Prototipo · no es evidencia'
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

  test('offers by moment: "Plan" with its accepted ones in the third cell, and a dash under the minimum', async () => {
    serveFixtures()
    await renderWithData(<MochiView source="prototype" />)

    const offers = await screen.findByRole('table', { name: 'Ofertas del agente por momento' })
    const [plan, cart] = bodyRows(offers)
    expect(momentName(plan)).toBe('Plan')
    expect(cells(plan).slice(1)).toEqual(['1', '1', '—', '—', '—', '0'])
    expect(momentName(cart)).toBe('Carro')
    // Lo que busca `make mvp-check`: la fila cuyo nombre empieza con "Plan ".
    expect(within(offers).getByRole('row', { name: /^Plan / })).toBe(plan)
    expect(within(plan).getByText('Un kit para una ocasión que la persona elige (carrete, asado)')).toBeTruthy()
  })

  test('the orders Mochi placed alone, with permission, are counted apart from the offers', async () => {
    serveFixtures()
    await renderWithData(<MochiView source="prototype" />)

    const line = await screen.findByTestId('autopedidos')
    expect(line.textContent).toContain('con permiso ("Pedir por mí"): 1 de 1 persona.')
    expect(line.textContent).toContain('No cuentan como ofertas aceptadas.')
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

  test('rejected, opened and opened "¿Por qué?" go after the rate; an older saved response shows a dash', async () => {
    serveFixturesWith(
      offersWith([
        {
          momento: 'carrito',
          mostradas: 4,
          aceptadas: 1,
          rechazadas: 2,
          abiertas: 1,
          por_que_abiertos: 3,
          aceptacion_pct: null,
        },
        { momento: 'recompra', mostradas: 2, aceptadas: 1, aceptacion_pct: null }, // sin las cuentas nuevas
        { momento: 'plan', mostradas: 3, aceptadas: 0, rechazadas: 0, por_que_abiertos: 1, aceptacion_pct: null },
        { momento: 'volver', mostradas: 1, aceptadas: 0, rechazadas: 0, por_que_abiertos: 0, aceptacion_pct: null },
        {
          momento: 'sin_momento',
          mostradas: 3,
          aceptadas: 0,
          rechazadas: 2,
          por_que_abiertos: 0,
          aceptacion_pct: null,
        },
      ]),
    )
    await renderWithData(<MochiView source="prototype" />)

    const offers = await screen.findByRole('table', { name: 'Ofertas del agente por momento' })
    expect(
      within(offers)
        .getAllByRole('columnheader')
        .map((th) => th.textContent),
    ).toEqual([
      'Momento',
      'Mostradas',
      'Aceptadas',
      'Tasa de aceptación',
      'Rechazadas',
      'Abiertas',
      '"¿Por qué?" abiertos',
    ])
    const rows = Object.fromEntries(bodyRows(offers).map((row) => [momentName(row), row]))
    expect(cells(rows.Carro).slice(1)).toEqual(['4', '1', '—', '2', '1', '3'])
    expect(cells(rows.Recompra).slice(4)).toEqual(['—', '—', '—'])
    // El plan no tiene botón para rechazar ni para abrir una vertical: "—", no un 0 que diría que nadie lo hizo. Volver
    // tiene "Después", pero no abre una vertical.
    expect(cells(rows.Plan).slice(4)).toEqual(['—', '—', '1'])
    expect(cells(rows['Volver a pedir']).slice(4)).toEqual(['0', '—', '0'])
    // Sin momento (un origen desconocido) muestra los rechazos que haya; sin ninguno, "—".
    expect(cells(rows['Sin momento']).slice(4)).toEqual(['2', '—', '0'])
    expect(screen.getByText(/Los otros momentos no tienen ese botón y muestran una raya/)).toBeTruthy()
  })

  test('prototype sections carry the not-evidence label', async () => {
    serveFixtures()
    await renderWithData(<MochiView source="prototype" />)

    expect(screen.getAllByText(NOT_EVIDENCE)).toHaveLength(4) // ofertas, si molesta, listas y búsquedas
    expect(screen.queryByText(/datos simulados/i)).toBeNull()
  })

  test('who hid or silenced Mochi, out of the active people, who brought him back and the Home explanations', async () => {
    serveFixturesWith({
      presencia: {
        source: 'prototype',
        data: {
          personas_activas: 8,
          ocultos: 2,
          ocultos_pct: 25,
          ocultadas: 3,
          volvieron: 1,
          silenciadas: 4,
          silenciaron: 3,
          silenciaron_pct: 37.5,
          explicaciones: 5,
          explicaciones_personas: 4,
        },
      },
    })
    await renderWithData(<MochiView source="prototype" />)

    const section = (await screen.findByRole('heading', { name: '¿Mochi molesta?' })).closest('section')
    const figure = (label) => within(section).getByText(label).parentElement.textContent
    expect(figure('Ocultaron a Mochi')).toBe('Ocultaron a Mochi225,0% de 8 personas activas; lo ocultaron 3 veces')
    expect(figure('Lo silenciaron por hoy')).toBe(
      'Lo silenciaron por hoy337,5% de 8 personas activas; lo silenciaron 4 veces',
    )
    expect(figure('Lo volvieron a mostrar')).toBe('Lo volvieron a mostrar1persona, desde Cuenta')
    expect(figure('Mochi explicó el orden de la Home')).toContain('5 vecesa 4 personas')
    expect(within(section).getByText(/la app no anota "¿Por qué\?" ni "Entendido"/)).toBeTruthy()
    expect(within(section).getByText(/Si muchas personas lo ocultan o lo silencian, Mochi molesta/)).toBeTruthy()
  })

  test('the recorded prototype journey: one person silenced him, then hid him, and he explained the Home once', async () => {
    serveFixtures()
    await renderWithData(<MochiView source="prototype" />)

    const section = (await screen.findByRole('heading', { name: '¿Mochi molesta?' })).closest('section')
    expect(within(section).getByText('10,0% de 10 personas activas; lo ocultaron 1 vez')).toBeTruthy()
    expect(within(section).getByText('10,0% de 10 personas activas; lo silenciaron 1 vez')).toBeTruthy()
    expect(within(section).getByText('1 vez')).toBeTruthy()
  })

  test('without hides, silences nor explanations, an empty state (and the simulator does not record them)', async () => {
    const none = {
      personas_activas: 6,
      ocultos: 0,
      ocultos_pct: 0,
      ocultadas: 0,
      volvieron: 0,
      silenciadas: 0,
      silenciaron: 0,
      silenciaron_pct: 0,
      explicaciones: 0,
      explicaciones_personas: 0,
    }
    serveFixturesWith({ presencia: { source: 'prototype', data: none } })
    await renderWithData(<MochiView source="prototype" />)
    expect(await screen.findByText('Nadie ocultó ni silenció a Mochi, ni lo vio mover la Home')).toBeTruthy()
    expect(screen.queryByText('Ocultaron a Mochi')).toBeNull()

    // Los simulados de antes del 14-11-2026 no traían ocultar ni silenciar: lo dice en vez de un 0 %.
    resetApi()
    serveFixturesWith({ presencia: { source: 'synthetic', data: none } })
    await renderWithData(<MochiView source="synthetic" />)
    expect(await screen.findByText('Los datos simulados no registran ocultar ni silenciar a Mochi')).toBeTruthy()
  })

  test('lists: CTR by position and the session funnel, each step out of all sessions', async () => {
    serveFixturesWith({
      'ctr-posicion': {
        source: 'prototype',
        data: {
          posiciones: [
            { posicion: 0, impresiones: 10, clics: 3, ctr: 0.3 },
            { posicion: 1, impresiones: 8, clics: 1, ctr: 0.125 },
          ],
          listas: [],
        },
      },
      'embudo-sesion': {
        source: 'prototype',
        data: [{ modo: 'propuesta', sesiones: 4, vieron: 4, tocaron: 2, agregaron: 1, pidieron: 1 }],
      },
    })
    await renderWithData(<MochiView source="prototype" />)

    const ctr = await screen.findByRole('table', { name: 'CTR por posición en las listas' })
    expect(bodyRows(ctr).map(cells)).toEqual([
      ['1.º', '10', '3', '30,0%'],
      ['2.º', '8', '1', '12,5%'],
    ])
    expect(screen.getByRole('button', { name: 'Ver tabla de CTR por posición' })).toBeTruthy()
    const funnel = screen.getByRole('table', { name: 'Embudo por sesión' })
    expect(bodyRows(funnel).map((row) => cells(row)[2])).toEqual(['100,0%', '100,0%', '50,0%', '25,0%', '25,0%'])
  })

  test('synthetic without moments: the cross suggestions carry the section', async () => {
    // Los simulados de antes del 14-11-2026 no guardaban el momento de la oferta: todo caía en "sin momento".
    serveFixturesWith({ offers: { source: 'synthetic', data: OFFERS_WITHOUT_MOMENT } })
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
    expect(cells(next).slice(1)).toEqual(['96,6%', '84,0%Orden fijo', '+12,6 puntos (mejora)'])
    expect(within(next).getByText(/\(505 personas\)$/)).toBeTruthy()
    expect(screen.getByText(/prueba la mecánica del motor, no su efecto/)).toBeTruthy()
    resetApi()

    serveFixtures() // los guardados: el motor corrió sin 84 días de pedidos
    await renderWithData(<MochiView source="synthetic" />)
    expect(screen.getByText('Sin evaluación todavía')).toBeTruthy()
  })

  test('each motor row says how many people it is measured on, and the step gap of 74 people is not painted', async () => {
    const saved = (await import('../../fixtures/sin-conexion/motor.json')).default
    serveFixturesWith({ motor: { source: saved.source, data: saved.data } })
    await renderWithData(<MochiView source="synthetic" />)

    const motor = screen.getByRole('table', { name: 'El motor contra una regla simple' })
    const step = within(motor).getByRole('row', { name: /^Qué vertical sumar a su combinación/ })
    expect(within(step).getByText(/\(74 personas\)$/)).toBeTruthy()
    expect(within(step).getByText('no es concluyente')).toBeTruthy()
    const gap = within(step).getByText('−5,4 puntos').closest('.delta')
    expect(gap.classList.contains('status--bad')).toBe(false)
    expect(gap.textContent).not.toMatch(/mejora|empeora/)
    // Delta no es hijo directo de la grilla: ahí dejaría de ser inline-flex y no se alinearía a la derecha.
    for (const delta of motor.querySelectorAll('.delta')) {
      expect(delta.parentElement.classList.contains('cell-stack')).toBe(false)
    }
    // La nota bajo la tabla ya no le atribuye a toda la tabla las personas de la primera fila.
    const note = screen.getByText(/^Se mide con pedidos posteriores a los que usó para aprender\. Corrida del/)
    expect(note.textContent).not.toContain('505 personas')
    resetApi()

    // Con la prueba de McNemar de la API, la diferencia dice su p.
    const evaluacion = { ...saved.data.evaluacion, paso: { ...saved.data.evaluacion.paso, p_mcnemar: 0.4237 } }
    serveFixturesWith({ motor: { source: saved.source, data: { ...saved.data, evaluacion } } })
    await renderWithData(<MochiView source="synthetic" />)
    expect(screen.getByText('no es concluyente (p = 0,42)')).toBeTruthy()
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

  test('search abandonment: the % from 10 searches, before that the count, and the rescued ones', async () => {
    const abandono = { busquedas: 61, con_clic: 35, rescatadas: 1, abandonadas: 25, abandono_pct: 41, plazo_minutos: 2 }
    const data = { personas: 9, busquedas: 70, sin_resultado: 4, por_vertical: [], abandono }
    serveFixturesWith({ unmet: { source: 'prototype', data } })
    const { unmount } = await renderWithData(<MochiView source="prototype" />)

    expect(await screen.findByText('Abandono de búsqueda')).toBeTruthy()
    expect(screen.getByText('41,0%')).toBeTruthy()
    expect(screen.getByText('de 61 búsquedas; 1 se salvó al reformular')).toBeTruthy()
    expect(screen.getByLabelText('Ayuda: Abandono de búsqueda')).toBeTruthy()
    expect(screen.getByText(/ni en otra búsqueda con toque en 2 minutos\./)).toBeTruthy()
    unmount()

    const few = { ...abandono, busquedas: 3, con_clic: 1, rescatadas: 0, abandonadas: 2, abandono_pct: null }
    serveFixturesWith({ unmet: { source: 'prototype', data: { ...data, abandono: few } } })
    await renderWithData(<MochiView source="prototype" />)
    expect(await screen.findByText('2 de 3')).toBeTruthy()
  })

  test('with the API down and the prototype source no saved figures appear', async () => {
    window.history.replaceState(null, '', '/?vista=mochi&fuente=prototipo')
    apiDown()
    await renderWithData(<App />)

    expect(within(await screen.findByRole('alert')).getByText(OFFLINE, { exact: false })).toBeTruthy()
    expect(screen.getAllByText('Sin conexión con la API').length).toBeGreaterThan(1)
    expect(screen.queryByRole('table', { name: 'Ofertas del agente por momento' })).toBeNull()
    expect(screen.queryByText('Modo sin conexión (datos guardados):')).toBeNull() // no hay nada guardado que avisar
  })

  test('a response from the other source is discarded instead of shown', async () => {
    const synthetic = (await import('../../fixtures/offers.synthetic.json')).default
    serveFixturesWith({ offers: synthetic }) // la API contesta "simulado" también a ?source=prototype
    await renderWithData(<MochiView source="prototype" />)

    expect(screen.getAllByText('Sin conexión con la API').length).toBeGreaterThan(0)
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
