import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { DataTable } from './DataTable.jsx'
import { Panel } from './Panel.jsx'

const table = (
  <DataTable
    caption="Pedidos"
    columns={[
      { key: 'semana', header: 'Semana del', primary: true },
      { key: 'pedidos', header: 'Pedidos', numeric: true },
    ]}
    rows={[{ semana: '26 oct', pedidos: 448 }]}
    rowKey={(row) => row.semana}
  />
)

describe('Panel', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  test('a panel with a table downloads it as CSV, named after its title', async () => {
    const blobs = []
    vi.stubGlobal('URL', {
      createObjectURL: (blob) => blobs.push(blob) && 'blob:csv',
      revokeObjectURL: () => {},
    })
    let fileName
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function () {
      fileName = this.download
    })
    render(<Panel title="Serie semanal">{table}</Panel>)

    fireEvent.click(screen.getByRole('button', { name: 'Descargar CSV de Serie semanal' }))

    expect(fileName).toBe('serie-semanal.csv')
    // Con BOM (EF BB BF): así una planilla en español abre bien los acentos.
    expect([...new Uint8Array(await blobs[0].arrayBuffer())].slice(0, 3)).toEqual([0xef, 0xbb, 0xbf])
    expect(await blobs[0].text()).toBe('Semana del;Pedidos\r\n26 oct;448')
    click.mockRestore()
  })
})
