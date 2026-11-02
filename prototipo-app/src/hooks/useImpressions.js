import { useEffect } from 'react'
import { impressionRef, setImpressionSink } from '../api/impressions'
import { useEvents } from '../state/EventsContext'

/**
 * Impresiones de una lista (api/impressions.js): devuelve `watch(item, fields)`, el ref para el nodo de cada elemento
 * (el mismo para el mismo elemento en el mismo lugar, render tras render).
 * Cuenta el elemento cuando queda visible al menos la mitad, una vez por pestaña, lista y lugar, y lo manda con los demás
 * de su lista en un `list_view`. Sin lugar (`item.placement`) no cuenta nada.
 */
export function useImpressions() {
  const { track } = useEvents()
  useEffect(() => {
    setImpressionSink(track)
  }, [track])
  return impressionRef
}
