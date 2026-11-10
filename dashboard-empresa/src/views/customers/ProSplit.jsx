import { DataTable } from '../../components/DataTable.jsx'
import { Panel } from '../../components/Panel.jsx'
import { EmptyState } from '../../components/States.jsx'
import { formatNumber, formatPct } from '../../lib/format.js'
import { useAnalytics } from '../../lib/useAnalytics.js'

const GROUP_LABELS = { pro: 'Pro', sin_pro: 'Sin Pro' }

const COLUMNS = [
  { key: 'grupo', header: 'Grupo', primary: true, render: (row) => GROUP_LABELS[row.grupo] ?? row.grupo },
  { key: 'personas', header: 'Personas con pedidos', numeric: true, render: (row) => formatNumber(row.personas) },
  { key: 'pedidos', header: 'Pedidos (30 días)', numeric: true, render: (row) => formatNumber(row.pedidos_30d) },
  {
    key: 'porPersona',
    header: 'Pedidos por persona (30 días)',
    numeric: true,
    render: (row) => formatNumber(row.pedidos_por_persona_30d, 2),
  },
  { key: 'recompra', header: 'Volvió a comprar', numeric: true, render: (row) => formatPct(row.recompra_pct) },
  {
    key: 'multi',
    header: 'Multi-vertical (60 días)',
    numeric: true,
    render: (row) => formatPct(row.multi_vertical_pct),
  },
  {
    key: 'retencion',
    header: 'Retención (días 61 a 120)',
    numeric: true,
    render: (row) => formatPct(row.retencion_pct),
  },
]

/**
 * Pro y sin Pro (/analytics/pro, `app_users.pro`): pedidos, recompra, multi-vertical y retención de cada grupo. Un grupo
 * con menos personas que el mínimo no llega (privacidad). En los simulados la marca Pro es un supuesto del generador
 * que sigue a cuántas verticales combina cada persona: ahí la diferencia la puso el generador.
 */
export function ProSplit({ source }) {
  const split = useAnalytics('pro', source)
  const missing =
    split.sin_dato > 0 ? ` ${formatNumber(split.sin_dato)} personas con pedidos no tienen la marca y no entran.` : ''
  return (
    <Panel
      foot={
        <>
          <p className="block-note">
            Volvió a comprar: hizo una segunda compra (un carro dividido en dos tiendas es una compra). Multi-vertical:
            pidió en dos verticales o más entre quienes pidieron en los últimos 60 días. La retención es solo de quien
            tiene 120 días de historia, y se omite con menos de {formatNumber(split.minimo_personas)} personas.
            {split.grupos.length > 0 && missing}
          </p>
          {source === 'synthetic' && (
            <p className="block-note">
              En los datos simulados, quién es Pro lo sortea el generador según cuántas verticales combina cada persona
              (un supuesto propio, no un dato de Rappi): que Pro combine más verticales lo puso el generador, no es
              evidencia.
            </p>
          )}
        </>
      }
    >
      {split.grupos.length ? (
        <DataTable caption="Pro y sin Pro" columns={COLUMNS} rows={split.grupos} rowKey={(row) => row.grupo} />
      ) : (
        <EmptyState title="Todavía no hay grupos que mostrar">
          Cada grupo necesita al menos {formatNumber(split.minimo_personas)} personas con pedidos.{missing}
        </EmptyState>
      )}
    </Panel>
  )
}
