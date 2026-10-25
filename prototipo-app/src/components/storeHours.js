// Abierto o cerrado de una tienda o un restaurante (`store.hours` de la API): lo que Rappi publicó el día de la
// descarga, nunca el estado en vivo. Un restaurante trae su horario (`source: 'horario'`), que la API compara con la
// hora local; una tienda, cómo estaba al bajarla (`source: 'descarga'`).

/** La aclaración que acompaña al estado, según de dónde sale. */
export const HOURS_SOURCE_NOTE = {
  horario: 'Según el horario publicado en Rappi el día de la descarga, no el estado en vivo.',
  descarga: 'Según lo que Rappi publicó el día de la descarga, no el estado en vivo.',
}

export const isClosed = (hours) => hours?.open === false

/** «Cerrado · Abre a las 11:00», «Abierto hasta las 23:00»… o null si no hay nada que decir (no se sabe). */
export function hoursLabel(hours) {
  if (!hours || hours.open == null) return null
  if (hours.open) return hours.closes_at ? `Abierto hasta las ${hours.closes_at}` : null
  if (hours.opens_at) return `Cerrado · Abre ${hours.opens_tomorrow ? 'mañana ' : ''}a las ${hours.opens_at}`
  return hours.source === 'horario' ? 'Cerrado hoy' : 'Cerrada'
}

/** La promo que se muestra en la tarjeta: la primera que publicó la tienda o, en un restaurante, «Con promociones». */
export function promoLabel(store) {
  if (store?.promos?.length) return store.promos[0].title
  return store?.promo ? 'Con promociones' : null
}
