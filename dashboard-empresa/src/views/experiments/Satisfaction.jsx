import { AGENT_NAME } from '../../lib/agentName.js'
import { Caveat } from '../../components/Caveat.jsx'
import { EmptyState } from '../../components/States.jsx'
import { formatNumber, formatPct, formatPoints } from '../../lib/format.js'
import { useAnalytics } from '../../lib/useAnalytics.js'
import { Figure, GroupTable, HypothesisCard, Interval, MissingHypotheses, valueWithN } from './Hypotheses.jsx'
import {
  byVariant,
  hasHypotheses,
  hypothesesMode,
  offersExperiment,
  pairOf,
  surveyVerdict,
  TREATMENT,
  verdict,
} from './hypotheses.js'

// Las dos proporciones que se comparan como la H3: la parte que responde "Sí" (o que califica con 4 o 5 estrellas),
// con su n, por grupo y con la diferencia; sin grupos, la de toda la población.
const ANSWERS = { n: 'respondidas', pct: 'si_pct', one: 'respuesta', noun: 'respuestas', header: 'Respondió "Sí"' }
const RATINGS = {
  n: 'calificados',
  pct: 'buenos_pct',
  one: 'pedido calificado',
  noun: 'pedidos calificados',
  header: '4 o 5 estrellas',
}
const DESCRIBES = `Toda la fuente, sin grupos: describe, no mide el efecto de ${AGENT_NAME}.`

/** "1 respuesta", "40 respuestas". */
const counted = (n, keys) => `${formatNumber(n)} ${n === 1 ? keys.one : keys.noun}`

/** Una proporción por grupo (o de la población), con su veredicto a una cola, como la tarjeta de la H3. */
function ShareCard({ id, tag, title, goal, question, block, population, keys, unit, empty, mode, source }) {
  const common = { id, tag, title, goal, question }
  if (mode === 'poblacion') {
    return (
      <HypothesisCard {...common} status={verdict({ mode })} note={DESCRIBES}>
        <Figure
          value={formatPct(population[keys.pct])}
          unit={population[keys.n] ? `${unit} (de ${counted(population[keys.n], keys)})` : empty}
        />
      </HypothesisCard>
    )
  }
  const counts = Object.fromEntries(block.variantes.map((row) => [row.variante, row[keys.n]]))
  return (
    <HypothesisCard
      {...common}
      status={surveyVerdict({ mode, source, survey: block })}
      note={`${pairOf(counts)} ${keys.noun}; se lee desde ${formatNumber(block.minimo)} por grupo, con la prueba a una cola.`}
    >
      <GroupTable
        caption={`${title} por grupo`}
        columns={[
          {
            header: keys.header,
            value: (variant) => {
              const row = byVariant(block.variantes, variant)
              return valueWithN(formatPct(row[keys.pct]), row[keys.n], row[keys.n] === 1 ? keys.one : keys.noun)
            },
            diff: (
              <>
                {formatPoints(block.diferencia?.puntos)}
                <Interval ic95={block.diferencia?.ic95} source={source} />
              </>
            ),
          },
        ]}
      />
    </HypothesisCard>
  )
}

/** La P3: solo hay en tratamiento (el control no ve a Mochi), así que se muestra sin comparar. */
function TrustCard({ trust, population, mode, source }) {
  const common = {
    id: 'satisfaccion-p3',
    tag: 'P3',
    title: `Confía en ${AGENT_NAME}`,
    goal: `De 1 a 5, solo con ${AGENT_NAME} a la vista`,
    question: `"¿Confías en las sugerencias de ${AGENT_NAME}?", después de abrir un "¿Por qué?".`,
  }
  const row = mode === 'poblacion' ? population : byVariant(trust.variantes, TREATMENT)
  const status =
    mode === 'poblacion' || source === 'synthetic'
      ? verdict({ mode, source })
      : { tone: 'muted', label: 'Solo en tratamiento: no tiene con qué compararse' }
  const who = mode === 'poblacion' ? '' : ' en tratamiento'
  return (
    <HypothesisCard
      {...common}
      status={status}
      note={
        mode === 'poblacion'
          ? DESCRIBES
          : `El control tiene a ${AGENT_NAME} apagado: no ve ofertas ni su "¿Por qué?", y no se le pregunta.`
      }
    >
      <Figure
        value={formatNumber(row.promedio, 1)}
        unit={
          row.respondidas ? `de 5 en promedio${who} (${counted(row.respondidas, ANSWERS)})` : 'Nadie respondió todavía'
        }
      />
    </HypothesisCard>
  )
}

