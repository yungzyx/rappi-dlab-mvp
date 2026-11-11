import { Async } from '../../components/Async.jsx'
import { Caveat } from '../../components/Caveat.jsx'
import { ChartPanel } from '../../components/ChartTableSwitch.jsx'
import { DataTable } from '../../components/DataTable.jsx'
import { SectionHead } from '../../components/SectionHead.jsx'
import { Stats } from '../../components/Stats.jsx'
import { BarRows } from '../../components/charts/BarRows.jsx'
import { formatNumber, formatPct } from '../../lib/format.js'
import { useAnalytics } from '../../lib/useAnalytics.js'
import { Churn } from './Churn.jsx'
import { ProSplit } from './ProSplit.jsx'
import { RetentionLadder, startLabel } from './RetentionLadder.jsx'
import './customers.css'

// La tabla de Rappi no depende de la fuente: se lee con la simulada, que tiene respaldo sin conexión.
const useRappi = () => useAnalytics('combos', 'synthetic').rappi

/** La nota que acompaña a la tabla de Rappi (de dónde sale), dentro de la ayuda de la sección. */
function RappiNote() {
  return <p>{useRappi().nota}</p>
}

/** Las cifras de toda la tabla de Rappi: usuarios, cuántos vuelven al mes siguiente y pedidos por usuario. */
function RappiTotals() {
  const { total } = useRappi()
  return (
    <Stats
      items={[
        { label: 'Usuarios en la tabla', value: formatNumber(total.usuarios), note: 'todo Chile' },
        {
          label: 'Vuelven al mes siguiente',
          value: formatPct(total.retencion_m1 === null ? null : total.retencion_m1 * 100, 0),
          note: 'todo Chile',
        },
        { label: 'Pedidos por usuario', value: formatNumber(total.pedidos_por_usuario, 1), note: 'todo Chile' },
      ]}
    />
  )
}

function Ladder() {
  return <RetentionLadder rappi={useRappi()} />
}

const COMBO_SERIES = [
  { key: 'usuarios', label: '% de los usuarios' },
  { key: 'pedidos', label: '% de los pedidos' },
]

const COMBO_COLUMNS = [
  { key: 'combo', header: 'Combinación', primary: true, render: (row) => startLabel(row.combo) },
  { key: 'pct_usuarios', header: '% usuarios', numeric: true, render: (row) => formatPct(row.pct_usuarios) },
  { key: 'pct_pedidos', header: '% pedidos', numeric: true, render: (row) => formatPct(row.pct_pedidos) },
  {
    key: 'pedidos',
    header: 'Pedidos por usuario',
    numeric: true,
    render: (row) => formatNumber(row.pedidos_por_usuario, 1),
  },
]

/** Cuántos usuarios y cuántos pedidos hay en cada combinación de la tabla de Rappi, de más a menos usuarios. */
function UsersAndOrders() {
  const rows = [...useRappi().filas].sort((a, b) => b.pct_usuarios - a.pct_usuarios)
  const name = 'Usuarios y pedidos por combinación'
  return (
    <ChartPanel
      title={name}
      chart={
        <BarRows
          series={COMBO_SERIES}
          max={Math.max(...rows.flatMap((row) => [row.pct_usuarios, row.pct_pedidos]))}
          rows={rows.map((row) => ({
            key: row.combo,
            label: startLabel(row.combo),
            values: [row.pct_usuarios, row.pct_pedidos],
            texts: [formatPct(row.pct_usuarios), formatPct(row.pct_pedidos)],
            note: `${formatNumber(row.pedidos_por_usuario, 1)} por usuario`,
          }))}
        />
      }
      table={<DataTable caption={name} columns={COMBO_COLUMNS} rows={rows} rowKey={(row) => row.combo} />}
    />
  )
}

/**
 * Gerencia: dónde está la venta cruzada (la tabla de Rappi), Pro frente a sin Pro y a quién estamos perdiendo (la fuente
 * elegida). Con `tab` (la subpestaña), solo esa sección; sin `tab`, las tres.
 */
export function CustomersView({ source, tab }) {
  const show = (id) => !tab || tab === id
  return (
    <div className="view">
      {show('venta-cruzada') && (
        <section className="section" aria-labelledby="venta-cruzada">
          <SectionHead
            id="venta-cruzada"
            title="Dónde está la venta cruzada"
            source="rappi"
            help={
              <>
                <p>
                  La tabla que compartió Rappi dice, para cada combinación de grupos de verticales, cuántos usuarios
                  vuelven al mes siguiente y cuánto piden. Cada fila compara una combinación con la que suma un grupo
                  más y retiene más; arriba, donde hay más usuarios. Retail agrupa todo el comercio que no es
                  restaurante ni Turbo. Favor no tiene una combinación con un grupo más en la tabla.
                </p>
                <Async fallback={null} errorFallback={null}>
                  <RappiNote />
                </Async>
              </>
            }
          />
          <Async>
            <RappiTotals />
          </Async>
          <Async>
            <Ladder />
          </Async>
          <Async>
            <UsersAndOrders />
          </Async>
        </section>
      )}

      {show('pro') && (
        <section className="section" aria-labelledby="pro">
          <SectionHead id="pro" title="Pro y sin Pro" source={source}>
            <Caveat>Es una comparación, no un efecto: quien ya pide más se hace Pro.</Caveat>
            {source === 'synthetic' && (
              <Caveat>
                En los simulados, quién es Pro lo sortea el generador según cuántas verticales combina: la diferencia no
                es evidencia.
              </Caveat>
            )}
          </SectionHead>
          <Async>
            <ProSplit source={source} />
          </Async>
        </section>
      )}

      {show('perdiendo') && (
        <section className="section" aria-labelledby="perdiendo">
          <SectionHead
            id="perdiendo"
            title="A quién estamos perdiendo"
            source={source}
            help={
              <p>
                Cada persona tiene su propio ritmo de compra y el riesgo se mide contra ese ritmo: en riesgo es pasar el
                doble sin pedir (mínimo 21 días) y perdida, el triple (mínimo 45 días). "¿Volvemos a…?" usa otra regla:
                algo que la persona pedía con ritmo y dejó. El concepto que se muestra nunca es sensible, y fuera de la
                app solo se escribe a quien aceptó avisos.
              </p>
            }
          />
          <Async>
            <Churn source={source} />
          </Async>
        </section>
      )}
    </div>
  )
}
