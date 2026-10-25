import { ChartTableSwitch } from '../../components/ChartTableSwitch.jsx'
import { DataTable } from '../../components/DataTable.jsx'
import { EmptyState } from '../../components/States.jsx'
import { formatNumber, formatPct, formatPoints } from '../../lib/format.js'
import { comboLabel } from '../../lib/labels.js'
import { ladderSteps, retentionDomain } from './ladder.js'

const TICK_STEP = 10

// La retención llega como fracción (0,82); `null` si la combinación no la trae.
const retention = (row) => formatPct(row.retencion_m1 === null ? null : row.retencion_m1 * 100, 0)

const RAPPI_COLUMNS = [
  { key: 'combo', header: 'Combinación', primary: true, render: (row) => comboLabel(row.combo) },
  { key: 'usuarios', header: 'Usuarios', numeric: true, render: (row) => formatNumber(row.usuarios) },
  { key: 'pct_usuarios', header: '% usuarios', numeric: true, render: (row) => formatPct(row.pct_usuarios) },
  { key: 'pct_pedidos', header: '% pedidos', numeric: true, render: (row) => formatPct(row.pct_pedidos) },
  {
    key: 'pedidos',
    header: 'Pedidos por usuario',
    numeric: true,
    render: (row) => formatNumber(row.pedidos_por_usuario, 1),
  },
  { key: 'retencion', header: 'Vuelven al mes siguiente', numeric: true, render: retention },
  {
    key: 'gasto',
    header: 'Gasto por usuario (moneda de la fuente)',
    numeric: true,
    render: (row) => formatNumber(row.gasto_por_usuario),
  },
]

/** "Solo Restaurantes" para un grupo; la combinación tal cual para dos o más. */
const startLabel = (combo) => (combo.includes('+') ? comboLabel(combo) : `Solo ${comboLabel(combo)}`)

function Step({ step, toX, ticks }) {
  const from = toX(step.fromPct)
  const to = toX(step.toPct)
  const added = comboLabel(step.added)
  return (
    <li className="ladder-row">
      <p className="visually-hidden">
        {startLabel(step.from.combo)}, {formatPct(step.from.pct_usuarios)} de los usuarios: vuelve al mes siguiente el{' '}
        {formatPct(step.fromPct, 0)}; quienes además usan {added}, el {formatPct(step.toPct, 0)}. Pedidos por usuario:{' '}
        {formatNumber(step.from.pedidos_por_usuario, 1)} y {formatNumber(step.to.pedidos_por_usuario, 1)}.
      </p>
      <div className="ladder-label" aria-hidden="true">
        <strong>{startLabel(step.from.combo)}</strong>
        <span>{formatPct(step.from.pct_usuarios)} de los usuarios</span>
      </div>
      <div className="ladder-track" aria-hidden="true">
        {ticks.map((tick) => (
          <span key={tick} className="ladder-tick" style={{ left: `${toX(tick)}%` }} />
        ))}
        <span className="ladder-link" style={{ left: `${Math.min(from, to)}%`, width: `${Math.abs(to - from)}%` }} />
        <span className="ladder-dot ladder-dot--from" style={{ left: `${from}%` }}>
          <span className="ladder-value ladder-value--from">{formatPct(step.fromPct, 0)}</span>
        </span>
        <span className="ladder-dot ladder-dot--to" style={{ left: `${to}%` }}>
          <span className="ladder-value ladder-value--to">{formatPct(step.toPct, 0)}</span>
        </span>
      </div>
      <p className="ladder-gain" aria-hidden="true">
        <strong>{formatPoints(step.gain, 0)}</strong>
        <span>con {added}</span>
        <span>
          {formatNumber(step.from.pedidos_por_usuario, 1)} → {formatNumber(step.to.pedidos_por_usuario, 1)} pedidos
        </span>
      </p>
    </li>
  )
}

/**
 * La escalera de la tabla de Rappi como gráfico de pesas (antes → después por fila, un tono y gris):
 * para cada combinación, la retención M+1 de hoy y la de la combinación con un grupo más que más retiene. Su tabla es
 * la tabla completa que compartió Rappi, con el total.
 */
export function RetentionLadder({ rappi }) {
  const steps = ladderSteps(rappi.filas)
  if (!steps.length) {
    return <EmptyState title="La tabla de Rappi no trae combinaciones que comparar" />
  }
  const [lo, hi] = retentionDomain(steps)
  const toX = (pct) => ((pct - lo) / (hi - lo)) * 100
  const ticks = Array.from({ length: (hi - lo) / TICK_STEP + 1 }, (_, index) => lo + index * TICK_STEP)
  const chart = (
    <div className="ladder">
      <div className="legend">
        <span className="legend-item">
          <span className="ladder-key ladder-key--from" />
          Hoy: vuelven al mes siguiente
        </span>
        <span className="legend-item">
          <span className="ladder-key ladder-key--to" />
          Quienes además usan el grupo siguiente
        </span>
      </div>
      <ol className="ladder-rows">
        {steps.map((step) => (
          <Step key={step.from.combo} step={step} toX={toX} ticks={ticks} />
        ))}
      </ol>
      <div className="ladder-axis" aria-hidden="true">
        <span />
        <div className="ladder-axis-track">
          {ticks.map((tick) => (
            <span key={tick} style={{ left: `${toX(tick)}%` }}>
              {formatPct(tick, 0)}
            </span>
          ))}
        </div>
        <span />
      </div>
    </div>
  )
  const table = (
    <DataTable
      caption="Combinaciones de verticales de Rappi"
      columns={RAPPI_COLUMNS}
      rows={[...rappi.filas, { ...rappi.total, combo: 'total' }]}
      rowKey={(row) => row.combo}
      rowClassName={(row) => (row.combo === 'total' ? 'is-group-start' : undefined)}
    />
  )
  return <ChartTableSwitch chart={chart} table={table} />
}
