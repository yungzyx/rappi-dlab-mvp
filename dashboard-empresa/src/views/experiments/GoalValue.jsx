import { useEffect, useState } from 'react'
import { Icon } from '../../components/Icon.jsx'
import { Panel } from '../../components/Panel.jsx'
import { EmptyState } from '../../components/States.jsx'
import { Stats } from '../../components/Stats.jsx'
import { formatNumber, formatPct } from '../../lib/format.js'
import { DEFAULTS, FIELDS, goalValue, HORIZON, parseAmount } from './goalValue.js'

// Solo en esta pestaña del navegador: para no perder lo escrito al cambiar de vista del panel. Nunca en la API.
const STORAGE_KEY = 'panel-empresa:valor-meta'

const GROUPS = [
  { legend: 'Tu negocio', keys: ['usuarios', 'retencion', 'pedidos', 'valor', 'margen'] },
  { legend: 'Restaurantes → Turbo', keys: ['restaurantes', 'turbo'] },
  { legend: 'Metas', keys: ['puntos', 'relativo', 'cobertura'] },
  { legend: 'Costos (opcional)', keys: ['inversion', 'operacion'] },
]

function loadTexts() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? 'null')
    if (!saved) return DEFAULTS
    return Object.fromEntries(
      Object.keys(DEFAULTS).map((key) => [key, typeof saved[key] === 'string' ? saved[key] : DEFAULTS[key]]),
    )
  } catch {
    return DEFAULTS // almacenamiento bloqueado o dañado: se parte de cero
  }
}

function saveTexts(texts) {
  try {
    const empty = Object.keys(DEFAULTS).every((key) => texts[key] === DEFAULTS[key])
    if (empty) sessionStorage.removeItem(STORAGE_KEY)
    else sessionStorage.setItem(STORAGE_KEY, JSON.stringify(texts))
  } catch {
    // Sin almacenamiento: lo escrito vive mientras la vista esté abierta.
  }
}

/** Montos y personas: sin decimales salvo los montos chicos ("2,5"). */
const amount = (value) => formatNumber(value, Math.abs(value) < 100 && !Number.isInteger(value) ? 1 : 0)

/** La meta escrita, para los títulos: "2", "2,5" o "—". */
function goalText(text) {
  const value = parseAmount(text)
  return formatNumber(value, Number.isInteger(value) ? 0 : 1)
}

const paybackText = (month) => (month === null ? `No se recupera en ${HORIZON} meses` : `Mes ${month}`)

