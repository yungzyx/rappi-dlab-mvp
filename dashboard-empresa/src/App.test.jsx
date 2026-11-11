import { act, fireEvent, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import App, { VIEWS } from './App.jsx'
import { apiDown, renderWithData, resetApi, serveFixtures, serveFixturesWith } from './test/fixtureApi.js'

describe('App', () => {
  beforeEach(() => {
    window.history.replaceState(null, '', '/')
    vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  afterEach(resetApi)

  test('four views, the simulated notice is permanent and the tabs work with the keyboard', async () => {
    serveFixtures()
    await renderWithData(<App />)

    expect(screen.getByText('Datos simulados:')).toBeTruthy()
    expect(screen.getAllByRole('tab').map((tab) => tab.getAttribute('aria-label'))).toEqual([
      'Resumen',
      'Retención y venta cruzada',
      'Mochi y búsquedas',
      'Experimentos',
    ])
    const summaryTab = screen.getByRole('tab', { name: 'Resumen' })
    expect(summaryTab.getAttribute('aria-selected')).toBe('true')

    await act(async () => fireEvent.keyDown(summaryTab, { key: 'ArrowRight' }))
    const customersTab = screen.getByRole('tab', { name: 'Retención y venta cruzada' })
    expect(customersTab.getAttribute('aria-selected')).toBe('true')
    expect(document.activeElement).toBe(customersTab)
    expect(screen.getByRole('tabpanel').id).toBe('panel-clientes')
    expect(window.location.search).toContain('vista=clientes')

    await act(async () => fireEvent.keyDown(customersTab, { key: 'ArrowRight' }))
    expect(screen.getByRole('tab', { name: 'Mochi y búsquedas' }).getAttribute('aria-selected')).toBe('true')
    expect(await screen.findByRole('heading', { name: 'Lo que ofrece Mochi' })).toBeTruthy()

    await act(async () => fireEvent.keyDown(screen.getByRole('tab', { name: 'Mochi y búsquedas' }), { key: 'End' }))
    expect(screen.getByRole('tab', { name: 'Experimentos' }).getAttribute('aria-selected')).toBe('true')
    expect(await screen.findByRole('heading', { name: 'Experimentos del MVP' })).toBeTruthy()
    expect(screen.getByText('Datos simulados:')).toBeTruthy()
  })

  test('ArrowDown and ArrowUp also move between the tabs (the side navigation is vertical)', async () => {
    serveFixtures()
    await renderWithData(<App />)

    await act(async () => fireEvent.keyDown(screen.getByRole('tab', { name: 'Resumen' }), { key: 'ArrowDown' }))
    const customersTab = screen.getByRole('tab', { name: 'Retención y venta cruzada' })
    expect(customersTab.getAttribute('aria-selected')).toBe('true')
    expect(document.activeElement).toBe(customersTab)

    await act(async () => fireEvent.keyDown(customersTab, { key: 'ArrowUp' }))
    expect(screen.getByRole('tab', { name: 'Resumen' }).getAttribute('aria-selected')).toBe('true')
  })

  test('each sub-tab shows the headings of its sections', async () => {
    for (const { id, tabs } of VIEWS) {
      for (const tab of tabs) {
        window.history.replaceState(null, '', `/?vista=${id}&seccion=${tab.id}`)
        serveFixtures()
        const { unmount } = await renderWithData(<App />)
        for (const section of tab.sections) {
          expect(document.getElementById(section)?.tagName, `${id}/${tab.id}#${section}`).toBe('H2')
        }
        const nav = screen.queryByRole('navigation', { name: 'Secciones de esta vista' })
        if (tabs.length > 1) {
          const buttons = within(nav).getAllByRole('button')
          expect(buttons.map((button) => button.textContent)).toEqual(tabs.map((item) => item.label))
          expect(buttons.filter((button) => button.getAttribute('aria-current') === 'page')).toEqual([
            within(nav).getByRole('button', { name: tab.label }),
          ])
        } else {
          expect(nav).toBeNull()
        }
        unmount()
        resetApi()
      }
    }
  })

  test('a sub-tab changes the section and the link', async () => {
    window.history.replaceState(null, '', '/?vista=mochi')
    serveFixtures()
    await renderWithData(<App />)

    const nav = screen.getByRole('navigation', { name: 'Secciones de esta vista' })
    await act(async () => fireEvent.click(within(nav).getByRole('button', { name: 'Búsquedas' })))

    expect(screen.getByRole('tabpanel').id).toBe('panel-mochi')
    expect(screen.getByRole('heading', { name: 'Qué buscan y no encuentran' })).toBeTruthy()
    expect(screen.queryByRole('heading', { name: 'Lo que ofrece Mochi' })).toBeNull()
    expect(window.location.search).toBe('?vista=mochi&fuente=simulados&seccion=busquedas')

    await act(async () => fireEvent.click(within(nav).getByRole('button', { name: 'Ofertas' })))
    expect(window.location.search).toBe('?vista=mochi&fuente=simulados')
  })

  test('an unknown section in the link opens the first sub-tab', async () => {
    window.history.replaceState(null, '', '/?vista=clientes&seccion=otra')
    serveFixtures()
    await renderWithData(<App />)

    expect(screen.getByRole('heading', { name: 'Dónde está la venta cruzada' })).toBeTruthy()
    expect(window.location.search).toBe('?vista=clientes&fuente=simulados')
  })

  test('the header and the footer say it is a dLab prototype with Rappi, not official, and the footer links the presentation', async () => {
    serveFixtures()
    await renderWithData(<App />)

    expect(document.querySelector('.masthead').textContent).toContain('Prototipo dLab con Rappi, no oficial')
    expect(screen.getByText('Prototipo dLab con Rappi · demo, no es un producto oficial de Rappi.')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Presentación de la propuesta' }).getAttribute('href')).toBe(
      `${import.meta.env.BASE_URL}presentacion.html`,
    )
  })

  test('the page title is the name of the view', async () => {
    serveFixtures()
    await renderWithData(<App />)

    expect(screen.getByRole('heading', { level: 1, name: 'Resumen' })).toBeTruthy()
    await act(async () => fireEvent.click(screen.getByRole('tab', { name: 'Mochi y búsquedas' })))
    expect(screen.getByRole('heading', { level: 1, name: 'Mochi y búsquedas' })).toBeTruthy()
  })

  test('the header says the date of the catalog prices, and nothing when the API does not', async () => {
    const catalogo = { desde: '2026-10-18', hasta: '2026-10-18', verticales: {} }
    serveFixturesWith({ '/catalog/home': { nearby_stores: [], catalogo } })
    await renderWithData(<App />)

    expect(document.querySelector('.masthead-catalog').textContent).toBe('Precios de Rappi Chile al 18-10-2026')
    expect(globalThis.fetch.mock.calls.filter(([url]) => url.endsWith('/catalog/home'))).toHaveLength(1)
    resetApi()

    apiDown()
    await renderWithData(<App />)
    expect(await screen.findByText('Modo sin conexión (datos guardados):')).toBeTruthy()
    expect(document.querySelector('.masthead-catalog')).toBeNull()
  })

  test('only the active tab has aria-controls (the other panels are not in the DOM)', async () => {
    serveFixtures()
    await renderWithData(<App />)

    const controls = screen.getAllByRole('tab').map((tab) => tab.getAttribute('aria-controls'))
    expect(controls.filter(Boolean)).toEqual(['panel-resumen'])
    expect(document.getElementById('panel-resumen')).toBe(screen.getByRole('tabpanel'))
  })

  test('an unknown view in the link (?vista=otra) opens the Resumen and keeps the source', async () => {
    window.history.replaceState(null, '', '/?vista=otra&fuente=prototipo')
    serveFixtures()
    await renderWithData(<App />)

    expect(screen.getByRole('tabpanel').id).toBe('panel-resumen')
    expect(window.location.search).toBe('?vista=resumen&fuente=prototipo')
  })

  test('a decision links to its detail: the view changes and the section heading gets the focus', async () => {
    serveFixtures()
    await renderWithData(<App />)

    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Ver la escalera' })))

    expect(screen.getByRole('tabpanel').id).toBe('panel-clientes')
    expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Dónde está la venta cruzada' }))

    await act(async () => fireEvent.click(screen.getByRole('tab', { name: 'Resumen' })))
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Ver las búsquedas' })))
    expect(screen.getByRole('tabpanel').id).toBe('panel-mochi')
    expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Qué buscan y no encuentran' }))
    expect(window.location.search).toContain('seccion=busquedas')
  })

  test('switching to Prototipo changes the notice and the URL', async () => {
    serveFixtures()
    await renderWithData(<App />)

    await act(async () => fireEvent.click(screen.getByRole('radio', { name: 'Prototipo' })))

    expect(screen.getByText('Datos del prototipo:')).toBeTruthy()
    expect(screen.getByText('uso del MVP, pocas personas: no es evidencia')).toBeTruthy()
    expect(window.location.search).toContain('fuente=prototipo')
    expect(
      await screen.findByText(
        'Nadie pasó el doble de su ritmo sin pedir: el ritmo necesita al menos dos compras por persona.',
      ),
    ).toBeTruthy()
  })

  test('"Actualizar" brings what is new in the prototype without reloading the page', async () => {
    window.history.replaceState(null, '', '/?vista=mochi&fuente=prototipo')
    serveFixtures()
    await renderWithData(<App />)
    expect(await screen.findByText('Sin sugerencias entre verticales que evaluar')).toBeTruthy()

    // Mientras tanto se hace la demo en el prototipo: la API ya cuenta la sugerencia mostrada.
    const fixtures = globalThis.fetch
    const demo = [
      {
        concepto: '🥤 Bebidas gaseosas',
        vertical: 'licores',
        mostradas: 2,
        aceptadas: 1,
        ignoradas: 0,
        convertidas: 1,
        aceptacion_pct: null,
      },
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url) =>
        url.includes('/analytics/suggestions')
          ? { ok: true, status: 200, json: async () => ({ source: 'prototype', data: demo }) }
          : fixtures(url),
      ),
    )
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Actualizar' })))

    expect(await screen.findByRole('table', { name: 'Sugerencias entre verticales' })).toBeTruthy()
    expect(screen.queryByText('Sin sugerencias entre verticales que evaluar')).toBeNull()
  })

  test('an empty state is static text: it is not announced as a live region', async () => {
    window.history.replaceState(null, '', '/?vista=mochi&fuente=simulados')
    serveFixtures()
    await renderWithData(<App />)

    const empty = (await screen.findByText('Los datos simulados no registran el momento de la oferta')).closest(
      '.state',
    )
    expect(empty.getAttribute('role')).toBeNull()
  })

  test('with the prototype source and the API down there is a single alert, and the header gets no error box', async () => {
    window.history.replaceState(null, '', '/?vista=mochi&fuente=prototipo')
    vi.spyOn(console, 'error').mockImplementation(() => {}) // el límite de error de cada bloque lo registra
    apiDown()
    await renderWithData(<App />)

    const [alert, ...others] = await screen.findAllByRole('alert')
    expect(others).toHaveLength(0)
    expect(within(alert).getByRole('button', { name: 'Reintentar' })).toBeTruthy()
    expect(screen.getAllByRole('button', { name: 'Reintentar' })).toHaveLength(1)
    const header = document.querySelector('.page-head')
    expect(header.textContent).not.toContain('No se pudieron cargar')
    expect(header.textContent).toContain('fecha de corte: sin conexión')

    // Reintentar con la API de vuelta: el aviso se va y el encabezado vuelve a decir la fecha.
    serveFixtures()
    await act(async () => fireEvent.click(within(alert).getByRole('button', { name: 'Reintentar' })))
    expect(screen.queryByRole('alert')).toBeNull()
    expect(header.textContent).toContain('Datos al')
  })

  test('with the API down it uses the saved data and says so', async () => {
    apiDown()
    await renderWithData(<App />)

    expect(await screen.findByText('Modo sin conexión (datos guardados):')).toBeTruthy()
    expect(await screen.findByText('62,6%')).toBeTruthy()
  })
})
