import { DataTable } from '../../components/DataTable.jsx'
import { Meter } from '../../components/Meter.jsx'
import { EmptyState } from '../../components/States.jsx'
import { formatNumber, formatPct } from '../../lib/format.js'

// Los pasos del embudo por sesión (/analytics/embudo-sesion): cada uno exige los anteriores.
export const FUNNEL_STEPS = [
  { key: 'sesiones', label: 'Sesiones' },
  { key: 'vieron', label: 'Vieron una lista' },
  { key: 'tocaron', label: 'Tocaron algo' },
  { key: 'agregaron', label: 'Agregaron al carro' },
  { key: 'pidieron', label: 'Pidieron' },
]
const MODE_LABELS = { propuesta: 'Prototipo con Mochi', actual: 'Rappi hoy' }

/**
 * CTR por posición (/analytics/ctr-posicion, capa.v_ctr_posicion): de lo que quedó a la vista en cada lugar de las
 * listas, cuánto se tocó desde ahí. Solo el prototipo con Mochi.
 */
export function CtrByPosition({ data }) {
  const { posiciones } = data
  if (!posiciones.length) {
    return (
      <EmptyState title="Todavía no hay impresiones">
        Aparecen cuando las listas de la app (Home, búsqueda, tiendas, Turbo, Mochi) quedan a la vista.
      </EmptyState>
    )
  }
  const top = Math.max(...posiciones.map((row) => row.ctr ?? 0))
  const columns = [
    { key: 'posicion', header: 'Lugar', primary: true, render: (row) => `${row.posicion + 1}.º` },
    { key: 'impresiones', header: 'Vistos', numeric: true, render: (row) => formatNumber(row.impresiones) },
    { key: 'clics', header: 'Tocados', numeric: true, render: (row) => formatNumber(row.clics) },
    {
      key: 'ctr',
      header: 'CTR',
      numeric: true,
      render: (row) => (
        <span className="cell-bar">
          <Meter value={row.ctr} max={top} />
          {formatPct(row.ctr * 100)}
        </span>
      ),
    },
  ]
  return (
    <DataTable
      caption="CTR por posición en las listas"
      columns={columns}
      rows={posiciones}
      rowKey={(row) => row.posicion}
    />
  )
}

/** El embudo por sesión (/analytics/embudo-sesion, capa.v_embudo_sesion): una tabla por modo de la app. */
export function SessionFunnel({ rows }) {
  if (!rows.length) {
    return <EmptyState title="Todavía no hay sesiones">Aparecen con el primer uso de la app.</EmptyState>
  }
  return rows.map((row) => (
    <FunnelTable key={row.modo} row={row} title={rows.length > 1 ? (MODE_LABELS[row.modo] ?? row.modo) : null} />
  ))
}

function FunnelTable({ row, title }) {
  const steps = FUNNEL_STEPS.map((step) => ({ ...step, n: row[step.key] }))
  const columns = [
    { key: 'label', header: 'Paso', primary: true },
    { key: 'n', header: 'Sesiones', numeric: true, render: (step) => formatNumber(step.n) },
    {
      key: 'pct',
      header: 'De todas',
      numeric: true,
      render: (step) => (
        <span className="cell-bar">
          <Meter value={step.n} max={row.sesiones} />
          {formatPct(row.sesiones ? (step.n * 100) / row.sesiones : null)}
        </span>
      ),
    },
  ]
  return (
    <>
      {title && <h4 className="subhead">{title}</h4>}
      <DataTable
        caption={`Embudo por sesión${title ? `: ${title}` : ''}`}
        columns={columns}
        rows={steps}
        rowKey={(step) => step.key}
      />
    </>
  )
}
