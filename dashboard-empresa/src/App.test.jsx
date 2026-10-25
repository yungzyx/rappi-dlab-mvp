import { act, fireEvent, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import App from './App.jsx'
import { apiDown, renderWithData, resetApi, serveFixtures } from './test/fixtureApi.js'

describe('App', () => {
  beforeEach(() => {
    window.history.replaceState(null, '', '/')
    vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  afterEach(resetApi)

  test('three views, the simulated notice is permanent and the tabs work with the keyboard', async () => {
    serveFixtures()
    await renderWithData(<App />)

    expect(screen.getByText('Usuarios y eventos SIMULADOS:')).toBeTruthy()
    expect(screen.getAllByRole('tab').map((tab) => tab.getAttribute('aria-label'))).toEqual([
      'Resumen',
      'Retención y venta cruzada',
      'Mochi y búsquedas',
    ])
    const summaryTab = screen.getByRole('tab', { name: 'Resumen' })
    expect(summaryTab.getAttribute('aria-selected')).toBe('true')

    await act(async () => fireEvent.keyDown(summaryTab, { key: 'ArrowRight' }))
    const customersTab = screen.getByRole('tab', { name: 'Retención y venta cruzada' })
    expect(customersTab.getAttribute('aria-selected')).toBe('true')
    expect(document.activeElement).toBe(customersTab)
    expect(screen.getByRole('tabpanel').id).toBe('panel-clientes')
    expect(window.location.search).toContain('vista=clientes')

    await act(async () => fireEvent.keyDown(customersTab, { key: 'End' }))
    expect(screen.getByRole('tab', { name: 'Mochi y búsquedas' }).getAttribute('aria-selected')).toBe('true')
    expect(await screen.findByRole('heading', { name: 'Lo que ofrece Mochi' })).toBeTruthy()
    expect(screen.getByText('Usuarios y eventos SIMULADOS:')).toBeTruthy()
  })

  test('the header and the footer say it is an independent prototype, and the footer links the presentation', async () => {
    serveFixtures()
    await renderWithData(<App />)

    expect(document.querySelector('.masthead').textContent).toContain('Prototipo independiente, no afiliado a Rappi')
    expect(screen.getByText('Demo no oficial · prototipo independiente, no afiliado a Rappi.')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Presentación de la propuesta' }).getAttribute('href')).toBe(
      `${import.meta.env.BASE_URL}presentacion.html`,
    )
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
  })

  test('switching to Prototipo changes the notice and the URL', async () => {
    serveFixtures()
    await renderWithData(<App />)

    await act(async () => fireEvent.click(screen.getByRole('radio', { name: 'Prototipo' })))

    expect(screen.getByText('Usuarios y eventos del PROTOTIPO:')).toBeTruthy()
    expect(window.location.search).toContain('fuente=prototipo')
    expect(
      await screen.findByText(
        'Nadie pasó el doble de su ritmo sin pedir: el ritmo necesita al menos dos compras por persona.',
      ),
    ).toBeTruthy()
  })

  test('«Actualizar» brings what is new in the prototype without reloading the page', async () => {
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

  test('with the API down it uses the saved data and says so', async () => {
    apiDown()
    await renderWithData(<App />)

    expect(await screen.findByText('Modo sin conexión (datos guardados):')).toBeTruthy()
    expect(await screen.findByText('62,6%')).toBeTruthy()
  })
})
