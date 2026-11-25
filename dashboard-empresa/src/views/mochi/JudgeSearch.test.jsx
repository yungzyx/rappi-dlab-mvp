import { act, fireEvent, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { renderWithData, resetApi } from '../../test/fixtureApi.js'
import { JudgeSearch } from './JudgeSearch.jsx'
import { nextUnjudged, shortcutLevel } from './judging.js'

const pair = (id, consulta, nombre, juicio = null) => ({
  id,
  consulta,
  vertical: 'supermercado',
  nombre,
  presentacion: null,
  tienda: 'Súper',
  precio: 1990,
  imagen: null,
  categoria: 'Snacks salados',
  juicio,
})

const PAIRS = {
  juez: 'J1',
  muestra: 4,
  fuera_del_catalogo: 1,
  pares: [
    pair('P0000000001', 'papas fritas', 'Papas Lays 180 g', 2),
    pair('P0000000002', 'ramitas', 'Ramitas Evercrisp 250 g'),
    pair('P0000000003', 'gaseosa', 'Coca-Cola 1,5 L'),
  ],
}

/** Una API falsa: responde la lista y anota cada juicio que se guarda. */
function serveJudging(saved = []) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url, options = {}) => {
      const { pathname, searchParams } = new URL(url)
      if (options.method === 'PUT') {
        const body = JSON.parse(options.body)
        saved.push([pathname.split('/').pop(), body.nivel, body.juez])
        return { ok: true, status: 200, json: async () => ({ juzgados: saved.length }) }
      }
      expect(searchParams.get('juez')).toBe('J1')
      return { ok: true, status: 200, json: async () => PAIRS }
    }),
  )
  return saved
}

describe('JudgeSearch', () => {
  beforeEach(() => window.localStorage.setItem('panel-juez-busqueda', 'J1'))

  afterEach(() => {
    window.localStorage.clear()
    resetApi()
  })

  test('starts at the first unjudged pair, blind: no position, method or other verdict', async () => {
    serveJudging()
    await renderWithData(<JudgeSearch />)

    expect(screen.getByText('"ramitas"')).toBeTruthy()
    expect(screen.getByText('Ramitas Evercrisp 250 g')).toBeTruthy()
    expect(screen.getByText('1 de 3 pares juzgados')).toBeTruthy()
    expect(screen.getByText(/1 de los 4 pares de la muestra no se pueden juzgar/)).toBeTruthy()
    // La tarjeta y los botones: nada del método, la posición ni otro juez (la ayuda sí lo menciona, para decirlo).
    expect(document.querySelector('.judge-card').textContent).not.toMatch(/posici|híbrido|léxic|LLM|concepto/i)
  })

  test('the buttons and the keys 2/1/0 save and move to the next unjudged pair', async () => {
    const saved = serveJudging()
    await renderWithData(<JudgeSearch />)

    await act(async () => fireEvent.click(screen.getByRole('button', { name: /^A medias/ })))
    expect(saved).toEqual([['P0000000002', 1, 'J1']])
    expect(screen.getByText('"gaseosa"')).toBeTruthy()
    expect(screen.getByRole('status').textContent).toBe('Guardado: A medias. 2 de 3.')

    await act(async () => fireEvent.keyDown(window, { key: '0' }))
    expect(saved.at(-1)).toEqual(['P0000000003', 0, 'J1'])
    expect(screen.getByText('Juzgaste los 3 pares.')).toBeTruthy()
    // Todos juzgados: se queda en el último, con su juicio marcado, y se puede volver atrás.
    expect(screen.getByRole('button', { name: /^No sirve/ }).getAttribute('aria-pressed')).toBe('true')
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Anterior' })))
    expect(screen.getByText('"ramitas"')).toBeTruthy()
    expect(screen.getByRole('button', { name: /^A medias/ }).getAttribute('aria-pressed')).toBe('true')
  })

  test('skip moves without saving', async () => {
    const saved = serveJudging()
    await renderWithData(<JudgeSearch />)

    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Saltar' })))
    expect(screen.getByText('"gaseosa"')).toBeTruthy()
    expect(saved).toEqual([])
  })

  test('without a label it asks for one first, and refuses a name or an email', async () => {
    window.localStorage.clear()
    serveJudging()
    await renderWithData(<JudgeSearch />)

    const input = screen.getByLabelText('Rótulo del juez')
    fireEvent.change(input, { target: { value: 'ana@correo.cl' } })
    expect(screen.getByRole('button', { name: 'Empezar' }).disabled).toBe(true)
    fireEvent.change(input, { target: { value: 'J1' } })
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Empezar' })))
    expect(screen.getByText('"ramitas"')).toBeTruthy()
    expect(window.localStorage.getItem('panel-juez-busqueda')).toBe('J1')
  })

  test('without the analytics routes it says so', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) })),
    )
    await renderWithData(<JudgeSearch />)
    expect(screen.getByRole('alert').textContent).toMatch(/API_ENABLE_ANALYTICS/)
  })
})

describe('judging helpers', () => {
  test('nextUnjudged wraps around and says -1 when all are judged', () => {
    const pairs = [{ id: 'a' }, { id: 'b' }, { id: 'c' }]
    expect(nextUnjudged(pairs, { a: 2 }, 0)).toBe(1)
    expect(nextUnjudged(pairs, { b: 2, c: 0 }, 1)).toBe(0)
    expect(nextUnjudged(pairs, { a: 2, b: 1, c: 0 })).toBe(-1)
  })

  test('a shortcut never fires while typing or with a modifier', () => {
    const input = document.createElement('input')
    expect(shortcutLevel({ key: '2', target: document.body })).toBe(2)
    expect(shortcutLevel({ key: '0', target: document.body })).toBe(0)
    expect(shortcutLevel({ key: '3', target: document.body })).toBeNull()
    expect(shortcutLevel({ key: '1', target: input })).toBeNull()
    expect(shortcutLevel({ key: '1', target: document.body, metaKey: true })).toBeNull()
  })
})
