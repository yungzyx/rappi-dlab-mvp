import { AGENT_NAME } from '../../lib/agentName.js'
import { Async } from '../../components/Async.jsx'
import { DataTable } from '../../components/DataTable.jsx'
import { ProvenanceBadge } from '../../components/ProvenanceBadge.jsx'
import { SourceNote } from '../../components/SourceNote.jsx'
import { EmptyState } from '../../components/States.jsx'
import { formatNumber, formatPct } from '../../lib/format.js'
import { useAnalytics } from '../../lib/useAnalytics.js'
import { assignedPeople, experimentLabel, orderedPct, variantLabel } from './experiments.js'

// Las columnas de todos los experimentos: personas, con pedido y verticales por persona, desde que se asignó la variante.
const GROUP_COLUMNS = [
  {
    key: 'variante',
    header: 'Variante',
    primary: true,
    render: (row) => <strong>{variantLabel(row.variante)}</strong>,
  },
  { key: 'personas', header: 'Personas', numeric: true, render: (row) => formatNumber(row.personas) },
  {
    key: 'con_pedido',
    header: 'Con pedido',
    numeric: true,
    render: (row) => (
      <span className="cell-stack">
        {formatNumber(row.con_pedido)}
        {row.personas > 0 && <span className="cell-sub">{formatPct(orderedPct(row))}</span>}
      </span>
    ),
  },
  {
    key: 'verticales',
    header: 'Verticales por persona con pedido',
    numeric: true,
    render: (row) => formatNumber(row.verticales_por_persona, 1),
  },
]

// En el grupo de control, además, las ofertas de los momentos que Mochi propone solo.
const OFFER_COLUMNS = [
  {
    key: 'mostradas',
    header: 'Ofertas mostradas',
    numeric: true,
    render: (row) => formatNumber(row.ofertas.mostradas),
  },
  { key: 'retenidas', header: 'Retenidas', numeric: true, render: (row) => formatNumber(row.ofertas.retenidas) },
  { key: 'aceptadas', header: 'Aceptadas', numeric: true, render: (row) => formatNumber(row.ofertas.aceptadas) },
  {
    key: 'despues',
    header: 'Pedidos después de la oferta',
    numeric: true,
    render: (row) => formatNumber(row.ofertas.pedidos_despues),
  },
]

function Kind({ random }) {
  return random ? (
    <span className="chip">al azar</span>
  ) : (
    <span className="chip chip--warn">describe, no mide efecto</span>
  )
}

/** Sin nadie asignado: en el grupo de control, si está apagado (OFFERS_CONTROL_PCT en 0) o si nadie llegó todavía. */
function NobodyYet({ experiment }) {
  if (experiment.id === 'ofertas_control' && experiment.control_pct === 0) {
    return (
      <EmptyState title="El grupo de control está apagado">
        Con OFFERS_CONTROL_PCT en 0 nadie tiene variante y {AGENT_NAME} no retiene ninguna oferta. Para medir el efecto
        de sus ofertas, la API se levanta con OFFERS_CONTROL_PCT entre 1 y 50 (la parte de las personas que queda en
        control).
      </EmptyState>
    )
  }
  return (
    <EmptyState title="Nadie tiene variante todavía">
      Cada persona recibe la suya al abrir la app (o al pedir su primera oferta) y la conserva.
    </EmptyState>
  )
}

function GroupSizes({ variants }) {
  const sizes = variants.map((row) => `${formatNumber(row.personas)} en ${row.variante}`).join(' y ')
  return (
    <p className="block-note" data-testid="tamano-grupos">
      Grupos: {sizes}. Con pocas personas por grupo, la diferencia entre ellos no es concluyente.
    </p>
  )
}

function Experiment({ experiment }) {
  const offers = experiment.id === 'ofertas_control'
  const empty = assignedPeople(experiment) === 0
  const label = experimentLabel(experiment.id)
  return (
    <div className="block">
      <h3 className="subhead">
        {label} <Kind random={experiment.al_azar} />
      </h3>
      <p className="block-note">{experiment.nota}</p>
      {empty ? (
        <NobodyYet experiment={experiment} />
      ) : (
        <>
          {offers && <GroupSizes variants={experiment.variantes} />}
          <DataTable
            caption={label}
            columns={offers ? [...GROUP_COLUMNS, ...OFFER_COLUMNS] : GROUP_COLUMNS}
            rows={experiment.variantes}
            rowKey={(row) => row.variante}
          />
        </>
      )}
    </div>
  )
}

function Experiments({ source }) {
  const { experimentos } = useAnalytics('experimentos', source)
  return experimentos.map((experiment) => <Experiment key={experiment.id} experiment={experiment} />)
}

/** Los experimentos del MVP: cada persona con una variante estable, comparadas dentro de una sola población. */
export function ExperimentsView({ source }) {
  return (
    <div className="view">
      <section className="section" aria-labelledby="experimentos">
        <div className="section-head">
          <h2 id="experimentos" tabIndex={-1}>
            Experimentos del MVP
          </h2>
          <p>
            Cada persona tiene una variante por experimento, asignada una vez. Solo un experimento al azar mide un
            efecto; uno elegido por alguien describe. Las cifras cuentan desde que se asignó la variante. La tabla de
            Rappi (combinar verticales retiene más) es una correlación: medir el efecto pide un grupo de control.
          </p>
          <ProvenanceBadge kind={source} />
        </div>
        <div className="block">
          <SourceNote source={source} />
          <Async>
            <Experiments source={source} />
          </Async>
        </div>
      </section>
    </div>
  )
}
