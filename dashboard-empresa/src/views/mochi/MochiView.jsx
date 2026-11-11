import { AGENT_NAME } from '../../lib/agentName.js'
import { Async } from '../../components/Async.jsx'
import { DataTable } from '../../components/DataTable.jsx'
import { Delta } from '../../components/Delta.jsx'
import { Caveat } from '../../components/Caveat.jsx'
import { SectionHead } from '../../components/SectionHead.jsx'
import { Panel } from '../../components/Panel.jsx'
import { Meter } from '../../components/Meter.jsx'
import { EmptyState } from '../../components/States.jsx'
import { Stats } from '../../components/Stats.jsx'
import { formatNumber, formatPct, formatSignedPct } from '../../lib/format.js'
import { verticalLabel } from '../../lib/labels.js'
import { useAnalytics, useAnalyticsMany } from '../../lib/useAnalytics.js'
import { thinAssortment } from './demand.js'
import { CtrByPosition, SessionFunnel } from './ListsAndFunnel.jsx'
import { MotorCheck } from './MotorCheck.jsx'
import { OffersByMoment } from './OffersByMoment.jsx'
import { Presence } from './Presence.jsx'
import { offerTotals, suggestionTotals } from './offers.js'
import { ServiceEngagement } from './ServiceEngagement.jsx'
import { SuggestionRanking } from './SuggestionRanking.jsx'
import { splitTrends } from './trends.js'
import { UnmetDemand } from './UnmetDemand.jsx'
import { UnmetSearches } from './UnmetSearches.jsx'

const TOP_RISING = 5

function OfferStats({ source }) {
  const [offers, suggestions] = useAnalyticsMany(['offers', 'suggestions'], source)
  const totals = offerTotals(offers.momentos)
  const cross = suggestionTotals(suggestions)
  if (!totals.shown && !cross.shown) return null
  return (
    <Stats
      items={[
        {
          label: 'Ofertas mostradas',
          value: formatNumber(totals.shown),
          note: `a ${formatNumber(offers.personas)} ${offers.personas === 1 ? 'persona' : 'personas'}`,
        },
        {
          label: 'Aceptadas',
          value: totals.rate === null ? formatNumber(totals.accepted) : formatPct(totals.rate),
          note:
            totals.rate === null ? 'la tasa aparece desde 10 mostradas' : `${formatNumber(totals.accepted)} ofertas`,
        },
        {
          label: 'Entre verticales, llegan a pedido',
          value: cross.convertRate === null ? formatNumber(cross.converted) : formatPct(cross.convertRate),
          note:
            cross.convertRate === null
              ? 'sugerencias aceptadas que terminaron en pedido'
              : `de las ${formatNumber(cross.accepted)} sugerencias aceptadas`,
        },
      ]}
    />
  )
}

function Suggestions({ source }) {
  return <SuggestionRanking rows={useAnalytics('suggestions', source)} />
}

/**
 * Por momento, a todo el ancho (7 columnas), con qué es rechazar y abrir a demanda. Con los simulados no hay momentos (el
 * simulador no los guarda): en su lugar, una línea que lo dice.
 */
function Moments({ source }) {
  const offers = useAnalytics('offers', source)
  const noMoments = offers.momentos.length > 0 && offers.momentos.every((row) => row.momento === 'sin_momento')
  if (source === 'synthetic' && noMoments) return <OffersByMoment data={offers} source={source} />
  return (
    <Panel
      title="Por momento"
      help={
        <>
          <p>
            Rechazada: tocar "Ahora no" (Carro) o "Después" (Vertical por probar, Recompra y Volver a pedir). Los otros
            momentos no tienen ese botón y muestran una raya. Una oferta que no se toca no es un rechazo: no se cuenta.
          </p>
          <p>
            Abierta: tocar el botón que abre su vertical ("Ver …", "Abrir …"); dice que la persona fue a mirar, no que
            la aceptó.
          </p>
        </>
      }
    >
      <OffersByMoment data={offers} source={source} />
    </Panel>
  )
}

function Services({ source }) {
  return <ServiceEngagement rows={useAnalytics('services', source)} />
}

