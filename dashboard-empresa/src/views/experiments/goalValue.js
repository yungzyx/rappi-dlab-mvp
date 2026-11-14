// "¿Cuánto vale la meta?": traduce las metas de la H1 y la H2 a margen, con los supuestos que escribe quien presenta.
// Nada sale de la API ni viaja por la red: los valores son texto del formulario y, a lo más, quedan en sessionStorage de
// la pestaña. Ninguna cifra de Rappi vive aquí, ni como valor por defecto: los campos parten vacíos.
//
// El método del gerente: margen incremental = pedidos incrementales × valor del pedido × margen por pedido, mes a mes.
// H1 (+Δ puntos de retención): el primer mes se retienen de más E = usuarios × cobertura × Δ. Dos lecturas:
//   techo:    +Δ % de usuarios cada mes, compuesto, y nadie se va (el modelo del gerente)
//             X_k = (1 + Δ) × X_(k−1) + E      (X_k = usuarios × cobertura × ((1 + Δ)^k − 1))
//   prudente: cada mes E de más, que después se van a la tasa normal de fuga (1 − r)
//             X_k = r × X_(k−1) + E            (X_k = E × (1 − r^k) / (1 − r))
// y el margen del mes k es X_k × pedidos por usuario × valor × margen.
// H2 (+L % relativo en Restaurantes → Turbo): clientes nuevos en Turbo = clientes de Restaurantes × cobertura × t × L,
// cada uno con un pedido de Turbo al mes (lo mínimo que cuenta la H2), con el mismo valor y margen; igual cada mes.
// Recupera la inversión: el primer mes k en que la suma de (margen − costo mensual) de los meses 1 a k paga la inversión.

export const HORIZON = 36
export const YEAR = 12

/** Los campos del formulario: clave, etiqueta, unidad, tipo y lo que pide (`pct`: entre 0 y 100). */
export const FIELDS = {
  usuarios: { label: 'Usuarios activos al mes', unit: 'usuarios', integer: true },
  retencion: { label: 'Retención base', unit: '%', pct: true },
  pedidos: { label: 'Pedidos por usuario activo al mes', unit: 'pedidos' },
  valor: { label: 'Valor promedio del pedido', unit: 'en tu moneda' },
  margen: { label: 'Margen por pedido', unit: '% del valor', pct: true },
  restaurantes: { label: 'Clientes de Restaurantes al mes', unit: 'clientes', integer: true },
  turbo: { label: 'De ellos, compran hoy en Turbo', unit: '%', pct: true },
  puntos: { label: 'Meta H1: retención', unit: 'puntos', pct: true },
  relativo: { label: 'Meta H2: Restaurantes → Turbo', unit: '% relativo' },
  cobertura: { label: 'Cobertura: a quiénes llega', unit: '% de los usuarios', pct: true },
  inversion: { label: 'Costo de implementación (una vez)', unit: 'en tu moneda' },
  operacion: { label: 'Costo de operar, al mes', unit: 'en tu moneda' },
}

/** Lo que trae el formulario al abrir o al tocar "Borrar": todo vacío salvo las metas del piloto y la cobertura. */
export const DEFAULTS = Object.freeze({
  usuarios: '',
  retencion: '',
  pedidos: '',
  valor: '',
  margen: '',
  restaurantes: '',
  turbo: '',
  puntos: '2',
  relativo: '10',
  cobertura: '100',
  inversion: '',
  operacion: '',
})

const H1_FIELDS = ['usuarios', 'retencion', 'pedidos', 'valor', 'margen', 'puntos']
const H2_FIELDS = ['restaurantes', 'turbo', 'valor', 'margen', 'relativo']

/**
 * Un número escrito en es-CL: "10.000" → 10000, "2,5" → 2.5, "1.234,5" → 1234.5. Sin coma, un punto seguido de tres
 * cifras es de miles ("1.250" → 1250) y uno con otra cantidad, decimal ("2.5" → 2.5). Vacío → null; lo que no es un
 * número → NaN.
 */
export function parseAmount(text) {
  const raw = String(text ?? '')
    .replace(/\s/g, '') // también el espacio duro que pega una planilla
    .replace(/^−/, '-')
  if (raw === '') return null
  let normal
  if (raw.includes(',')) normal = raw.replace(/\./g, '').replace(',', '.')
  else if (/^-?\d{1,3}(\.\d{3})+$/.test(raw)) normal = raw.replace(/\./g, '')
  else normal = raw
  return /^-?(\d+\.?\d*|\.\d+)$/.test(normal) ? Number(normal) : Number.NaN
}

