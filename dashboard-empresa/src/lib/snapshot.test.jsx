import { act, fireEvent, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { renderWithData, resetApi } from '../test/fixtureApi.js'
import { PANEL_METRICS } from './metrics.js'

// El panel en un solo HTML (npm run panel:html): las respuestas llegan grabadas por el módulo virtual, no por la red.
// La fábrica sube al comienzo del archivo: lo que usa lo importa adentro.
vi.mock('virtual:panel-snapshot', async () => {
  const { PANEL_METRICS } = await import('./metrics.js')
  const kpis = (await import('../fixtures/kpis.synthetic.json')).default
  const respuestas = {}
  for (const name of PANEL_METRICS) {
    for (const source of ['synthetic', 'prototype']) {
      const saved = await import(`../fixtures/${name}.${source}.json`).catch(() => null)
      if (saved) respuestas[`${name}.${source}`] = saved.default
    }
  }
  respuestas['kpis.synthetic'] = { ...kpis, data: { ...kpis.data, usuarios_activos: 4242 } }
  respuestas['trends.prototype'] = { source: 'synthetic', data: [] } // de la otra fuente: no se muestra
  delete respuestas['assortment.prototype'] // una respuesta que falta en la foto
  return { default: { grabado: { fecha: '2026-10-23', base: 'rappi_staging' }, respuestas } }
})

const { loadAnalytics, SNAPSHOT_INFO } = await import('./api.js')
vi.stubEnv('MODE', 'panel-html') // el armado del HTML suelto trae «Ver cómo funciona»; se lee al cargar App
const { default: App } = await import('../App.jsx')

describe('panel en un solo HTML', () => {
  afterEach(resetApi)

  test('reads the recorded answers and never the network', async () => {
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)

    const result = await loadAnalytics('kpis', 'synthetic')

    expect(result.data.usuarios_activos).toBe(4242)
    expect(result.offline).toBe(false)
    expect(fetch).not.toHaveBeenCalled()
    expect(SNAPSHOT_INFO).toEqual({ fecha: '2026-10-23', base: 'rappi_staging' })
  })

  test('a recorded answer from the other source is refused, and a missing one says so', async () => {
    await expect(loadAnalytics('trends', 'prototype')).rejects.toThrow('Se esperaba la fuente prototype')
    await expect(loadAnalytics('assortment', 'prototype')).rejects.toThrow('Este archivo no trae «assortment»')
  })

  test('the shell says it is a photo: date and copy of the base, no refresh and no presentation link', async () => {
    window.history.replaceState(null, '', '/')
    vi.stubGlobal('fetch', vi.fn())
    await renderWithData(<App />)
    await act(async () => {})

    expect(screen.getByText('Foto sin conexión:')).toBeTruthy()
    expect(screen.getByText(/grabadas el 23-10-2026 desde una copia de la base \(rappi_staging\)/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Actualizar' })).toBeNull()
    expect(screen.queryByRole('link', { name: 'Presentación de la propuesta' })).toBeNull()
    expect(screen.getByText('Usuarios y eventos SIMULADOS:')).toBeTruthy()
    expect(globalThis.fetch).not.toHaveBeenCalled()
  })
})

describe('Ver cómo funciona', () => {
  afterEach(resetApi)

  const planRow = async () => {
    const offers = await screen.findByRole('table', { name: 'Ofertas del agente por momento' })
    const plan = within(offers).getByRole('row', { name: /^Plan / })
    return within(plan)
      .getAllByRole('cell')
      .map((cell) => cell.textContent)
      .slice(1, 3)
  }

  test('a short journey adds example events to the photo, labelled as a demonstration, and closing undoes them', async () => {
    window.history.replaceState(null, '', '/')
    vi.stubGlobal('fetch', vi.fn())
    await renderWithData(<App />)

    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Ver cómo funciona' })))
    const tour = screen.getByRole('complementary', { name: 'Ver cómo funciona' })
    expect(within(tour).getByText('Demostración')).toBeTruthy()
    expect(within(tour).getByText('Eventos de ejemplo sobre la foto grabada: no son datos reales.')).toBeTruthy()
    expect(window.location.search).toBe('?vista=mochi&fuente=prototipo')
    expect(await planRow()).toEqual(['1', '1']) // lo grabado: 1 mostrada, 1 aceptada
    const advance = within(tour).getByRole('button', { name: 'Empezar' })
    expect(document.activeElement).toBe(advance) // el foco queda en la tarjeta, no en el título de la sección

    expect(screen.queryByText(/con eventos de ejemplo de la demostración/)).toBeNull() // todavía es la foto

    await act(async () => fireEvent.click(within(tour).getByRole('button', { name: 'Empezar' })))
    expect(within(tour).getByText('Paso 1 de 4')).toBeTruthy()
    expect(await planRow()).toEqual(['2', '1'])
    // Cada sección del prototipo dice que trae eventos de ejemplo, no solo la tarjeta.
    expect(screen.getAllByText(/con eventos de ejemplo de la demostración: no son datos reales/)).toHaveLength(2)

    await act(async () => fireEvent.click(within(tour).getByRole('button', { name: 'Siguiente' })))
    expect(await planRow()).toEqual(['2', '2'])
    expect(document.activeElement).toBe(advance)

    // Paso 3: el pedido cuenta en la frecuencia de 30 días del Resumen.
    await act(async () => fireEvent.click(within(tour).getByRole('button', { name: 'Siguiente' })))
    expect(window.location.search).toBe('?vista=resumen&fuente=prototipo')
    const frequency = await screen.findByRole('article', { name: 'Frecuencia (30 días)' })
    expect(within(frequency).getByText(/4 pedidos de 7 personas/)).toBeTruthy() // lo grabado: 3 de 6

    // Paso 4: una búsqueda sin resultado más en «Qué buscan y no encuentran»; el botón ya dice «Terminar».
    await act(async () => fireEvent.click(within(tour).getByRole('button', { name: 'Siguiente' })))
    expect(within(tour).getByRole('button', { name: 'Terminar' })).toBe(advance)
    expect(window.location.search).toBe('?vista=mochi&fuente=prototipo')
    expect(await screen.findByText('2 de 2')).toBeTruthy() // lo grabado: 1 de 1

    await act(async () => fireEvent.keyDown(document.body, { key: 'Escape' })) // Escape cierra desde cualquier parte
    expect(screen.queryByRole('complementary', { name: 'Ver cómo funciona' })).toBeNull()
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Ver cómo funciona' }))
    expect(await planRow()).toEqual(['1', '1'])
    expect(globalThis.fetch).not.toHaveBeenCalled()
  })
})

describe('PANEL_METRICS', () => {
  test('lists every metric the views ask for: the photo records exactly those', () => {
    const sources = import.meta.glob('../**/*.jsx', { query: '?raw', import: 'default', eager: true })
    const asked = new Set()
    for (const [file, code] of Object.entries(sources)) {
      if (file.includes('.test.')) continue
      for (const [, name] of code.matchAll(/useAnalytics\('([\w-]+)'/g)) asked.add(name)
      for (const [, list] of code.matchAll(/useAnalyticsMany\(\s*\[([^\]]+)\]/g))
        for (const [, name] of list.matchAll(/'([\w-]+)'/g)) asked.add(name)
    }

    expect(asked.size).toBeGreaterThan(5)
    expect([...asked].filter((name) => !PANEL_METRICS.includes(name))).toEqual([])
    expect(PANEL_METRICS.filter((name) => !asked.has(name))).toEqual([])
  })
})
