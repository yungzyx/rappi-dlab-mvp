import { AGENT_NAME } from '../../lib/agentName.js'
import { Async } from '../../components/Async.jsx'
import { DataTable } from '../../components/DataTable.jsx'
import { Caveat } from '../../components/Caveat.jsx'
import { SectionHead } from '../../components/SectionHead.jsx'
import { Panel } from '../../components/Panel.jsx'
import { EmptyState } from '../../components/States.jsx'
import { formatNumber, formatPct, formatPoints } from '../../lib/format.js'
import { useAnalytics } from '../../lib/useAnalytics.js'
import { GoalValue } from './GoalValue.jsx'
import { Adoption, Hypotheses } from './Hypotheses.jsx'
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
// una desde su asignación, sin tope (también en M+1), contada en los dos grupos con lo que anota la API de las que la
// app pide igual en los dos (control las pide aunque no tenga a Mochi): en control, la oferta retenida
// (offer_withheld); en tratamiento, la misma oferta entregada (offer_eligible). La parte expuesta para el efecto entre
// expuestos es la de la tabla de retención: misma cohorte y antes de M+1 (docs/plan-piloto.md).
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
    header: 'Con oferta elegible antes de M+1',
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
        Con OFFERS_CONTROL_PCT en 0 nadie tiene variante y {AGENT_NAME} está para todos. Para medir su efecto, la API se
        levanta con OFFERS_CONTROL_PCT entre 1 y 50 (la parte de las personas que queda en control, con {AGENT_NAME}{' '}
        apagado).
      </EmptyState>
    )
  }
  return (
    <EmptyState title="Nadie tiene variante todavía" inline>
      Cada persona recibe la suya al abrir la app (o al pedir su primera oferta) y la conserva.
    </EmptyState>
  )
}

/** El tamaño de cada grupo y, si se sabe, el que pide el plan de piloto para medir la meta de la H1 (+2 puntos). */
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
        Con oferta elegible antes de M+1: de esta misma cohorte, con una oferta retenible entre su asignación y el
        inicio de M+1, contada igual en los dos grupos con lo que anota la API. En tratamiento puede no haberla visto
        (la Home estaba tapada, {AGENT_NAME} en silencio o la había rechazado antes). Es la parte expuesta del plan de
        piloto: el efecto entre expuestos es la diferencia dividida por esa parte, si en quien no tuvo una oferta el
        efecto es cero.
      </p>
    </>
  )
}

/** Cómo se cuentan las personas con oferta: igual en los dos grupos, con lo que anota la API. */
function OfferedNote() {
  return (
    <p className="block-note" data-testid="expuestas-nota">
      Personas con oferta: con una oferta que {AGENT_NAME} propone solo desde su asignación, sin tope. Los dos grupos se
      cuentan igual, con lo que anota la API de lo que la app pide en los dos (control la pide aunque no la vea): en
      control la oferta retenida y en tratamiento la misma oferta entregada, la haya alcanzado a mostrar la app o no.
      "Muéstrame algo nuevo" no cuenta: se pide en el menú de la mascota, que control no tiene.
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

/**
 * Los experimentos del MVP, en el orden del gerente: primero las tres hipótesis (retención, frecuencia y venta cruzada,
 * y "¿Encontraste lo que buscabas?") y cuánto vale su meta con los supuestos de quien presenta, después la adopción y el apagado de Mochi y al final la mecánica de cada
 * experimento (cada persona con una variante estable, comparadas dentro de una sola población).
 */
export function ExperimentsView({ source }) {
  return (
    <div className="view">
      <section className="section" aria-labelledby="hipotesis">
        <SectionHead
          id="hipotesis"
          title="Las tres hipótesis"
          meta="Tratamiento contra el grupo de control de las ofertas"
          source={source}
          help={
            <>
              <p>
                H1: retención M+1 (meta +2 puntos). H2: pedidos por persona en 30 días y, de los clientes de
                Restaurantes, la parte que pide en Turbo en 28 días (meta +10 % relativo sobre el control). H3: el % de
                "Sí" a "¿Encontraste lo que buscabas?", con la prueba a una cola y sin umbral. Todo cuenta desde la
                asignación, por intención de tratar (docs/plan-piloto.md).
              </p>
              <p>
                Bajo el mínimo de cada una, la diferencia no es concluyente y va sin intervalo. El mínimo de la H1 es
                para +2 puntos; el de +5 puntos, que pide unas seis veces menos personas, queda como referencia en el
                plan de piloto.
              </p>
              <p>
                El control es {AGENT_NAME} apagado: no ve la mascota, no recibe ofertas suyas y busca con el buscador de
                siempre, sin sus tarjetas, planes, chips ni sugerencias. Conserva "Para ti" y el orden de la Home, que
                Rappi ya tiene. La pregunta "¿Encontraste lo que buscabas?" le sale igual.
              </p>
            </>
          }
        />
        <div className="block">
          <Async>
            <Hypotheses source={source} />
          </Async>
        </div>
      </section>

      <section className="section" aria-labelledby="valor-meta">
        <SectionHead
          id="valor-meta"
          title="¿Cuánto vale la meta?"
          meta="La H1 y la H2 en margen, con tus números"
          help={
            <>
              <p>
                El método: margen de más = pedidos de más × valor promedio del pedido × margen por pedido, mes a mes,
                con y sin el proyecto. La fórmula de cada meta está en su ayuda.
              </p>
              <p>
                Los campos parten vacíos: el panel no trae cifras de Rappi. Lo que escribes no va a la API ni sale del
                navegador; queda en esta pestaña hasta que la cierras o tocas "Borrar". Separador decimal: coma.
              </p>
            </>
          }
        >
          <Caveat>Con tus supuestos: no son datos del panel ni evidencia.</Caveat>
          <Caveat>
            Correlación no es efecto: la meta solo vale lo que dice esta cuenta si el grupo de control la confirma.
          </Caveat>
        </SectionHead>
        <div className="block">
          <GoalValue />
        </div>
      </section>

      <section className="section" aria-labelledby="adopcion">
        <SectionHead
          id="adopcion"
          title="Adopción y apagado"
          source={source}
          help={
            <p>
              Usaron a {AGENT_NAME}: buscaron o preguntaron en su buscador o aceptaron una oferta suya desde la
              asignación (tocar la mascota no deja un evento propio). Oculto: su último cambio fue ocultarlo.
              Silenciado: lo silenciaron por hoy alguna vez; no cuenta como ocultarlo. En control las tres quedan en 0
              por diseño: tiene a {AGENT_NAME} apagado, sin mascota que ocultar ni buscador con {AGENT_NAME}. Sin
              grupos, las personas activas de 30 días.
            </p>
          }
        />
        <div className="block">
          <Async>
            <Adoption source={source} />
          </Async>
        </div>
      </section>

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
