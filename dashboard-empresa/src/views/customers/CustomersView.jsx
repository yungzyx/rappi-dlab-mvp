import { AGENT_NAME } from '../../lib/agentName.js'
import { Async } from '../../components/Async.jsx'
import { ProvenanceBadge } from '../../components/ProvenanceBadge.jsx'
import { SourceNote } from '../../components/SourceNote.jsx'
import { useAnalytics } from '../../lib/useAnalytics.js'
import { Churn } from './Churn.jsx'
import { RetentionLadder } from './RetentionLadder.jsx'
import './customers.css'

// La tabla de Rappi no depende de la fuente: se lee con la simulada, que tiene respaldo sin conexión.
function Ladder() {
  const { rappi } = useAnalytics('combos', 'synthetic')
  return (
    <>
      <RetentionLadder rappi={rappi} />
      <p className="block-note">
        {rappi.nota} Retail agrupa todo el comercio que no es restaurante ni Turbo; Favor no tiene una combinación con
        un grupo más en la tabla. {AGENT_NAME} ofrece el paso como «vertical por probar»; solo un grupo de control mide
        si sumar la vertical hace volver.
      </p>
    </>
  )
}

/** Gerencia: dónde está la venta cruzada (la tabla de Rappi) y a quién estamos perdiendo (la fuente elegida). */
export function CustomersView({ source }) {
  return (
    <div className="view">
      <section className="section" aria-labelledby="venta-cruzada">
        <div className="section-head">
          <h2 id="venta-cruzada" tabIndex={-1}>
            Dónde está la venta cruzada
          </h2>
          <p>
            En la tabla que compartió Rappi, quien combina grupos de verticales vuelve más al mes siguiente y pide más.
            Es una correlación, no un efecto. Cada fila: cuántos vuelven en una combinación y en la combinación con un
            grupo más que más retiene; arriba, donde están más usuarios.
          </p>
          <ProvenanceBadge kind="rappi" />
        </div>
        <div className="block">
          <Async>
            <Ladder />
          </Async>
        </div>
      </section>

      <section className="section" aria-labelledby="perdiendo">
        <div className="section-head">
          <h2 id="perdiendo" tabIndex={-1}>
            A quién estamos perdiendo
          </h2>
          <p>
            Cada persona tiene su propio ritmo de compra, y el riesgo se mide contra ese ritmo. El concepto que se
            muestra nunca es sensible, y fuera de la app solo se escribe a quien aceptó avisos.
          </p>
          <ProvenanceBadge kind={source} />
        </div>
        <div className="block">
          <SourceNote source={source} />
          <Async>
            <Churn source={source} />
          </Async>
        </div>
      </section>
    </div>
  )
}