function AgentPresence({ source }) {
  return <Presence data={useAnalytics('presencia', source)} source={source} />
}

function Motor({ source }) {
  return <MotorCheck data={useAnalytics('motor', source)} source={source} />
}

/**
 * Las cuentas de búsquedas sin resultado y, debajo, la demanda agrupada (5 o más personas, con su acción) o, si ninguna
 * llega a ese mínimo, las búsquedas sin resultado por vertical y concepto.
 */
function Unmet({ source }) {
  const [opportunities, unmet] = useAnalyticsMany(['opportunities', 'unmet'], source)
  return (
    <>
      <UnmetSearches data={unmet} table={!opportunities.length} />
      {opportunities.length > 0 && (
        <Panel title="Demanda sin oferta">
          <UnmetDemand rows={opportunities} />
        </Panel>
      )}
    </>
  )
}

function Ctr({ source }) {
  return <CtrByPosition data={useAnalytics('ctr-posicion', source)} />
}

function Funnel({ source }) {
  return <SessionFunnel rows={useAnalytics('embudo-sesion', source)} />
}

function Rising({ source }) {
  const [trends, opportunities] = useAnalyticsMany(['trends', 'opportunities'], source)
  const rising = splitTrends(trends).rising.slice(0, TOP_RISING)
  if (!rising.length) {
    return (
      <EmptyState title="Ningún concepto sube" inline>
        La comparación pide 20 o más señales de interés en las 4 semanas anteriores.
      </EmptyState>
    )
  }
  const unmet = new Set(opportunities.map((row) => row.concept_id).filter(Boolean))
  const max = Math.max(...rising.map((row) => row.recientes))
  const columns = [
    {
      key: 'concepto',
      header: 'Concepto',
      primary: true,
      render: (row) => (
        <span className="cell-stack">
          <strong>{row.concepto}</strong>
          {unmet.has(row.concept_id) && <span className="chip chip--warn">sin surtido</span>}
        </span>
      ),
    },
    {
      key: 'senales',
      header: 'Interés: ahora vs antes',
      numeric: true,
      render: (row) => (
        <span className="cell-bar">
          <Meter value={row.recientes} max={max} />
          {formatNumber(row.recientes)} vs {formatNumber(row.anteriores)}
        </span>
      ),
    },
    {
      key: 'cambio',
      header: 'Cambio',
      numeric: true,
      render: (row) => <Delta value={row.crecimiento_pct} format={formatSignedPct} goodWhen={null} />,
    },
  ]
  return <DataTable caption="Conceptos que suben" columns={columns} rows={rising} rowKey={(row) => row.concept_id} />
}

function Thin({ source }) {
  const rows = thinAssortment(useAnalytics('assortment', source))
  if (!rows.length) {
    return (
      <EmptyState title="Ningún concepto tiene más personas buscando que productos" inline>
        Se compara con los productos reales de la muestra pública.
      </EmptyState>
    )
  }
  const columns = [
    {
      key: 'concepto',
      header: 'Concepto',
      primary: true,
      render: (row) => (
        <span className="cell-stack">
          <strong>{row.concepto}</strong>
          <span className="cell-sub">en {verticalLabel(row.vertical)}</span>
        </span>
      ),
    },
    { key: 'buscan', header: 'Personas', numeric: true, render: (row) => formatNumber(row.usuarios_que_buscan) },
    { key: 'items', header: 'Productos', numeric: true, render: (row) => formatNumber(row.items_en_catalogo) },
    {
      key: 'ratio',
      header: 'Personas por producto',
      numeric: true,
      render: (row) => formatNumber(row.usuarios_por_item, 1),
    },
  ]
  return (
    <DataTable
      caption="Poco surtido para lo que se busca"
      columns={columns}
      rows={rows}
      rowKey={(row) => `${row.concepto}-${row.vertical}`}
    />
  )
}

/**
 * RappiAds: qué ofrece Mochi, en qué momento y con qué resultado, y qué busca la gente que no encuentra. Con `tab` (la
 * subpestaña), solo sus secciones ("ofertas" lleva también "¿Mochi molesta?"); sin `tab`, todas.
 */
