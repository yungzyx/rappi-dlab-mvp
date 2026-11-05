import { usePricesDate } from '../api/usePricesDate'

/**
 * " (catálogo al 18-10)": de qué fecha son los precios de esas verticales (id de pantalla o lista; sin ellas, todo el
 * catálogo), para cerrar una nota sobre lo descargado. Pide la fecha recién cuando la nota se ve; mientras no se sabe, o
 * si la API no la da, no agrega nada.
 */
export default function PricesDate({ verticals, label = 'catálogo' }) {
  const prices = usePricesDate(verticals)
  return prices ? ` (${label} ${prices})` : null
}
