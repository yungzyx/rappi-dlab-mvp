import { AGENT_NAME } from '../../lib/agentName.js'
import { DataTable } from '../../components/DataTable.jsx'
import { Meter } from '../../components/Meter.jsx'
import { EmptyState } from '../../components/States.jsx'
import { formatNumber, formatPct } from '../../lib/format.js'
import { MIN_SHOWN_FOR_RATE, OPENABLE_MOMENTS, REJECTABLE_MOMENTS, momentHint, momentLabel } from './offers.js'

/**
 * Ofertas de Mochi por momento (dónde se hizo la oferta). La tasa llega vacía (—) con menos mostradas que el mínimo:
 * ahí solo valen las cuentas. Después de la tasa, las rechazadas ("Ahora no" o "Después", solo donde hay ese botón),
 * las abiertas (la vertical abierta desde la oferta, solo donde hay un botón que la abre: no es una aceptación) y los
 * "¿Por qué?" abiertos; una respuesta guardada antes de que la API los contara no los trae y muestra "—".
 * `make mvp-check` lee esta tabla: "Plan" y sus aceptadas en la tercera celda. Debajo, aparte, los pedidos que Mochi hizo solo con permiso ("Pedir por
 * mí"): no son ofertas aceptadas.
 */
export function OffersByMoment({ data, source }) {
  const { momentos } = data
  if (!momentos.length) {
    return (
      <EmptyState title={`${AGENT_NAME} todavía no hizo ofertas`}>
        Aparecen cuando una oferta se muestra en la app.
      </EmptyState>
    )
  }
  // El simulador no guarda en qué momento se hizo cada oferta: todo cae en "sin momento".
  if (source === 'synthetic' && momentos.every((row) => row.momento === 'sin_momento')) {
    return (
      <EmptyState title="Los datos simulados no registran el momento de la oferta">
        Solo el prototipo guarda dónde se hizo cada oferta; las sugerencias entre verticales, abajo, sí tienen datos.
      </EmptyState>
    )
  }
  const columns = [
    {
      key: 'momento',
      header: 'Momento',
      primary: true,
      render: (row) => (
        // El espacio separa el momento de su descripción en el nombre de la fila ("Plan Un kit…"): `make mvp-check`
        // busca la fila que empieza con "Plan ".
        <span className="cell-stack">
          <strong>{momentLabel(row.momento)}</strong>{' '}
          {momentHint(row.momento) && <span className="cell-sub">{momentHint(row.momento)}</span>}
        </span>
      ),
    },
    { key: 'mostradas', header: 'Mostradas', numeric: true, render: (row) => formatNumber(row.mostradas) },
    { key: 'aceptadas', header: 'Aceptadas', numeric: true, render: (row) => formatNumber(row.aceptadas) },
    {
      key: 'aceptacion_pct',
      header: 'Tasa de aceptación',
      numeric: true,
      render: (row) => (
        <span className="cell-bar">
          {row.aceptacion_pct === null ? <span /> : <Meter value={row.aceptacion_pct} max={100} />}
          {formatPct(row.aceptacion_pct)}
        </span>
      ),
    },
    {
      key: 'rechazadas',
      header: 'Rechazadas',
      numeric: true,
      // Sin botón para rechazar, "—" en vez de 0; "sin momento" muestra lo que haya (los simulados no guardan el momento).
      render: (row) => (REJECTABLE_MOMENTS.has(row.momento) || row.rechazadas > 0 ? formatNumber(row.rechazadas) : '—'),
    },
    {
      key: 'abiertas',
      header: 'Abiertas',
      numeric: true,
      // Abrir la vertical de la oferta no es aceptarla; sin un botón que la abra, "—", como las rechazadas.
      render: (row) => (OPENABLE_MOMENTS.has(row.momento) || row.abiertas > 0 ? formatNumber(row.abiertas) : '—'),
    },
    {
      key: 'por_que_abiertos',
      header: '"¿Por qué?" abiertos',
      numeric: true,
      render: (row) => formatNumber(row.por_que_abiertos),
    },
  ]
  return (
    <>
      <DataTable
        caption="Ofertas del agente por momento"
        columns={columns}
        rows={momentos}
        rowKey={(row) => row.momento}
      />
      <p className="cell-sub">
        La tasa aparece desde {MIN_SHOWN_FOR_RATE} mostradas; antes, solo las cuentas. Rechazada es tocar "Ahora no"
        (Carro) o "Después" (Vertical por probar, Recompra y Volver a pedir); los otros momentos no tienen ese botón y
        muestran "—". Una oferta que no se toca no es un rechazo: no se cuenta. Abierta es tocar el botón que abre su
        vertical ("Ver …", "Abrir …"): dice que la persona fue a mirar, no que la aceptó.
      </p>
      <AutoOrders counts={data.autopedidos} />
    </>
  )
}

/** Los pedidos que Mochi hizo solo, con el permiso de la persona ("Pedir por mí"), contados aparte de las ofertas. */
function AutoOrders({ counts }) {
  if (!counts) return null
  return (
    <p className="cell-sub" data-testid="autopedidos">
      Pedidos que {AGENT_NAME} hizo solo, con permiso ("Pedir por mí"): {formatNumber(counts.pedidos)}
      {counts.pedidos > 0 && ` de ${formatNumber(counts.personas)} ${counts.personas === 1 ? 'persona' : 'personas'}`}.
      No cuentan como ofertas aceptadas.
    </p>
  )
}
