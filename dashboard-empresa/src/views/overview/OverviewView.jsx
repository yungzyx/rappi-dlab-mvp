import { AGENT_NAME } from '../../lib/agentName.js'
import { Async } from '../../components/Async.jsx'
import { SectionHead } from '../../components/SectionHead.jsx'
import { useAnalytics, useAnalyticsMany } from '../../lib/useAnalytics.js'
import { DecisionBody, DecisionCard } from './DecisionCard.jsx'
import { churnDecision, crossSellDecision, demandDecision, mochiDecision } from './decisions.js'
import { Pulse, WeeklyChart } from './Pulse.jsx'
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
  return <DecisionBody decision={mochiDecision(offers, suggestions, source)} source={source} />
}

function Demand({ source }) {
  const [kpis, weekly, opportunities, unmet] = useAnalyticsMany(['kpis', 'weekly', 'opportunities', 'unmet'], source)
  return (
    <DecisionBody decision={demandDecision({ kpis, weekly, asOf: kpis.as_of, opportunities, unmet })} source={source} />
  )
}

/**
 * La vista principal: cómo va el negocio (5 indicadores y la serie semanal) y las 4 preguntas que hay que decidir, cada
 * una con enlace a su detalle.
 */
export function OverviewView({ source, onNavigate }) {
  return (
    <div className="view">
      <section className="section" aria-labelledby="como-va">
        <SectionHead
          id="como-va"
          title="Cómo va"
          meta="Última semana completa frente a la de hace 4 semanas"
          source={source}
          help={
            <p>
              Cada indicador compara la última semana completa con la de hace 4 semanas; el cambio va en rojo solo si
              empeora. Frecuencia y 2 o más verticales usan ventanas de 30 y 60 días y no tienen serie semanal. En la
              tabla de Rappi, quien combina verticales vuelve más: por eso se sigue ese porcentaje.
            </p>
          }
        />
        <Async>
          <Pulse source={source} />
        </Async>
      </section>

      <div className="pair pair--7-5 overview-pair">
        <section className="section" aria-labelledby="que-decidir">
          <SectionHead
            id="que-decidir"
            title="Qué decidir"
            help={
              <p>
                Cada pregunta trae su cifra, su comparación y una acción cuando los datos la sostienen. Solo la del dato
                de Rappi es una sugerencia; con datos simulados es un ejemplo de la mecánica y con los del prototipo,
                algo para revisar. Ninguna se escala sin un grupo de control.
              </p>
            }
          />
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
        <Async>
          <WeeklyChart source={source} />
        </Async>
      </div>
    </div>
  )
}
