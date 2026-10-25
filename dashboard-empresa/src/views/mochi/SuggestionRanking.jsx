import { AGENT_NAME } from '../../lib/agentName.js'
import { useState } from 'react'
import { DataTable } from '../../components/DataTable.jsx'
import { Meter } from '../../components/Meter.jsx'
import { EmptyState } from '../../components/States.jsx'
import { formatNumber, formatPct } from '../../lib/format.js'
import { verticalLabel } from '../../lib/labels.js'
import { MIN_SHOWN_FOR_RATE } from './offers.js'

const PREVIEW_ROWS = 8

/**
 * Sugerencias entre verticales (al preguntarle a Mochi y en «Para ti») por concepto y vertical: cuántas se aceptaron de
 * las mostradas y cuántas llegaron a un pedido. Primero las más mostradas; el resto, a pedido. Incluye lo que la persona
 * pidió al preguntarle (una cerveza, si la pidió): Mochi no propone alcohol por su cuenta, y la nota lo dice.
 */
export function SuggestionRanking({ rows }) {
  const [expanded, setExpanded] = useState(false)
  if (!rows.length) {
    return (
      <EmptyState title="Sin sugerencias entre verticales que evaluar">
        Aparecen cuando {AGENT_NAME} sugiere un producto de otra vertical.
      </EmptyState>
    )
  }
  const sorted = [...rows].sort((a, b) => b.mostradas - a.mostradas)
  const columns = [
    {
      key: 'sugerencia',
      header: 'Sugerencia',
      primary: true,
      render: (row) => (
        <span className="cell-stack">
          <strong>{row.concepto}</strong>
          <span className="cell-sub">en {verticalLabel(row.vertical)}</span>
        </span>
      ),
    },
    {
      key: 'aceptadas',
      header: 'Aceptadas',
      numeric: true,
      render: (row) => `${formatNumber(row.aceptadas)} de ${formatNumber(row.mostradas)}`,
    },
    {
      key: 'aceptacion',
      header: 'Tasa',
      numeric: true,
      render: (row) => (
        <span className="cell-bar">
          {row.aceptacion_pct === null ? <span /> : <Meter value={row.aceptacion_pct} max={100} />}
          {formatPct(row.aceptacion_pct)}
        </span>
      ),
    },
    {
      key: 'convertidas',
      header: 'Llegaron a pedido',
      numeric: true,
      // La parte de las aceptadas, con el mismo mínimo que la tasa: con 4 aceptadas un % no dice nada.
      render: (row) =>
        row.aceptadas >= MIN_SHOWN_FOR_RATE
          ? `${formatNumber(row.convertidas)} (${formatPct((row.convertidas * 100) / row.aceptadas, 0)})`
          : formatNumber(row.convertidas),
    },
  ]
  return (
    <>
      <DataTable
        caption="Sugerencias entre verticales"
        columns={columns}
        rows={expanded ? sorted : sorted.slice(0, PREVIEW_ROWS)}
        rowKey={(row) => `${row.concepto}-${row.vertical}`}
      />
      <p className="cell-sub">
        Incluye lo que la persona pidió al preguntarle: {AGENT_NAME} no propone por su cuenta alcohol, Farmacia, bebé ni
        salud.
      </p>
      {sorted.length > PREVIEW_ROWS && (
        <div className="view-switch">
          <button type="button" className="text-button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
            {expanded ? `Ver solo las ${PREVIEW_ROWS} más mostradas` : `Ver las ${formatNumber(sorted.length)}`}
          </button>
        </div>
      )}
    </>
  )
}
