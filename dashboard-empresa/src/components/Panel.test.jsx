import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { DataTable } from './DataTable.jsx'
import { Panel } from './Panel.jsx'
import { SectionHead } from './SectionHead.jsx'

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

  test('the CSV carries where its figures come from: the source of its section and the status of the page', async () => {
    const blobs = []
    vi.stubGlobal('URL', {
      createObjectURL: (blob) => blobs.push(blob) && 'blob:csv',
      revokeObjectURL: () => {},
    })
    const names = []
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function () {
      names.push(this.download)
    })
    render(
      <>
        <p className="page-meta">
          <span className="data-status">Datos guardados</span>
          <span aria-hidden="true">·</span>
          <span>
            Datos al <strong>03-11-2026</strong>
          </span>
        </p>
        <section className="section">
          <SectionHead id="como-va" title="Cómo va" source="synthetic" />
          <Panel title="Serie semanal">{table}</Panel>
        </section>
        <section className="section">
          <SectionHead id="venta-cruzada" title="Venta cruzada" source="synthetic" />
          <Panel title="Combinaciones" source="rappi">
            {table}
          </Panel>
        </section>
      </>,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Descargar CSV de Serie semanal' }))
    fireEvent.click(screen.getByRole('button', { name: 'Descargar CSV de Combinaciones' }))

    expect(names).toEqual(['serie-semanal-simulados.csv', 'combinaciones.csv'])
    expect(await blobs[0].text()).toBe(
      'Procedencia;Datos simulados: no son evidencia\r\nDatos;Datos guardados · Datos al 03-11-2026\r\n\r\n' +
        'Semana del;Pedidos\r\n26 oct;448',
    )
    // El bloque con su propia insignia manda sobre la de su sección: la tabla de Rappi no es simulada.
    expect((await blobs[1].text()).split('\r\n')[0]).toBe(
      'Procedencia;Dato de Rappi (tabla de combinaciones, cohortes de enero a junio de 2026): es una correlación',
    )
    click.mockRestore()
  })
})
