// Para los tests de render: una API falsa que responde con las respuestas guardadas en src/fixtures.
import { act, cleanup, render } from '@testing-library/react'
import { vi } from 'vitest'
import { retryConnection } from '../lib/api.js'

const fixtures = import.meta.glob('../fixtures/*.json', { eager: true, import: 'default' })

function fixtureFor(url) {
  const { pathname, searchParams } = new URL(url)
  const name = pathname.replace('/analytics/', '')
  return fixtures[`../fixtures/${name}.${searchParams.get('source')}.json`]
}

/** La API "responde" con los fixtures (camino en vivo, sin red). */
export function serveFixtures() {
  retryConnection()
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url) => {
      const body = fixtureFor(url)
      return { ok: Boolean(body), status: body ? 200 : 404, json: async () => body ?? {} }
    }),
  )
}

/** La API "responde" con los fixtures, salvo lo que se le pase (`overrides`: nombre de la métrica → cuerpo completo). */
export function serveFixturesWith(overrides) {
  serveFixtures()
  const fixtures = globalThis.fetch
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url) => {
      const name = new URL(url).pathname.replace('/analytics/', '')
      return name in overrides ? { ok: true, status: 200, json: async () => overrides[name] } : fixtures(url)
    }),
  )
}

/** La API está caída: el panel debe caer a los datos guardados. */
export function apiDown() {
  retryConnection()
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))),
  )
}

/**
 * Render que espera los datos: con use() de React 19 hay que esperar el act para que el componente
 * suspendido se reanude cuando la promesa resuelve.
 */
export async function renderWithData(ui) {
  let result
  await act(async () => {
    result = render(ui)
  })
  return result
}

export function resetApi() {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
}