/** El error de un campo, o null. `values`: los números ya leídos (para cruzar retención + meta y Turbo × meta). */
function fieldError(key, value, values) {
  if (value === null) return null
  if (Number.isNaN(value)) return 'No es un número: usa coma para los decimales'
  if (value < 0) return 'No puede ser negativo'
  if (FIELDS[key].pct && value > 100) return 'No puede pasar de 100'
  if (key === 'puntos' && values.retencion !== null && values.retencion + value > 100) {
    return 'Con la retención base pasa de 100 %'
  }
  if (key === 'relativo' && values.turbo !== null && values.turbo * (1 + value / 100) > 100) {
    return 'Con el % que hoy compra en Turbo pasa de 100 %'
  }
  return null
}

/**
 * Los meses 1…HORIZON de retenidos de más, en una lectura: `perMonth` nuevos cada mes; `keep`, cuánto queda al mes
 * siguiente de lo que había (r en la prudente; 1 + Δ en el techo, que compone).
 */
export function extraActive(perMonth, keep) {
  const series = []
  let stock = 0
  for (let month = 1; month <= HORIZON; month += 1) {
    stock = stock * keep + perMonth
    series.push(stock)
  }
  return series
}

/** El primer mes (1…HORIZON) en que el margen acumulado menos los costos llega a 0, o null si no se recupera. */
export function paybackMonth(margins, investment, monthlyCost) {
  let balance = -investment
  for (let index = 0; index < margins.length; index += 1) {
    balance += margins[index] - monthlyCost
    if (balance >= 0) return index + 1
  }
  return null
}

const sum = (values) => values.reduce((total, value) => total + value, 0)

/** Lo que falta para una hipótesis: las claves de sus campos vacíos o con error. */
const gaps = (keys, values, errors) => keys.filter((key) => values[key] === null || errors[key])

/**
 * Todo lo que muestra la calculadora a partir del texto del formulario (`texts`, con las claves de FIELDS):
 * - `errors`: { campo: mensaje } de lo escrito que no sirve;
 * - `costs`: si se escribió algún costo (sin costos no hay "recupera la inversión");
 * - `h1` y `h2`: `{ missing: [campos] }` si falta algo, o sus cifras al mes, del primer año y el mes en que se recupera
 *   la inversión (null: no se recupera en HORIZON meses). La H1 trae `techo` y `prudente`.
 */
export function goalValue(texts) {
  const values = Object.fromEntries(Object.keys(FIELDS).map((key) => [key, parseAmount(texts[key])]))
  const errors = {}
  for (const key of Object.keys(FIELDS)) {
    const error = fieldError(key, values[key], values)
    if (error) errors[key] = error
  }
  const ok = (key) => (errors[key] ? null : values[key])
  const coverage = (ok('cobertura') ?? 100) / 100
  const investment = ok('inversion') ?? 0
  const monthlyCost = ok('operacion') ?? 0
  const costs = investment > 0 || monthlyCost > 0
  const marginPerOrder = (ok('valor') ?? 0) * ((ok('margen') ?? 0) / 100)
  const payback = (margins) => (costs ? paybackMonth(margins, investment, monthlyCost) : null)

  let h1
  const missing1 = gaps(H1_FIELDS, values, errors)
  if (missing1.length || errors.cobertura) {
    h1 = { missing: errors.cobertura ? [...missing1, 'cobertura'] : missing1 }
  } else {
    const retained = values.usuarios * coverage * (values.puntos / 100)
    const reading = (keep) => {
      const extra = extraActive(retained, keep)
      const margins = extra.map((people) => people * values.pedidos * marginPerOrder)
      return {
        retainedAtYear: extra[YEAR - 1],
        marginYear: sum(margins.slice(0, YEAR)),
        payback: payback(margins),
      }
    }
    h1 = {
      people: values.usuarios * coverage,
      churn: 100 - values.retencion,
      retained,
      orders: retained * values.pedidos,
      margin: retained * values.pedidos * marginPerOrder,
      techo: reading(1 + values.puntos / 100),
      prudente: reading(values.retencion / 100),
    }
  }

  let h2
  const missing2 = gaps(H2_FIELDS, values, errors)
  if (missing2.length || errors.cobertura) {
    h2 = { missing: errors.cobertura ? [...missing2, 'cobertura'] : missing2 }
  } else {
    const clients = values.restaurantes * coverage * (values.turbo / 100) * (values.relativo / 100)
    const margin = clients * marginPerOrder
    h2 = {
      clients,
      margin,
      marginYear: margin * YEAR,
      payback: payback(Array(HORIZON).fill(margin)),
    }
  }

  return { errors, costs, h1, h2 }
}
