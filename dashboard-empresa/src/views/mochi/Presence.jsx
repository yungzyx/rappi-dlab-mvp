import { AGENT_NAME } from '../../lib/agentName.js'
import { EmptyState } from '../../components/States.jsx'
import { Stats } from '../../components/Stats.jsx'
import { formatNumber, formatPct } from '../../lib/format.js'

const people = (n) => `${formatNumber(n)} ${n === 1 ? 'persona' : 'personas'}`
const times = (n) => `${formatNumber(n)} ${n === 1 ? 'vez' : 'veces'}`

/**
 * Si Mochi molesta (`/analytics/presencia`, últimos 30 días): quiénes lo tienen oculto y qué % de las personas activas
 * son, quiénes lo silenciaron por hoy (y su %), quiénes lo trajeron de vuelta y cuántas veces explicó por qué movió los
 * accesos de la Home. Sin ningún evento de estos, un estado vacío: el simulador no los genera.
 */
export function Presence({ data, source }) {
  const nothing = !data.ocultadas && !data.ocultos && !data.volvieron && !data.silenciadas && !data.explicaciones
  if (nothing) {
    return source === 'synthetic' ? (
      <EmptyState title={`Los datos simulados no registran ocultar ni silenciar a ${AGENT_NAME}`} inline>
        Tampoco sus explicaciones de la Home: se ven con el uso del MVP.
      </EmptyState>
    ) : (
      <EmptyState title={`Nadie ocultó ni silenció a ${AGENT_NAME}, ni lo vio mover la Home`} inline>
        Aparece cuando alguien lo oculta (en su menú o en Cuenta), lo silencia por hoy (en su menú) o cuando{' '}
        {AGENT_NAME} explica por qué movió los accesos de la Home.
      </EmptyState>
    )
  }
  return (
    <Stats
      items={[
        {
          label: `Ocultaron a ${AGENT_NAME}`,
          value: formatNumber(data.ocultos),
          note:
            data.ocultos_pct === null
              ? 'lo tienen oculto ahora'
              : `${formatPct(data.ocultos_pct)} de ${people(data.personas_activas)} activas; lo ocultaron ${times(data.ocultadas)}`,
        },
        {
          label: 'Lo silenciaron por hoy',
          value: formatNumber(data.silenciaron),
          note:
            data.silenciaron_pct === null
              ? 'sigue a la vista, pero no habla solo ese día'
              : `${formatPct(data.silenciaron_pct)} de ${people(data.personas_activas)} activas; lo silenciaron ${times(data.silenciadas)}`,
        },
        {
          label: 'Lo volvieron a mostrar',
          value: formatNumber(data.volvieron),
          note: data.volvieron === 1 ? 'persona, desde Cuenta' : 'personas, desde Cuenta',
        },
        {
          label: `${AGENT_NAME} explicó el orden de la Home`,
          value: times(data.explicaciones),
          note: `a ${people(data.explicaciones_personas)}; la app no anota "¿Por qué?" ni "Entendido"`,
        },
      ]}
    />
  )
}
