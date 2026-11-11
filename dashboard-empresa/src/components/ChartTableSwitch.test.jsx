import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, test } from 'vitest'
import { ChartTableSwitch } from './ChartTableSwitch.jsx'

const table = (
  <table>
    <caption>Serie semanal</caption>
    <tbody>
      <tr>
        <td>561</td>
      </tr>
    </tbody>
  </table>
)

describe('ChartTableSwitch', () => {
  afterEach(cleanup)

  test('with keepTable the table is always in the DOM, hidden from view until "Ver tabla"', async () => {
    render(<ChartTableSwitch chart={<p>Gráfico</p>} table={table} name="Serie semanal" />)

    const hidden = screen.getByRole('table', { name: 'Serie semanal' })
    expect(hidden.closest('.visually-hidden')).toBeTruthy()
    expect(screen.getByText('Gráfico')).toBeTruthy()

    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Ver tabla de Serie semanal' })))

    expect(screen.getByRole('table', { name: 'Serie semanal' }).closest('.visually-hidden')).toBeNull()
    expect(screen.queryByText('Gráfico')).toBeNull()
    expect(screen.getByRole('button', { name: 'Ver gráfico de Serie semanal' }).textContent).toBe('Ver gráfico')
  })

  test('without keepTable the table only exists after "Ver tabla"', async () => {
    render(<ChartTableSwitch chart={<p>Gráfico</p>} table={table} name="Serie semanal" keepTable={false} />)

    expect(screen.queryByRole('table')).toBeNull()
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Ver tabla de Serie semanal' })))
    expect(screen.getByRole('table', { name: 'Serie semanal' })).toBeTruthy()
  })
})
