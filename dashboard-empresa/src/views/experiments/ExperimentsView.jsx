import { AGENT_NAME } from '../../lib/agentName.js'
import { Async } from '../../components/Async.jsx'
import { DataTable } from '../../components/DataTable.jsx'
import { Caveat } from '../../components/Caveat.jsx'
import { SectionHead } from '../../components/SectionHead.jsx'
import { Panel } from '../../components/Panel.jsx'
import { EmptyState } from '../../components/States.jsx'
import { formatNumber, formatPct, formatPoints } from '../../lib/format.js'
import { useAnalytics } from '../../lib/useAnalytics.js'
import { assignedPeople, cohortPeople, experimentLabel, offeredPct, orderedPct, variantLabel } from './experiments.js'

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

// En el grupo de control, además, las ofertas de los momentos que Mochi propone solo. Las personas con oferta tienen
// una desde su asignación, sin tope (también en M+1), contada en los dos grupos con lo que anota la API: en control, la
// oferta retenida (offer_withheld); en tratamiento, la misma oferta entregada (offer_eligible). La parte expuesta para
// el efecto entre expuestos es la de la tabla de retención: misma cohorte y antes de M+1 (docs/plan-piloto.md).
const OFFER_COLUMNS = [
  {
    key: 'mostradas',
    header: 'Ofertas mostradas',
    numeric: true,
    render: (row) => formatNumber(row.ofertas.mostradas),
  },
  { key: 'retenidas', header: 'Retenidas', numeric: true, render: (row) => formatNumber(row.ofertas.retenidas) },
  {
    key: 'con_oferta',
    header: 'Personas con oferta',
    numeric: true,
    render: (row) => (
      <span className="cell-stack">
        {formatNumber(row.ofertas.personas_con_oferta)}
        {row.personas > 0 && <span className="cell-sub">{formatPct(offeredPct(row))}</span>}
      </span>
    ),
  },
  { key: 'aceptadas', header: 'Aceptadas', numeric: true, render: (row) => formatNumber(row.ofertas.aceptadas) },
  {
    key: 'despues',
    header: 'Pedidos después de la oferta',
    numeric: true,
    render: (row) => formatNumber(row.ofertas.pedidos_despues),
  },
]

// La retención del grupo de control (docs/plan-piloto.md): por variante y, al final, la diferencia; su IC de 95 % solo
// llega cuando cada grupo alcanza el mínimo (antes, con pocas personas, se encogería y parecería un efecto).
const DIFFERENCE = 'diferencia'

function RetentionCell({ row, pct, difference }) {
  if (row.variante !== DIFFERENCE) return formatPct(row[pct])
  if (!difference) return formatPct(null)
  if (!difference.ic95) return formatPoints(difference.puntos)
  return (
    <span className="cell-stack">
      {formatPoints(difference.puntos)}
      <span className="cell-sub">
        IC 95 %: {formatNumber(difference.ic95[0], 1)} a {formatNumber(difference.ic95[1], 1)}
      </span>
    </span>
  )
}

const retentionColumns = (diferencia) => [
  {
    key: 'variante',
    header: 'Variante',
    primary: true,
    render: (row) => (
      <strong>{row.variante === DIFFERENCE ? 'Diferencia (tratamiento − control)' : variantLabel(row.variante)}</strong>
    ),
  },
  {
    key: 'personas',
    header: 'Personas con su mes siguiente completo',
    numeric: true,
    render: (row) => formatNumber(row.personas),
  },
  {
    key: 'expuestas',
    header: 'Expuestas antes de M+1',
    numeric: true,
    render: (row) =>
      row.variante === DIFFERENCE ? (
        formatPct(null)
      ) : (
        <span className="cell-stack">
          {formatNumber(row.expuestas)}
          {row.personas > 0 && <span className="cell-sub">{formatPct(row.expuestas_pct)}</span>}
        </span>
      ),
  },
  {
    key: 'retencion',
    header: 'Retención M+1',
    numeric: true,
    render: (row) => <RetentionCell row={row} pct="retencion_m1_pct" difference={diferencia?.retencion_m1} />,
  },
  {
    key: 'suma',
    header: 'Suma una vertical nueva en 28 días',
    numeric: true,
    render: (row) => <RetentionCell row={row} pct="suma_vertical_pct" difference={diferencia?.suma_vertical} />,
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
      <EmptyState title="El grupo de control está apagado" inline>
        Con OFFERS_CONTROL_PCT en 0 nadie tiene variante y {AGENT_NAME} no retiene ninguna oferta. Para medir el efecto
        de sus ofertas, la API se levanta con OFFERS_CONTROL_PCT entre 1 y 50 (la parte de las personas que queda en
        control).
      </EmptyState>
    )
  }
  return (
    <EmptyState title="Nadie tiene variante todavía" inline>
      Cada persona recibe la suya al abrir la app (o al pedir su primera oferta) y la conserva.
    </EmptyState>
  )
}