/** Una respuesta grabada antes de la satisfacción (sin `satisfaccion`), lo dice en vez de caerse. */
function MissingSatisfaction() {
  return (
    <EmptyState title="Esta respuesta no trae la satisfacción" inline>
      Se ve con la API al día o con una foto grabada desde el 14-11 (npm run panel:snapshot).
    </EmptyState>
  )
}

/**
 * Satisfacción y esfuerzo, en el orden de la tarjeta de la app: encontró lo que buscaba (P1), fue fácil (P2), confía en
 * Mochi (P3) y, del seguimiento, los pedidos bien calificados. Por grupo si los dos tienen personas; si no, toda la
 * población, que describe y no mide.
 */
export function Satisfaction({ source }) {
  const experiment = offersExperiment(useAnalytics('experimentos', source))
  if (!hasHypotheses(experiment)) return <MissingHypotheses />
  const satisfaction = experiment.satisfaccion
  const population = experiment.poblacion.satisfaccion
  if (!satisfaction || !population) return <MissingSatisfaction />
  const mode = hypothesesMode(experiment)
  const simulated = source === 'synthetic'
  const shared = { mode, source }
  return (
    <>
      {mode === 'grupos' && simulated && (
        <Caveat>
          Datos simulados: las respuestas y las calificaciones de los dos grupos siguen supuestos del generador, no lo
          que dijo alguien. Se ven sin veredicto ni intervalo.
        </Caveat>
      )}
      <div className="hypotheses hypotheses--four" data-mode={mode}>
        <ShareCard
          {...shared}
          id="satisfaccion-p1"
          tag="P1"
          title="Encontró lo que buscaba"
          goal="Sin umbral: la diferencia con su intervalo"
          question={`"¿Encontraste lo que buscabas?", igual con ${AGENT_NAME} y sin él: la parte que responde "Sí".`}
          block={experiment.encuesta}
          population={experiment.poblacion.encuesta}
          keys={ANSWERS}
          unit='respondió "Sí"'
          empty="Nadie respondió todavía"
        />
        <ShareCard
          {...shared}
          id="satisfaccion-p2"
          tag="P2"
          title="Fue fácil encontrarlo"
          goal="El esfuerzo, sin umbral: la diferencia con su intervalo"
          question={'"¿Fue fácil encontrarlo?", después de un "Sí" o un "En parte": la parte que responde "Sí".'}
          block={satisfaction.facil}
          population={population.facil}
          keys={ANSWERS}
          unit='respondió "Sí"'
          empty="Nadie respondió todavía"
        />
        <TrustCard trust={satisfaction.confia} population={population.confia} {...shared} />
        <ShareCard
          {...shared}
          id="satisfaccion-pedidos"
          tag="Pedidos"
          title="Pedidos bien calificados"
          goal="Sin umbral: la diferencia con su intervalo"
          question={'"¿Cómo estuvo tu pedido?", en el seguimiento: la parte con 4 o 5 estrellas.'}
          block={satisfaction.pedidos}
          population={population.pedidos}
          keys={RATINGS}
          unit="con 4 o 5 estrellas"
          empty="Ningún pedido calificado todavía"
        />
      </div>
    </>
  )
}
