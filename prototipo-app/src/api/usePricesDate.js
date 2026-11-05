// De qué fecha son los precios que muestra la app: el `catalogo` de /catalog/home (rappi-ia, catalog/dates.py), dicho
// como "al 18-10" o "del 24-09 al 18-10".
import { catalogDates } from './catalog'
import { useApi } from './useApi'

const dayMonth = (day) => `${day.slice(8, 10)}-${day.slice(5, 7)}` // '2026-10-18' → '18-10'

/** `{ from, to }` ('AAAA-MM-DD') → "al 18-10" si es un solo día, o "del 24-09 al 18-10"; sin fechas, null. */
export function pricesDate(range) {
  if (!range) return null
  if (range.from === range.to) return `al ${dayMonth(range.to)}`
  return `del ${dayMonth(range.from)} al ${dayMonth(range.to)}`
}

/**
 * Las fechas de esas verticales (ids de pantalla) juntas, del precio más antiguo al más nuevo. Si el catálogo no conoce
 * ninguna (o no se pide ninguna), las de todo el catálogo.
 */
export function rangeOf(dates, verticals = []) {
  if (!dates) return null
  const known = verticals.map((vertical) => dates.byVertical[vertical]).filter(Boolean)
  if (known.length === 0) return dates
  const days = (end) => known.map((range) => range[end]).sort() // 'AAAA-MM-DD' se ordena como texto
  return { from: days('from')[0], to: days('to').at(-1) }
}

/**
 * "al 18-10": de cuándo son los precios de una vertical o de varias (id de pantalla o lista de ids) o, sin ellas, de
 * todo el catálogo. Null mientras no se sabe o si la API no lo dice: quien lo muestra lo omite.
 */
export function usePricesDate(verticals) {
  const { data } = useApi(catalogDates, [])
  return pricesDate(rangeOf(data, [verticals].flat().filter(Boolean)))
}
