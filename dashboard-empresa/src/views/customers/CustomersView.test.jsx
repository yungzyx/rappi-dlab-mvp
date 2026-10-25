import { act, fireEvent, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { renderWithData, resetApi, serveFixtures, serveFixturesWith } from '../../test/fixtureApi.js'
import { CustomersView } from './CustomersView.jsx'

const NOT_EVIDENCE = 'uso del MVP, pocas personas: no es evidencia'
const section = (name) => screen.getByRole('region', { name })

describe('CustomersView', () => {
  beforeEach(() => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  afterEach(resetApi)

  test('the Rappi ladder: each combination with its retention and the next one, as Rappi data', async () => {
    serveFixtures()
    await renderWithData(<CustomersView source="synthetic" />)

    const ladder = section('Dónde está la venta cruzada')
    expect(within(ladder).getByText('Dato de Rappi')).toBeTruthy()
    expect(
      within(ladder).getByText(
        'Solo Restaurantes, 62,6% de los usuarios: vuelve al mes siguiente el 47%; quienes además usan Turbo, el 82%. Pedidos por usuario: 1,9 y 5,5.',
      ),
    ).toBeTruthy()
    expect(within(ladder).getAllByRole('listitem')).toHaveLength(6)
    expect(within(ladder).getAllByText(/Es una correlación, no un efecto\./).length).toBeGreaterThan(0)
  })

  test('the ladder table is the full Rappi table with its total', async () => {
    serveFixtures()
    await renderWithData(<CustomersView source="synthetic" />)

    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Ver tabla' })))

    const table = screen.getByRole('table', { name: 'Combinaciones de verticales de Rappi' })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(9)
    expect(within(rows.at(-1)).getByText('Todo Chile')).toBeTruthy()
  })

  test('who we are losing: the counts, who to invite back and what they ordered, grouped', async () => {
    serveFixtures()
    await renderWithData(<CustomersView source="synthetic" />)

    const losing = section('A quién estamos perdiendo')
    expect(within(losing).getByText('280')).toBeTruthy()
    expect(within(losing).getByText('564')).toBeTruthy()
    expect(within(losing).getByText('Califican para «¿Volvemos a…?»')).toBeTruthy()
    expect(within(losing).getByText(/el último día de los pedidos simulados/)).toBeTruthy()

    const audiences = within(losing).getByRole('table', { name: 'Personas en riesgo o perdidas por lo que más pedían' })
    const [first] = within(audiences).getAllByRole('row').slice(1)
    expect(within(first).getAllByRole('cell')[0].textContent).toBe('🍕 Pizza')
    expect(within(first).getAllByRole('cell')[1].textContent).toBe('28')
    // todas las de la lista están en riesgo: la columna «En riesgo» repetiría «Personas»
    expect(within(audiences).queryByRole('columnheader', { name: 'En riesgo' })).toBeNull()
    expect(within(losing).getByText(/Muestra de 100 de las 844/)).toBeTruthy()
    expect(within(losing).queryByText(NOT_EVIDENCE)).toBeNull()
  })

  test('the pseudonymous list stays behind a disclosure', async () => {
    serveFixtures()
    await renderWithData(<CustomersView source="synthetic" />)

    const summary = screen.getByText('Ver la lista de personas (id seudónimo)')
    expect(summary.closest('details').open).toBe(false)
    const list = screen.getByRole('table', { name: 'Personas en riesgo o perdidas', hidden: true })
    expect(within(list).getAllByRole('row', { hidden: true })).toHaveLength(13) // 12 + encabezado
  })

  test('with lost people in the list, the at-risk column comes back', async () => {
    serveFixturesWith({
      'at-risk': {
        source: 'synthetic',
        data: [
          { usuario: 'u-1', estado: 'en_riesgo', concepto_top: '🍕 Pizza', consiente_avisos: true },
          { usuario: 'u-2', estado: 'perdido', concepto_top: '🍕 Pizza', consiente_avisos: false },
        ],
      },
    })
    await renderWithData(<CustomersView source="synthetic" />)

    const audiences = screen.getByRole('table', { name: 'Personas en riesgo o perdidas por lo que más pedían' })
    const cells = within(within(audiences).getAllByRole('row')[1])
      .getAllByRole('cell')
      .map((cell) => cell.textContent)
    expect(cells).toEqual(['🍕 Pizza', '2', '1', '1 de 2'])
  })

  test('with the prototype: nobody at risk yet, with the MVP label', async () => {
    serveFixtures()
    await renderWithData(<CustomersView source="prototype" />)

    const losing = section('A quién estamos perdiendo')
    expect(within(losing).getByText(NOT_EVIDENCE)).toBeTruthy()
    expect(within(losing).getByText('Nadie en riesgo ni perdido')).toBeTruthy()
    expect(within(losing).queryByText(/pedidos simulados/)).toBeNull()
    // La escalera es de Rappi: no lleva el rótulo del prototipo.
    expect(within(section('Dónde está la venta cruzada')).queryByText(NOT_EVIDENCE)).toBeNull()
  })

  test('if the API returns no at-risk person while there are some, it warns instead of hiding them', async () => {
    serveFixturesWith({
      'at-risk': {
        source: 'synthetic',
        data: [{ usuario: 'u-2', estado: 'perdido', concepto_top: null, consiente_avisos: false }],
      },
    })
    await renderWithData(<CustomersView source="synthetic" />)

    expect(screen.getByText(/ninguna es de una persona en riesgo/)).toBeTruthy()
    expect(screen.getByText('Sin concepto top')).toBeTruthy()
  })
})
