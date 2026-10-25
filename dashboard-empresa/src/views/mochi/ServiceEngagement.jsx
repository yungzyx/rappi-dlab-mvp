import { AGENT_NAME } from '../../lib/agentName.js'
import { DataTable } from '../../components/DataTable.jsx'
import { EmptyState } from '../../components/States.jsx'
import { formatNumber, formatPct } from '../../lib/format.js'
import { MIN_SHOWN_FOR_RATE } from './offers.js'

const COLUMNS = [
  { key: 'nombre', header: 'Servicio', primary: true },
  { key: 'ofrecido', header: `${AGENT_NAME} lo ofreció`, numeric: true, render: (row) => formatNumber(row.ofrecido) },
  {
    key: 'abierto',
    header: 'Se abrió',
    numeric: true,
    // El % desde 10 ofrecidas, como el resto del panel, y solo si no pasa de las ofrecidas: «abierto» también cuenta
    // aperturas que no vienen de una oferta de Mochi.
    render: (row) =>
      row.ofrecido >= MIN_SHOWN_FOR_RATE && row.abierto <= row.ofrecido
        ? `${formatNumber(row.abierto)} (${formatPct((row.abierto * 100) / row.ofrecido, 0)})`
        : formatNumber(row.abierto),
  },
  {
    key: 'ganchos',
    header: 'Producto sugerido junto, aceptado',
    numeric: true,
    render: (row) =>
      row.ganchos_mostrados ? `${formatNumber(row.ganchos_aceptados)} de ${formatNumber(row.ganchos_mostrados)}` : '—',
  },
]

/** Servicios sin catálogo (RappiTravel, RappiFavor): ofrecidos por Mochi, abiertos (de lo que ofreció) y ganchos del
 * catálogo aceptados (lo que sugiere junto al servicio). Los abiertos desde la Home no miden a Mochi: no van aquí. */
export function ServiceEngagement({ rows }) {
  if (!rows.some((row) => row.ofrecido)) {
    return (
      <EmptyState title={`${AGENT_NAME} todavía no ofreció servicios`}>
        Aparecen cuando alguien habla de un viaje o de un envío, o no encuentra lo que busca.
      </EmptyState>
    )
  }
  return <DataTable caption="Servicios sin catálogo" columns={COLUMNS} rows={rows} rowKey={(row) => row.servicio} />
}