export function MochiView({ source, tab }) {
  const show = (id) => !tab || tab === id
  return (
    <div className="view">
      {show('ofertas') && (
        <>
          <section className="section" aria-labelledby="ofertas">
            <SectionHead
              id="ofertas"
              title={`Lo que ofrece ${AGENT_NAME}`}
              source={source}
              help={
                <p>
                  A quién le ofrece qué, en qué momento y con qué resultado. Aceptada: la oferta se agregó al carro. La
                  tasa aparece desde 10 mostradas; antes, solo las cuentas.
                </p>
              }
            />
            <Async fallback={null}>
              <OfferStats source={source} />
            </Async>
            <Async>
              <Moments source={source} />
            </Async>
            <div className="pair pair--7-5">
              <Panel title="Entre verticales: qué se acepta">
                <Async>
                  <Suggestions source={source} />
                </Async>
              </Panel>
              <Panel title="Servicios sin catálogo">
                <Async>
                  <Services source={source} />
                </Async>
              </Panel>
            </div>
            <Panel
              title="El motor contra una regla simple"
              help={
                <p>
                  Compara lo que decide el motor con una regla simple, en pedidos posteriores a los que usó para
                  aprender.
                </p>
              }
            >
              <Async>
                <Motor source={source} />
              </Async>
            </Panel>
          </section>

          <section className="section" aria-labelledby="presencia">
            <SectionHead
              id="presencia"
              title={`¿${AGENT_NAME} molesta?`}
              meta="Últimos 30 días"
              source={source}
              help={
                <p>
                  Oculto es quien lo ocultó y no lo trajo de vuelta en Cuenta. Si muchas personas lo ocultan,{' '}
                  {AGENT_NAME} molesta: hay que revisar cada cuánto habla y propone.
                </p>
              }
            />
            <Async>
              <AgentPresence source={source} />
            </Async>
          </section>
        </>
      )}

      {show('listas') && (
        <section className="section" aria-labelledby="listas">
          <SectionHead
            id="listas"
            title="Qué se ve y qué se toca"
            source={source}
            help={
              <p>
                A la vista: el elemento quedó al menos la mitad en pantalla. CTR: de lo que quedó a la vista en cada
                lugar, cuánto se tocó. El embudo cuenta sesiones y cada paso exige los anteriores.
              </p>
            }
          />
          <div className="pair">
            <Async>
              <Ctr source={source} />
            </Async>
            <Async>
              <Funnel source={source} />
            </Async>
          </div>
        </section>
      )}

      {show('busquedas') && (
        <section className="section" aria-labelledby="busquedas">
          <SectionHead
            id="busquedas"
            title="Qué buscan y no encuentran"
            source={source}
            help={
              <p>
                Cada búsqueda o pregunta a {AGENT_NAME} sin resultado es demanda que el catálogo no cubre: qué falta,
                dónde y para cuántas personas. La demanda se agrupa cuando la pidieron 5 o más personas. Nunca se
                muestra el texto que escribió la persona ni un concepto sensible.
              </p>
            }
          >
            <Caveat>
              "No está en la muestra" no es "Rappi no lo vende": la muestra pública trae hasta 24 productos por
              sub-pasillo.
            </Caveat>
          </SectionHead>
          <Async>
            <Unmet source={source} />
          </Async>
          <div className="pair">
            <Panel
              title="Lo que sube"
              meta="Últimas 4 semanas frente a las 4 anteriores"
              help={
                <p>
                  Suma búsquedas, preguntas a {AGENT_NAME} y agregados al carro. Lo que sube y tiene surtido es campaña
                  con horario; lo que sube "sin surtido", demanda que cubrir. La comparación pide 20 o más señales en
                  las 4 semanas anteriores.
                </p>
              }
            >
              <Async>
                <Rising source={source} />
              </Async>
            </Panel>
            <Panel
              title="Poco surtido para lo que se busca"
              meta="Productos reales de la muestra pública"
              help={<p>Conceptos con más personas buscando que productos en el catálogo.</p>}
            >
              <Async>
                <Thin source={source} />
              </Async>
            </Panel>
          </div>
        </section>
      )}
    </div>
  )
}
