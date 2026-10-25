import { AGENT_NAME } from '../../lib/agentName.js'
import { Async } from '../../components/Async.jsx'
import { ProvenanceBadge } from '../../components/ProvenanceBadge.jsx'
import { SourceNote } from '../../components/SourceNote.jsx'
import { useAnalytics, useAnalyticsMany } from '../../lib/useAnalytics.js'
import { DecisionBody, DecisionCard } from './DecisionCard.jsx'
import { churnDecision, crossSellDecision, demandDecision, mochiDecision } from './decisions.js'
import { Pulse } from './Pulse.jsx'
import './overview.css'

// La tabla de Rappi viene en /analytics/combos con cualquier fuente: se lee con la simulada, que tiene respaldo sin
// conexión (con la del prototipo y la API caída, el dato de Rappi no tiene por qué caerse).
function CrossSell() {
  return <DecisionBody decision={crossSellDecision(useAnalytics('combos', 'synthetic'))} source="rappi" />
}

function Churn({ source }) {
  const [kpis, winback] = useAnalyticsMany(['kpis', 'volver'], source)
  return <DecisionBody decision={churnDecision(kpis, winback)} source={source} />
}

function Mochi({ source }) {
  const [offers, suggestions] = useAnalyticsMany(['offers', 'suggestions'], source)
  return <DecisionBody decision={mochiDecision(offers, suggestions)} source={source} />
}

function Demand({ source }) {
  const [kpis, weekly, opportunities, unmet] = useAnalyticsMany(['kpis', 'weekly', 'opportunities', 'unmet'], source)
  return (
    <DecisionBody decision={demandDecision({ kpis, weekly, asOf: kpis.as_of, opportunities, unmet })} source={source} />
  )
}

/** La vista principal: las 4 preguntas que hay que decidir, cada una con enlace a su detalle, y cómo va el negocio. */
export function OverviewView({ source, onNavigate }) {
  return (
    <div className="view">
      <section className="section" aria-labelledby="que-decidir">
        <div className="section-head">
          <h2 id="que-decidir">Qué decidir</h2>
          <p>Cada pregunta con su cifra, su comparación y una acción. Ninguna se escala sin un grupo de control.</p>
        </div>
        <div className="decisions">
          <DecisionCard
            id="decision-venta-cruzada"
            question="¿Dónde está la venta cruzada?"
            badge="rappi"
            linkLabel="Ver la escalera"
            onOpen={() => onNavigate('clientes', 'venta-cruzada')}
          >
            <CrossSell />
          </DecisionCard>
          <DecisionCard
            id="decision-perdiendo"
            question="¿A quién estamos perdiendo?"
            badge={source}
            linkLabel="Ver a quién y qué le ofrecemos"
            onOpen={() => onNavigate('clientes', 'perdiendo')}
          >
            <Churn source={source} />
          </DecisionCard>
          <DecisionCard
            id="decision-mochi"
            question={`¿Funciona lo que ofrece ${AGENT_NAME}?`}
            badge={source}
            linkLabel="Ver las ofertas"
            onOpen={() => onNavigate('mochi', 'ofertas')}
          >
            <Mochi source={source} />
          </DecisionCard>
          <DecisionCard
            id="decision-busquedas"
            question="¿Qué buscan y no encuentran?"
            badge={source}
            linkLabel="Ver las búsquedas"
            onOpen={() => onNavigate('mochi', 'busquedas')}
          >
            <Demand source={source} />
          </DecisionCard>
        </div>
      </section>

      <section className="section" aria-labelledby="como-va">
        <div className="section-head">
          <h2 id="como-va">Cómo va</h2>
          <p>La última semana completa contra la de hace 4 semanas. Rojo solo si empeora.</p>
          <ProvenanceBadge kind={source} />
        </div>
        <SourceNote source={source} />
        <Async>
          <Pulse source={source} />
        </Async>
      </section>
    </div>
  )
}