/** El tamaño de cada grupo y, si se sabe, el que pide el plan de piloto para medir +5 puntos de retención M+1. */
function GroupSizes({ variants, retention }) {
  const sizes = variants.map((row) => `${formatNumber(row.personas)} en ${row.variante}`).join(' y ')
  const minimum = retention?.minimo
  const needed =
    minimum && variants.map((row) => `${formatNumber(minimum[row.variante])} en ${row.variante}`).join(' y ')
  return (
    <p className="block-note" data-testid="tamano-grupos">
      Grupos: {sizes}.{' '}
      {needed &&
        `Para medir +${retention.efecto_minimo_puntos} puntos de retención M+1 harían falta ${needed} (plan de ` +
          `piloto, sobre el ${formatPct(retention.base_pct, 0)} de "solo Restaurantes" en la tabla de Rappi, un ` +
          'supuesto). '}
      Con menos personas por grupo, la diferencia entre ellos no es concluyente.
    </p>
  )
}

/** La retención M+1 y la parte que suma una vertical nueva, por variante, en la cohorte con su mes siguiente completo. */
function Retention({ retention }) {
  if (cohortPeople(retention) === 0) {
    return (
      <p className="block-note" data-testid="retencion-nota">
        Nadie tiene todavía su mes siguiente completo: la retención M+1 cuenta a quienes recibieron la variante en un
        mes que ya tuvo el siguiente entero.
      </p>
    )
  }
  const rows = [...retention.variantes, { variante: DIFFERENCE }]
  return (
    <>
      <DataTable
        caption="Retención M+1 por grupo"
        columns={retentionColumns(retention.diferencia)}
        rows={rows}
        rowKey={(row) => row.variante}
      />
      <p className="block-note" data-testid="retencion-nota">
        {retention.concluyente
          ? 'Cada grupo llega al mínimo del plan de piloto: la diferencia se lee con su intervalo.'
          : 'No es concluyente: los grupos no llegan al mínimo del plan de piloto.'}
      </p>
      <p className="block-note" data-testid="expuestas-cohorte-nota">
        Expuestas antes de M+1: de esta misma cohorte, con una oferta retenible entre su asignación y el inicio de M+1,
        contada igual en los dos grupos. Es la parte expuesta del plan de piloto: el efecto entre expuestos es la
        diferencia dividida por esa parte, si en quien no tuvo una oferta el efecto es cero.
      </p>
    </>
  )
}

/** Cómo se cuentan las personas con oferta: igual en los dos grupos, con lo que anota la API. */
function OfferedNote() {
  return (
    <p className="block-note" data-testid="expuestas-nota">
      Personas con oferta: con una oferta que {AGENT_NAME} propone solo desde su asignación, sin tope. Los dos grupos se
      cuentan igual, con lo que anota la API: en control la oferta retenida y en tratamiento la misma oferta entregada,
      la haya alcanzado a mostrar la app o no.
    </p>
  )
}

function Experiment({ experiment }) {
  const offers = experiment.id === 'ofertas_control'
  const empty = assignedPeople(experiment) === 0
  const label = experimentLabel(experiment.id)
  return (
    <Panel
      title={
        <>
          {label} <Kind random={experiment.al_azar} />
        </>
      }
    >
      <p className="block-note">{experiment.nota}</p>
      {empty ? (
        <NobodyYet experiment={experiment} />
      ) : (
        <>
          {offers && <GroupSizes variants={experiment.variantes} retention={experiment.retencion} />}
          <DataTable
            caption={label}
            columns={offers ? [...GROUP_COLUMNS, ...OFFER_COLUMNS] : GROUP_COLUMNS}
            rows={experiment.variantes}
            rowKey={(row) => row.variante}
          />
          {offers && <OfferedNote />}
          {offers && experiment.retencion && <Retention retention={experiment.retencion} />}
        </>
      )}
    </Panel>
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
        <SectionHead
          id="experimentos"
          title="Experimentos del MVP"
          source={source}
          help={
            <p>
              Cada persona tiene una variante por experimento, asignada una vez; las cifras cuentan desde esa
              asignación. Solo un experimento al azar mide un efecto; uno elegido por alguien describe.
            </p>
          }
        >
          <Caveat>
            La tabla de Rappi (combinar verticales retiene más) es una correlación: medir el efecto pide un grupo de
            control.
          </Caveat>
        </SectionHead>
        <div className="block">
          <Async>
            <Experiments source={source} />
          </Async>
        </div>
      </section>
    </div>
  )
}
