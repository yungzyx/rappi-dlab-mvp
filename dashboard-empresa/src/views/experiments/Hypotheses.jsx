import { AGENT_NAME } from '../../lib/agentName.js'
import { Caveat } from '../../components/Caveat.jsx'
import { DataTable } from '../../components/DataTable.jsx'
import { Icon } from '../../components/Icon.jsx'
import { EmptyState } from '../../components/States.jsx'
import { Stats } from '../../components/Stats.jsx'
import { formatNumber, formatPct, formatPoints } from '../../lib/format.js'
import { useAnalytics } from '../../lib/useAnalytics.js'
import { cohortPeople, variantLabel } from './experiments.js'
import {
  byVariant,
  CONTROL,
  formatSigned,
  hasHypotheses,
  hypothesesMode,
  monthName,
  offersExperiment,
  pairOf,
  surveyVerdict,
  TREATMENT,
  verdict,
} from './hypotheses.js'
import './experiments.css'

const VARIANTS = [TREATMENT, CONTROL]
const SHORT = { [TREATMENT]: 'Tratamiento', [CONTROL]: 'Control' }
const ICONS = { good: 'up', bad: 'down', warn: 'warn' }

/**
 * "IC 95 %: −1,2 a 3,4" de una diferencia, o nada si no lo trae (bajo el mínimo). Con los simulados tampoco: la
 * diferencia la pone un supuesto del generador y un intervalo la haría parecer un hallazgo.
 */
function Interval({ ic95, source, decimals = 1 }) {
  if (!ic95 || source === 'synthetic') return null
  return (
    <span className="cell-sub">
      IC 95 %: {formatNumber(ic95[0], decimals)} a {formatNumber(ic95[1], decimals)}
    </span>
  )
}

/** El estado de la tarjeta: con ícono y texto, nunca solo por color. */
function Verdict({ tone, label }) {
  return (
    <p className={`hypothesis-verdict status status--${tone}`}>
      {ICONS[tone] && <Icon name={ICONS[tone]} />}
      <span>{label}</span>
    </p>
  )
}

/**
 * Una hipótesis: su clave (H1…), el nombre, la meta y la pregunta; el cuerpo (cifras de la población o la tabla por
 * grupo); al pie, su estado y el tamaño de la muestra.
 */
function HypothesisCard({ id, tag, title, goal, question, status, note, children }) {
  return (
    <article className="hypothesis" aria-labelledby={id}>
      <header className="hypothesis-head">
        <p className="hypothesis-tag">{tag}</p>
        <h3 id={id}>{title}</h3>
        <p className="hypothesis-goal">{goal}</p>
      </header>
      <p className="hypothesis-question">{question}</p>
      <div className="hypothesis-body">{children}</div>
      <footer className="hypothesis-foot">
        <Verdict {...status} />
        {note && <p className="hypothesis-note">{note}</p>}
      </footer>
    </article>
  )
}

/** Una cifra de la población con su unidad: lo que se ve sin grupo de control. */
function Figure({ value, unit }) {
  return (
    <p className="hypothesis-figure">
      <strong>{value}</strong>
      <span>{unit}</span>
    </p>
  )
}

/**
 * La comparación por grupo: una fila por grupo y la diferencia al final; `columns`: [{ header, value(variant), diff }].
 * Es una tabla de verdad (con su título para el lector de pantalla), angosta a propósito: cabe en la tarjeta del celular.
 */
