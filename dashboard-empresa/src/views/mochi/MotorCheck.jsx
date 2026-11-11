import { DataTable } from '../../components/DataTable.jsx'
import { Delta } from '../../components/Delta.jsx'
import { Meter } from '../../components/Meter.jsx'
import { EmptyState } from '../../components/States.jsx'
import { formatDate, formatNumber, formatPct, formatPoints } from '../../lib/format.js'
import { motorRows } from './motor.js'

const COLUMNS = [
  {
    key: 'decides',
    header: 'Qué decide',
    primary: true,
    render: (row) => (
      <span className="cell-stack">
        <strong>{row.decides}</strong>
        <span className="cell-sub">
          Acierto: {row.metric} ({formatNumber(row.n)} personas)
        </span>
      </span>
    ),
  },
  {
    key: 'motor',
    header: 'Motor',
    numeric: true,
    render: (row) => (
      <span className="cell-bar">
        <Meter value={row.motor} max={100} />
        {formatPct(row.motor)}
      </span>
    ),
  },
  {
    key: 'base',
    header: 'Regla simple',
    numeric: true,
    render: (row) => (
      <span className="cell-stack">
        <span className="cell-bar">
          <Meter value={row.base} max={100} />
          {formatPct(row.base)}
        </span>
        <span className="cell-sub">{row.baseLabel}</span>
      </span>
    ),
  },
  {
    key: 'gap',
    header: 'Diferencia',
    numeric: true,
    render: (row) =>
      row.gap === null ? (
        '—'
      ) : (
        <span className="cell-stack">
          {/* Un span de bloque alrededor: Delta es inline-flex y, suelto en la grilla, se estira y pierde el text-align de la celda. */}
          <span>
            <Delta value={row.gap} format={formatPoints} goodWhen={row.noise ? null : 'up'} />
          </span>
          {row.noise && (
            <span className="cell-sub">
              no es concluyente{row.p === undefined || row.p === null ? '' : ` (p = ${formatNumber(row.p, 2)})`}
            </span>
          )}
        </span>
      ),
  },
]

export function MotorCheck({ data, source }) {
  if (!data) {
    return (
      <EmptyState title="El motor todavía no corrió" inline>
        Aparece cuando corre el motor sobre los pedidos de esta fuente.
      </EmptyState>
    )
  }
  if (!data.evaluacion) {
    return (
      <EmptyState title="Sin evaluación todavía" inline>
        La evaluación por fechas pide al menos 84 días de pedidos. Última corrida del motor: {formatDate(data.fecha)}.
      </EmptyState>
    )
  }
  return (
    <>
      <DataTable
        caption="El motor contra una regla simple"
        columns={COLUMNS}
        rows={motorRows(data.evaluacion)}
        rowKey={(row) => row.key}
      />
      <p className="cell-sub">
        Se mide con pedidos posteriores a los que usó para aprender. Corrida del {formatDate(data.fecha)}.
        {source === 'synthetic' && ' Sobre datos simulados prueba la mecánica del motor, no su efecto.'}
      </p>
    </>
  )
}