/** Una entrada con su etiqueta visible, su unidad al lado y el error debajo (con ícono y texto). */
function Field({ name, value, error, onChange }) {
  const { label, unit, integer } = FIELDS[name]
  const id = `valor-meta-${name}`
  return (
    <div className="goal-field">
      <label htmlFor={id}>{label}</label>
      <div className="goal-input">
        <input
          id={id}
          type="text"
          inputMode={integer ? 'numeric' : 'decimal'}
          autoComplete="off"
          spellCheck={false}
          placeholder={integer ? 'ej. 10.000' : 'ej. 12,5'}
          value={value}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id}-unidad ${id}-error` : `${id}-unidad`}
          onChange={(event) => onChange(name, event.target.value)}
        />
        <span id={`${id}-unidad`} className="goal-unit">
          {unit}
        </span>
      </div>
      {error && (
        <p id={`${id}-error`} className="goal-error">
          <Icon name="warn" />
          <span>{error}</span>
        </p>
      )}
    </div>
  )
}

/** Lo que falta para una hipótesis, con los nombres de los campos. */
function Missing({ keys }) {
  return (
    <EmptyState title="Faltan supuestos:" inline>
      {keys.map((key) => FIELDS[key].label[0].toLowerCase() + FIELDS[key].label.slice(1)).join(', ')}.
    </EmptyState>
  )
}

/** La línea que se lee en 10 segundos: cuánto margen deja cada meta el primer año. */
function Summary({ h1, h2, goals }) {
  const parts = []
  if (!h1.missing) {
    parts.push(
      <span key="h1">
        +{goals.puntos} puntos de retención dejan entre <strong>{amount(h1.prudente.marginYear)}</strong> y{' '}
        <strong>{amount(h1.techo.marginYear)}</strong> de margen el primer año
      </span>,
    )
  }
  if (!h2.missing) {
    parts.push(
      <span key="h2">
        +{goals.relativo} % en Restaurantes → Turbo deja <strong>{amount(h2.marginYear)}</strong>
        {h1.missing && ' de margen el primer año'}
      </span>,
    )
  }
  return (
    <p className="goal-summary" aria-live="polite">
      {parts.length === 0 ? (
        'Escribe tus supuestos: aquí aparece cuánto margen deja cada meta el primer año.'
      ) : (
        <>
          Con tus supuestos, {parts[0]}
          {parts[1] && <>; {parts[1]}</>}.
        </>
      )}
    </p>
  )
}

function H1Help() {
  return (
    <>
      <p>
        Retenidos de más cada mes = usuarios activos × cobertura × puntos ÷ 100. Pedidos = retenidos × pedidos por
        usuario. Margen = pedidos × valor del pedido × margen %.
      </p>
      <p>
        Techo: cada mes se suman los retenidos de más y ninguno se va; en el mes k hay k × retenidos. Prudente: se suman
        y después se van a la tasa normal de fuga (1 − retención base, r); en el mes k hay retenidos × (1 − rᵏ) ÷ (1 −
        r). El primer año suma los meses 1 a 12.
      </p>
      <p>
        Recupera la inversión: el primer mes en que el margen acumulado, menos el costo mensual de cada mes, paga el
        costo de implementación. Se mira hasta {HORIZON} meses.
      </p>
    </>
  )
}

function H2Help() {
  return (
    <>
      <p>
        Clientes nuevos en Turbo = clientes de Restaurantes × cobertura × % que hoy compra en Turbo × % relativo de la
        meta. Margen al mes = clientes nuevos × 1 pedido × valor del pedido × margen %.
      </p>
      <p>
        Un pedido de Turbo al mes por cliente nuevo es lo mínimo que cuenta la H2 (pedir en Turbo en 28 días), con el
        valor y el margen de "Tu negocio". La meta sube una tasa, así que vale igual cada mes: el año son 12 meses.
      </p>
    </>
  )
}

function H1Result({ h1, goals, costs }) {
  if (h1.missing) return <Missing keys={h1.missing} />
  const readings = [
    { key: 'techo', label: 'Techo', note: 'nadie se va' },
    { key: 'prudente', label: 'Prudente', note: `se va el ${formatPct(h1.churn, 0)} al mes` },
  ]
  return (
    <>
      <Stats
        items={[
          { label: 'Retenidos de más', value: amount(h1.retained), note: `cada mes, de ${amount(h1.people)} usuarios` },
          { label: 'Pedidos de más', value: amount(h1.orders), note: 'el primer mes' },
          { label: 'Margen de más', value: amount(h1.margin), note: 'el primer mes' },
        ]}
      />
      <div className="goal-table">
        <table className="hypothesis-table">
          <caption className="visually-hidden">La H1 en sus dos lecturas, con +{goals.puntos} puntos</caption>
          <thead>
            <tr>
              <th scope="col">Lectura</th>
              <th scope="col">Retenidos de más en el mes 12</th>
              <th scope="col">Margen del primer año</th>
              {costs && <th scope="col">Recupera la inversión</th>}
            </tr>
          </thead>
          <tbody>
            {readings.map(({ key, label, note }) => (
              <tr key={key}>
                <th scope="row">
                  <span className="cell-stack">
                    {label}
                    <span className="cell-sub">{note}</span>
                  </span>
                </th>
                <td>{amount(h1[key].retainedAtYear)}</td>
                <td>{amount(h1[key].marginYear)}</td>
                {costs && <td>{paybackText(h1[key].payback)}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

function H2Result({ h2, costs }) {
  if (h2.missing) return <Missing keys={h2.missing} />
  return (
    <>
      <Stats
        items={[
          { label: 'Clientes nuevos en Turbo', value: amount(h2.clients), note: 'al mes' },
          { label: 'Margen de más', value: amount(h2.margin), note: 'al mes' },
          { label: 'Margen del primer año', value: amount(h2.marginYear), note: '12 meses iguales' },
        ]}
      />
      {costs && <p className="block-note">Recupera la inversión: {paybackText(h2.payback).toLowerCase()}.</p>}
    </>
  )
}

/**
 * "¿Cuánto vale la meta?": la calculadora que traduce la H1 y la H2 a margen con los supuestos de quien presenta. Todo
 * del navegador (también en el panel en un solo HTML); la lógica, en goalValue.js.
 */
export function GoalValue() {
  const [texts, setTexts] = useState(loadTexts)
  useEffect(() => saveTexts(texts), [texts])
  const change = (name, value) => setTexts((current) => ({ ...current, [name]: value }))
  const { errors, costs, h1, h2 } = goalValue(texts)
  const goals = { puntos: goalText(texts.puntos), relativo: goalText(texts.relativo) }

  return (
    <div className="goal">
      <Summary h1={h1} h2={h2} goals={goals} />
      <Panel
        title="Tus supuestos"
        meta="Usa la misma moneda en todos los montos. Quedan solo en esta pestaña del navegador."
        actions={
          <button type="button" className="text-button" onClick={() => setTexts(DEFAULTS)}>
            Borrar
          </button>
        }
      >
        <form className="goal-form" onSubmit={(event) => event.preventDefault()} noValidate>
          {GROUPS.map((group) => (
            <fieldset key={group.legend} className="goal-group">
              <legend>{group.legend}</legend>
              {group.keys.map((key) => (
                <Field key={key} name={key} value={texts[key]} error={errors[key]} onChange={change} />
              ))}
            </fieldset>
          ))}
        </form>
      </Panel>

      <div className="goal-results">
        <Panel title={`H1 · +${goals.puntos} puntos de retención`} help={<H1Help />}>
          <H1Result h1={h1} goals={goals} costs={costs} />
        </Panel>
        <Panel title={`H2 · +${goals.relativo} % relativo en Restaurantes → Turbo`} help={<H2Help />}>
          <H2Result h2={h2} costs={costs} />
        </Panel>
        <p className="block-note">
          Cada meta va por separado y no se suman: los mismos clientes pueden estar en las dos. El costo, si lo
          escribes, se carga entero a cada una.
        </p>
      </div>
    </div>
  )
}
