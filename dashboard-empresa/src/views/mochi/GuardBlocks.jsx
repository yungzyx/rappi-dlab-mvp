import { AGENT_NAME } from '../../lib/agentName.js'
import { DataTable } from '../../components/DataTable.jsx'
import { Panel } from '../../components/Panel.jsx'
import { EmptyState } from '../../components/States.jsx'
import { Stats } from '../../components/Stats.jsx'
import { formatDate, formatNumber } from '../../lib/format.js'
import { useAnalytics } from '../../lib/useAnalytics.js'
import { momentHint, momentLabel } from './offers.js'

/** Los motivos de las guardias (offers/guards.py: GUARD_REASONS), con lo que cubre cada uno. */
export const REASONS = {
  alcohol: { label: 'Alcohol', note: 'Licores y lo que dice trago en su nombre, sección o descripción' },
  mas18: { label: '+18', note: 'Tabaco, vapeo, bienestar sexual y lo que la tienda marca +18' },
  farmacia: { label: 'Farmacia', note: 'La vertical y las tiendas que Rappi rotula Farmacia' },
  bebe: { label: 'Bebé', note: 'Pañales, alimentación y artículos de bebé' },
  salud: { label: 'Salud', note: 'Medicamentos, vitaminas, higiene y cuidado personal' },
}

const columnsFor = (reasons) => [
  {
    key: 'momento',
    header: 'Momento',
    primary: true,
    render: (row) => (
      <span className="cell-stack">
        {momentLabel(row.momento)}
        {momentHint(row.momento) && <span className="cell-sub">{momentHint(row.momento)}</span>}
      </span>
    ),
  },
  { key: 'candidatos', header: 'Total', numeric: true, render: (row) => formatNumber(row.candidatos) },
  ...reasons.map((reason) => ({
    key: reason,
    header: REASONS[reason]?.label ?? reason,
    numeric: true,
    render: (row) => formatNumber(row.motivos[reason]),
  })),
]

/**
 * Lo que Mochi no ofreció (/analytics/guardias): cuántos candidatos sacaron las guardias de ofertas, por motivo y por
 * momento, sin persona ni producto. Muestra que Mochi no propone solo alcohol, +18, Farmacia, bebé ni salud. Los
 * simulados no pasan por las guardias: con ellos no hay cifra que mostrar, y lo dice.
 */
export function GuardBlocks({ source }) {
  const data = useAnalytics('guardias', source)
  if (source === 'synthetic') {
    return (
      <EmptyState title="Los datos simulados no pasan por las guardias" inline>
        El contador anota lo que las guardias sacan cuando {AGENT_NAME} arma una oferta en la API: se ve con el uso del
        MVP (fuente prototipo).
      </EmptyState>
    )
  }
  if (!data.total) {
    return (
      <EmptyState title="Las guardias todavía no sacaron nada" inline>
        Se cuenta desde que la API anota lo que las guardias sacan de cada oferta.
      </EmptyState>
    )
  }
  const reasons = data.motivos.map((row) => row.motivo)
  return (
    <>
      <Stats
        items={data.motivos.map((row) => ({
          label: REASONS[row.motivo]?.label ?? row.motivo,
          value: formatNumber(row.candidatos),
          note: REASONS[row.motivo]?.note,
        }))}
      />
      <Panel
        title="Por momento"
        meta={`Del ${formatDate(data.desde)} al ${formatDate(data.hasta)}`}
        foot={
          <p className="block-note">
            Cuenta candidatos (un producto o una vertical) que una guardia sacó, no ofertas: el mismo producto buscado
            dos veces cuenta dos. No cuenta lo que se descarta antes por la historia de la persona, que diría algo de
            ella. Sin persona ni producto.
          </p>
        }
      >
        <DataTable
          caption="Lo que las guardias sacaron, por momento"
          columns={columnsFor(reasons)}
          rows={data.momentos}
          rowKey={(row) => row.momento}
        />
      </Panel>
    </>
  )
}
