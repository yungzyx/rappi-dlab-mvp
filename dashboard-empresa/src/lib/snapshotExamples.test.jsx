import { act, screen } from '@testing-library/react'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { renderWithData, resetApi } from '../test/fixtureApi.js'

// Una foto armada con `npm run panel:snapshot:fixtures` (los ejemplos de los tests, sin una base detrás).
vi.mock('virtual:panel-snapshot', async () => {
  const { PANEL_METRICS } = await import('./metrics.js')
  const respuestas = {}
  for (const name of PANEL_METRICS) {
    for (const source of ['synthetic', 'prototype']) {
      const saved = await import(`../fixtures/${name}.${source}.json`).catch(() => null)
      if (saved) respuestas[`${name}.${source}`] = saved.default
    }
  }
  const grabado = { fecha: '2026-11-26', base: 'ejemplos de src/fixtures', origen: 'ejemplos' }
  return { default: { grabado, respuestas } }
})

const { default: App } = await import('../App.jsx')

describe('panel en un solo HTML armado con los ejemplos de los tests', () => {
  afterEach(resetApi)

  test('says it shows test examples, not the panel as it was nor a copy of a base', async () => {
    window.history.replaceState(null, '', '/?fuente=prototipo')
    vi.stubGlobal('fetch', vi.fn())
    await renderWithData(<App />)
    await act(async () => {})

    expect(screen.getByText('Foto de ejemplos:')).toBeTruthy()
    expect(screen.getByText(/respuestas de ejemplo de los tests, no el uso de nadie/)).toBeTruthy()
    expect(screen.queryByText(/el panel como estaba/)).toBeNull()
    expect(screen.getByText('Foto de ejemplos', { selector: '.data-status' })).toBeTruthy()
    const footer = document.querySelector('.site-footer').textContent
    expect(footer).toMatch(/Respuestas de ejemplo de los tests \(src\/fixtures\), armadas el 26-11-2026/)
    expect(footer).not.toMatch(/copia de la base/)
  })
})