function GroupTable({ caption, columns }) {
  return (
    <table className="hypothesis-table">
      <caption className="visually-hidden">{caption}</caption>
      <thead>
        <tr>
          <th scope="col">
            <span className="visually-hidden">Grupo</span>
          </th>
          {columns.map((column) => (
            <th key={column.header} scope="col">
              {column.header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {VARIANTS.map((variant) => (
          <tr key={variant}>
            <th scope="row" title={variantLabel(variant)}>
              {SHORT[variant]}
            </th>
            {columns.map((column) => (
              <td key={column.header}>{column.value(variant)}</td>
            ))}
          </tr>
        ))}
        <tr className="hypothesis-diff">
          <th scope="row">Diferencia</th>
          {columns.map((column) => (
            <td key={column.header}>
              <span className="cell-stack">{column.diff}</span>
            </td>
          ))}
        </tr>
      </tbody>
    </table>
  )
}

const valueWithN = (value, n, noun) => (
  <span className="cell-stack">
    {value}
    <span className="cell-sub">
      {formatNumber(n)} {noun}
    </span>
  </span>
)

function H1({ experiment, mode, source }) {
  const retention = experiment.retencion
  const population = experiment.poblacion.retencion_m1
  const common = {
    id: 'hipotesis-h1',
    tag: 'H1',
    title: 'Retención M+1',
    goal: 'Meta: +2 puntos sobre el control',
    question: 'Del mes en que se asignó el grupo, ¿cuántos vuelven a pedir el mes siguiente?',
  }
  if (mode === 'poblacion') {
    return (
      <HypothesisCard
        {...common}
        status={verdict({ mode })}
        note="Toda la población de la fuente, sin grupos: describe cómo vuelve hoy, no el efecto de Mochi."
      >
        <Figure
          value={formatPct(population.pct)}
          unit={`de ${formatNumber(population.personas)} personas que pidieron en ${monthName(population.mes)} volvieron a pedir en ${monthName(population.mes_siguiente)}`}
        />
      </HypothesisCard>
    )
  }
  const difference = retention.diferencia?.retencion_m1
  const cohort = cohortPeople(retention)
  const note =
    cohort === 0
      ? 'Nadie tiene todavía su mes siguiente completo: la cohorte se lee cuando termine.'
      : `${pairOf(Object.fromEntries(retention.variantes.map((row) => [row.variante, row.personas])))} personas con su mes siguiente completo` +
        (retention.minimo ? `; para +2 puntos harían falta ${pairOf(retention.minimo)}.` : '.')
  return (
    <HypothesisCard
      {...common}
      status={verdict({ mode, source, conclusive: retention.concluyente, ic95: difference?.ic95 })}
      note={note}
    >
      <GroupTable
        caption="Retención M+1 por grupo"
        columns={[
          {
            header: 'Retención M+1',
            value: (variant) => formatPct(byVariant(retention.variantes, variant).retencion_m1_pct),
            diff: (
              <>
                {formatPoints(difference?.puntos)}
                <Interval ic95={difference?.ic95} source={source} />
              </>
            ),
          },
        ]}
      />
    </HypothesisCard>
  )
}

function H2({ experiment, mode, source }) {
  const turbo = experiment.rest_a_turbo
  const frequency = experiment.frecuencia
  const common = {
    id: 'hipotesis-h2',
    tag: 'H2',
    title: 'Frecuencia y Restaurantes → Turbo',
    goal: 'Meta: +10 % relativo sobre el control en Restaurantes → Turbo',
    question: `¿Piden más seguido y suman Turbo quienes piden Restaurantes?`,
  }
  if (mode === 'poblacion') {
    const population = experiment.poblacion
    return (
      <HypothesisCard
        {...common}
        status={verdict({ mode })}
        note="Toda la población de la fuente, sin grupos: describe, no mide el efecto de Mochi."
      >
        <div className="hypothesis-figures">
          <Figure
            value={formatNumber(population.frecuencia.pedidos_por_persona, 2)}
            unit={`pedidos por persona activa en ${population.frecuencia.dias} días`}
          />
          <Figure
            value={formatPct(population.rest_a_turbo.pct)}
            unit={`de ${formatNumber(population.rest_a_turbo.personas)} clientes de Restaurantes (${population.rest_a_turbo.dias} días) también pidió en Turbo`}
          />
        </div>
      </HypothesisCard>
    )
  }
  const diff30 = frequency.diferencia?.pedidos_30d
  const diffM1 = frequency.diferencia?.pedidos_m1
  const rest = turbo.diferencia
  const people = Object.fromEntries(turbo.variantes.map((row) => [row.variante, row.personas]))
  const m1 = VARIANTS.map((variant) => formatNumber(byVariant(frequency.variantes, variant).pedidos_m1, 2))
  const note = [
    `En M+1: ${m1[0]} contra ${m1[1]} pedidos por persona${diffM1 ? ` (${formatSigned(diffM1.valor)})` : ''}.`,
    `${pairOf(people)} clientes de Restaurantes con sus ${turbo.dias} días cumplidos` +
      (turbo.minimo ? `; para +10 % relativo harían falta ${pairOf(turbo.minimo)}, con la tasa del control.` : '.'),
  ].join(' ')
  return (
    <HypothesisCard
      {...common}
      status={verdict({ mode, source, conclusive: turbo.concluyente, ic95: rest?.ic95 })}
      note={note}
    >
      <GroupTable
        caption="Frecuencia y Restaurantes → Turbo por grupo"
        columns={[
          {
            header: `Pedidos por persona (${frequency.dias} días)`,
            value: (variant) => {
              const row = byVariant(frequency.variantes, variant)
              return valueWithN(formatNumber(row.pedidos_30d, 2), row.personas_30d, 'personas')
            },
            diff: (
              <>
                {formatSigned(diff30?.valor)}
                <Interval ic95={diff30?.ic95} source={source} decimals={2} />
              </>
            ),
          },
          {
            header: 'Restaurantes → Turbo',
            value: (variant) => {
              const row = byVariant(turbo.variantes, variant)
              return valueWithN(formatPct(row.pct), row.personas, 'clientes')
            },
            diff: (
              <>
                {formatPoints(rest?.puntos)}
                {rest?.relativa_pct !== null && rest?.relativa_pct !== undefined && (
                  <span className="cell-sub">{formatSigned(rest.relativa_pct, 1)} % relativo</span>
                )}
                <Interval ic95={rest?.ic95} source={source} />
              </>
            ),
          },
        ]}
      />
    </HypothesisCard>
  )
}

function H3({ experiment, mode, source }) {
  const survey = experiment.encuesta
  const common = {
    id: 'hipotesis-h3',
    tag: 'H3',
    title: '"¿Encontraste lo que buscabas?"',
    goal: 'Sin umbral: la diferencia con su intervalo',
    question: 'La pregunta de la app, igual con Mochi y sin él: ¿más personas responden "Sí"?',
  }
  if (mode === 'poblacion') {
    const population = experiment.poblacion.encuesta
    return (
      <HypothesisCard
        {...common}
        status={verdict({ mode })}
        note="Todas las respuestas de la fuente, sin grupos: describe, no mide el efecto de Mochi."
      >
        <Figure
          value={formatPct(population.si_pct)}
          unit={
            population.respondidas
              ? `respondió "Sí" (de ${formatNumber(population.respondidas)} respuestas)`
              : source === 'synthetic'
                ? 'Los datos simulados no traen la pregunta: se ve con el uso del MVP'
                : 'Nadie respondió todavía'
          }
        />
      </HypothesisCard>
    )
  }
  const difference = survey.diferencia
  const answers = Object.fromEntries(survey.variantes.map((row) => [row.variante, row.respondidas]))
  return (
    <HypothesisCard
      {...common}
      status={surveyVerdict({ mode, source, survey })}
      note={`${pairOf(answers)} respuestas; se lee desde ${formatNumber(survey.minimo)} por grupo, con la prueba a una cola.`}
    >
      <GroupTable
        caption='"Sí" a "¿Encontraste lo que buscabas?" por grupo'
        columns={[
          {
            header: 'Respondió "Sí"',
            value: (variant) => {
              const row = byVariant(survey.variantes, variant)
              return valueWithN(formatPct(row.si_pct), row.respondidas, 'respuestas')
            },
            diff: (
              <>
                {formatPoints(difference?.puntos)}
                <Interval ic95={difference?.ic95} source={source} />
              </>
            ),
          },
        ]}
      />
    </HypothesisCard>
  )
}

/** Sin la respuesta nueva (una foto grabada antes del 13-11), lo dice en vez de caerse. */
function MissingHypotheses() {
  return (
    <EmptyState title="Esta respuesta no trae las hipótesis" inline>
      Se ven con la API al día o con una foto grabada desde el 13-11 (npm run panel:snapshot).
    </EmptyState>
  )
}

/** Las tres hipótesis, en el orden del gerente. */
export function Hypotheses({ source }) {
  const experiment = offersExperiment(useAnalytics('experimentos', source))
  if (!hasHypotheses(experiment)) return <MissingHypotheses />
  const mode = hypothesesMode(experiment)
  return (
    <>
      {mode === 'poblacion' && (
        <Caveat>
          {experiment.control_pct === 0
            ? 'El grupo de control está apagado (OFFERS_CONTROL_PCT en 0): cada tarjeta describe a toda la población. Para medir, la API se levanta con OFFERS_CONTROL_PCT entre 1 y 50.'
            : 'Un grupo todavía no tiene personas: cada tarjeta describe a toda la población hasta que los dos las tengan.'}
        </Caveat>
      )}
      {mode === 'grupos' && source === 'synthetic' && (
        <Caveat>
          Datos simulados: el grupo de control y la diferencia entre los grupos salen de supuestos puestos a mano en el
          generador (rappi-ia/src/rappi_ia/events/synth.py), no de un efecto medido. Muestran cómo se lee cada
          hipótesis, sin veredicto ni intervalo.
        </Caveat>
      )}
      <div className="hypotheses" data-mode={mode}>
        <H1 experiment={experiment} mode={mode} source={source} />
        <H2 experiment={experiment} mode={mode} source={source} />
        <H3 experiment={experiment} mode={mode} source={source} />
      </div>
    </>
  )
}

const ADOPTION_COLUMNS = [
  { key: 'variante', header: 'Grupo', primary: true, render: (row) => <strong>{variantLabel(row.variante)}</strong> },
  { key: 'personas', header: 'Personas', numeric: true, render: (row) => formatNumber(row.personas) },
  ...[
    ['usaron', `Usaron a ${AGENT_NAME}`],
    ['ocultos', 'Lo tienen oculto'],
    ['silenciaron', 'Lo silenciaron por hoy'],
  ].map(([key, header]) => ({
    key,
    header,
    numeric: true,
    render: (row) => (
      <span className="cell-stack">
        {formatNumber(row[key])}
        {row.personas > 0 && <span className="cell-sub">{formatPct(row[`${key}_pct`])}</span>}
      </span>
    ),
  })),
]

/** Adopción y apagado: por grupo si los dos tienen personas; si no, la población activa de 30 días. */
export function Adoption({ source }) {
  const experiment = offersExperiment(useAnalytics('experimentos', source))
  if (!hasHypotheses(experiment)) return <MissingHypotheses />
  if (hypothesesMode(experiment) === 'grupos') {
    return (
      <DataTable
        caption="Adopción y apagado por grupo"
        columns={ADOPTION_COLUMNS}
        rows={experiment.adopcion.variantes}
        rowKey={(row) => row.variante}
      />
    )
  }
  const population = experiment.poblacion.adopcion
  const of = `de ${formatNumber(population.personas)} personas activas (${population.dias} días)`
  // El simulador no genera ocultar ni silenciar (como en "¿Mochi molesta?"): un 0 % diría algo que no midió.
  const simulated = source === 'synthetic'
  const notRecorded = 'los datos simulados no lo registran'
  return (
    <Stats
      items={[
        { label: `Usaron a ${AGENT_NAME}`, value: formatPct(population.usaron_pct), note: of },
        {
          label: 'Lo tienen oculto',
          value: formatPct(simulated ? null : population.ocultos_pct),
          note: simulated ? notRecorded : `${of}; su último cambio`,
        },
        {
          label: 'Lo silenciaron por hoy',
          value: formatPct(simulated ? null : population.silenciaron_pct),
          note: simulated ? notRecorded : of,
        },
      ]}
    />
  )
}
