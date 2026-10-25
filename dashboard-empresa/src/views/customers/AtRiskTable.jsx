import { useState } from 'react'
import { DataTable } from '../../components/DataTable.jsx'
import { StatusLabel } from '../../components/StatusLabel.jsx'
import { formatNumber } from '../../lib/format.js'

const PREVIEW_ROWS = 12

const COLUMNS = [
  { key: 'usuario', header: 'Persona', primary: true, render: (row) => <span className="mono">{row.usuario}</span> },
  { key: 'estado', header: 'Estado', render: (row) => <StatusLabel status={row.estado} /> },
  { key: 'persona', header: 'Perfil', render: (row) => row.persona ?? '—' },
  { key: 'ritmo', header: 'Ritmo (días)', numeric: true, render: (row) => formatNumber(row.ritmo_dias, 1) },
  { key: 'dias', header: 'Días sin pedir', numeric: true, render: (row) => formatNumber(row.dias_sin_pedir) },
  { key: 'concepto', header: 'Concepto top', render: (row) => row.concepto_top ?? '—' },
  { key: 'avisos', header: 'Acepta avisos', render: (row) => (row.consiente_avisos ? 'Sí' : 'No') },
  {
    key: 'accion',
    header: 'Acción',
    wide: true,
    render: (row) => <span className="action-cell">{row.accion}</span>,
  },
]

/** Lista de personas en riesgo o perdidas (id seudónimo), las primeras 12 y el resto a pedido. */
export function AtRiskTable({ rows }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <>
      <DataTable
        caption="Personas en riesgo o perdidas"
        columns={COLUMNS}
        rows={expanded ? rows : rows.slice(0, PREVIEW_ROWS)}
        rowKey={(row) => row.usuario}
        rowClassName={(row, index) =>
          index > 0 && rows[index - 1].estado !== row.estado ? 'is-group-start' : undefined
        }
      />
      {rows.length > PREVIEW_ROWS && (
        <div className="view-switch">
          <button type="button" className="text-button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
            {expanded ? `Ver solo las primeras ${PREVIEW_ROWS}` : `Ver las ${formatNumber(rows.length)}`}
          </button>
        </div>
      )}
    </>
  )
}
