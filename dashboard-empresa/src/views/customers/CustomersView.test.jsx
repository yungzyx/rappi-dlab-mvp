import { act, fireEvent, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { renderWithData, resetApi, serveFixtures, serveFixturesWith } from '../../test/fixtureApi.js'
import { CustomersView } from './CustomersView.jsx'

const NOT_EVIDENCE = 'Prototipo · no es evidencia'
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
    expect(within(ladder).getByText('1.180.000')).toBeTruthy() // usuarios de toda la tabla
  })

  test('users and orders by combination: a bar per series and its table, from more to fewer users', async () => {
    serveFixtures()
    await renderWithData(<CustomersView source="synthetic" />)

    const table = screen.getByRole('table', { name: 'Usuarios y pedidos por combinación' })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(8)
    expect(within(rows[0]).getAllByRole('cell')[1].textContent).toBe('62,6%')
    expect(screen.getByRole('button', { name: 'Ver tabla de Usuarios y pedidos por combinación' })).toBeTruthy()
  })

  test('the ladder table is the full Rappi table with its total', async () => {
    serveFixtures()
    await renderWithData(<CustomersView source="synthetic" />)

    await act(async () =>
      fireEvent.click(screen.getByRole('button', { name: 'Ver tabla de Combinaciones de verticales de Rappi' })),
    )

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
    expect(within(losing).getByText('Califican para "¿Volvemos a…?"')).toBeTruthy()
    expect(within(losing).getByText('Al 03-10-2026')).toBeTruthy()
    expect(within(losing).getByText('Doble de su ritmo sin pedir. Todavía se pueden recuperar.')).toBeTruthy()
    expect(within(losing).getByText('1 por un concepto, 0 por una vertical')).toBeTruthy()

    const audiences = within(losing).getByRole('table', { name: 'Personas en riesgo o perdidas por lo que más pedían' })
    const [first] = within(audiences).getAllByRole('row').slice(1)
    expect(within(first).getAllByRole('cell')[0].textContent).toBe('🍕 Pizza')
    expect(within(first).getAllByRole('cell')[1].textContent).toBe('28')
    // todas las de la lista están en riesgo: la columna "En riesgo" repetiría "Personas"
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

  test('a shared file without the ids of the prototype: the audiences, and no list of people', async () => {
    serveFixturesWith({
      kpis: { source: 'prototype', data: { en_riesgo: 1, perdidos: 1 } },
      'at-risk': {
        source: 'prototype',
        data: [
          { estado: 'en_riesgo', concepto_top: '🍕 Pizza', consiente_avisos: true },
          { estado: 'perdido', concepto_top: '🍕 Pizza', consiente_avisos: false },
        ],
      },
    })
    await renderWithData(<CustomersView source="prototype" />)

    const losing = section('A quién estamos perdiendo')
    const audiences = within(losing).getByRole('table', { name: 'Personas en riesgo o perdidas por lo que más pedían' })
    expect(within(audiences).getByText('🍕 Pizza')).toBeTruthy()
    expect(within(losing).queryByText('Ver la lista de personas (id seudónimo)')).toBeNull()
    expect(within(losing).queryByRole('table', { name: 'Personas en riesgo o perdidas', hidden: true })).toBeNull()
    expect(within(losing).getByText(/Este archivo no trae la lista de personas del prototipo/)).toBeTruthy()
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

  test('Pro y sin Pro: pedidos, recompra, multi-vertical y retención de cada grupo, con el supuesto de los simulados', async () => {
    const row = (grupo, personas, pedidos, porPersona, recompra, multi, retencion) => ({
      grupo,
      personas,
      pedidos_30d: pedidos,
      pedidos_por_persona_30d: porPersona,
      recompra_pct: recompra,
      multi_vertical_pct: multi,
      retencion_n: personas,
      retencion_pct: retencion,
    })
    serveFixturesWith({
      pro: {
        source: 'synthetic',
        data: {
          grupos: [row('pro', 420, 1310, 3.12, 81.4, 58.3, 64.2), row('sin_pro', 980, 1205, 1.23, 52.9, 21.7, null)],
          sin_dato: 3,
          minimo_personas: 20,
        },
      },
    })
    await renderWithData(<CustomersView source="synthetic" />)

    const pro = section('Pro y sin Pro')
    const rows = within(within(pro).getByRole('table', { name: 'Pro y sin Pro' }))
      .getAllByRole('row')
      .slice(1)
    const cells = (r) =>
      within(r)
        .getAllByRole('cell')
        .map((cell) => cell.textContent)
    expect(cells(rows[0])).toEqual(['Pro', '420', '1.310', '3,12', '81,4%', '58,3%', '64,2%'])
    expect(cells(rows[1])).toEqual(['Sin Pro', '980', '1.205', '1,23', '52,9%', '21,7%', '—'])
    expect(within(pro).getByText(/3 personas con pedidos no tienen la marca/)).toBeTruthy()
    expect(within(pro).getByText(/lo sortea el generador/)).toBeTruthy()
    expect(within(pro).getByText('Simulado')).toBeTruthy()
    for (const title of [
      'Pedidos por persona (30 días)',
      'Volvió a comprar',
      '2 o más verticales (60 días)',
      'Retención (días 61 a 120)',
    ]) {
      expect(within(pro).getByRole('heading', { name: title, hidden: true })).toBeTruthy()
    }
  })

  test('Pro y sin Pro con el prototipo: sin grupos con el mínimo de personas, lo dice y lleva el rótulo', async () => {
    serveFixtures()
    await renderWithData(<CustomersView source="prototype" />)

    const pro = section('Pro y sin Pro')
    expect(within(pro).getByText('Todavía no hay grupos que mostrar')).toBeTruthy()
    expect(
      within(pro).getByText(/al menos 20 personas con pedidos\. 8 personas con pedidos no tienen la marca/),
    ).toBeTruthy()
    expect(within(pro).getByText(NOT_EVIDENCE)).toBeTruthy()
    expect(within(pro).queryByText(/lo sortea el generador/)).toBeNull()
  })

  test('audiences: each with its rule, its size, who accepts notifications and what to offer', async () => {
    serveFixturesWith({
      audiencias: {
        source: 'synthetic',
        data: {
          audiencias: [
            {
              id: 'solo-restaurantes-con-habito',
              nombre: 'Solo Restaurantes, con hábito',
              regla: 'Pidió solo en Restaurantes en 60 días y lleva 2 o más compras en 30',
              ofrecer: 'Turbo, su vertical por probar',
              personas: 178,
              aceptan_avisos: 68,
              personas_antes: 160,
              cambio_personas_pct: 11,
            },
            {
              id: 'combina-3-o-mas',
              nombre: 'Ya combina 3 o más',
              regla: 'Pidió en 3 o más verticales en 60 días',
              ofrecer: 'Nada nuevo: no molestar',
              personas: 25,
              aceptan_avisos: 5,
              personas_antes: null,
              cambio_personas_pct: null,
            },
          ],
          bajo_el_minimo: 2,
          minimo_personas: 20,
          dias_cambio: 28,
        },
      },
    })
    await renderWithData(<CustomersView source="synthetic" tab="audiencias" />)

    expect(screen.getByRole('heading', { name: 'Audiencias para campañas' })).toBeTruthy()
    const [, row] = screen.getAllByRole('row')
    expect(within(row).getByText('Solo Restaurantes, con hábito')).toBeTruthy()
    expect(within(row).getByText('Pidió solo en Restaurantes en 60 días y lleva 2 o más compras en 30')).toBeTruthy()
    expect(within(row).getByText('178')).toBeTruthy()
    expect(within(row).getByText('68 de 178')).toBeTruthy()
    expect(within(row).getByText('Turbo, su vertical por probar')).toBeTruthy()
    expect(within(row).getByText('+11%')).toBeTruthy() // contra 4 semanas antes, sin juicio
    expect(within(row).getByText('antes 160')).toBeTruthy()
    expect(within(row).queryByText(/mejora|empeora/)).toBeNull()
    const [, , small] = screen.getAllByRole('row')
    expect(within(small).getByText('Hace 4 semanas no llegaba a 20')).toBeTruthy()
    expect(screen.getByText('2 audiencias no llegan a 20 personas y no se muestran.')).toBeTruthy()
    expect(screen.getByText(/Fuera de la app solo se le escribe a quien aceptó avisos/)).toBeTruthy()
  })

  test('an audience list is copied as CSV from the API: pseudonymous ids and who accepts notifications', async () => {
    const audience = {
      id: 'probo-turbo-una-vez',
      nombre: 'Probó Turbo una vez',
      regla: 'Un solo pedido en Turbo en 60 días y alguno en Restaurantes',
      ofrecer: 'Repetir en Turbo lo que pidió',
      personas: 20,
      aceptan_avisos: 1,
      personas_antes: null,
      cambio_personas_pct: null,
    }
    serveFixturesWith({
      audiencias: {
        source: 'prototype',
        data: { audiencias: [audience], bajo_el_minimo: 4, minimo_personas: 20, dias_cambio: 28 },
      },
      'audiencias/probo-turbo-una-vez': {
        source: 'prototype',
        data: {
          id: 'probo-turbo-una-vez',
          nombre: 'Probó Turbo una vez',
          personas: [
            { usuario: 'u-0a1b2c3d', acepta_avisos: true },
            { usuario: 'u-4e5f6a7b', acepta_avisos: false },
          ],
        },
      },
    })
    const writeText = vi.fn(async () => {})
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
    await renderWithData(<CustomersView source="prototype" tab="audiencias" />)

    await act(async () =>
      fireEvent.click(screen.getByRole('button', { name: 'Copiar la lista de Probó Turbo una vez' })),
    )
    expect(writeText).toHaveBeenCalledWith('Usuario;Acepta avisos\r\nu-0a1b2c3d;Sí\r\nu-4e5f6a7b;No')
    expect(screen.getByRole('status').textContent).toBe('Copiada')
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/analytics/audiencias/probo-turbo-una-vez?source=prototype'),
      expect.anything(),
    )
  })

  test('an audience list that the API does not give says so, without breaking the table', async () => {
    serveFixturesWith({
      audiencias: {
        source: 'prototype',
        data: {
          audiencias: [{ id: 'x', nombre: 'X', regla: '', ofrecer: '', personas: 20, aceptan_avisos: 0 }],
          bajo_el_minimo: 4,
          minimo_personas: 20,
        },
      },
    })
    await renderWithData(<CustomersView source="prototype" tab="audiencias" />)
    expect(screen.getAllByRole('row')[1].textContent).toContain('—') // una foto sin el cambio
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Descargar la lista de X en CSV' })))
    expect(screen.getByRole('status').textContent).toBe('No se pudo: la lista sale de la API en marcha.')
  })

  test('audiences say so when none reaches the minimum', async () => {
    serveFixtures() // la simulación chica: ninguna audiencia llega a 20 personas
    await renderWithData(<CustomersView source="synthetic" tab="audiencias" />)
    expect(screen.getByText('Ninguna audiencia llega al mínimo')).toBeTruthy()
  })
})
