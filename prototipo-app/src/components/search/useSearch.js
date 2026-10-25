import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchApi } from '../../api/useSearchApi'
import { useEvents } from '../../state/EventsContext'

/**
 * Búsqueda en vivo en el catálogo de la API (todas las verticales, agrupada). La comparten el buscador de «Rappi hoy»
 * y el del agente (prototipo final). `vertical`: la de la pantalla desde la que se abrió (la API la suma a las que busca
 * y el embudo del panel se mide por vertical).
 * Devuelve `{ query, setQuery, data, loading, error, retry, hasQuery, logSearch, pick, searchExact }`; `data`,
 * `loading` y `error` son los de `useSearchApi`. Si la API corrigió un error de tipeo (`data.correctedQuery`),
 * `searchExact(term)` vuelve a buscar `term` tal cual, hasta que llegue la respuesta de otro texto; esa búsqueda
 * también se registra.
 */
export function useSearch({ initial = '', vertical } = {}) {
  const [query, setQuery] = useState(initial)
  const [exactText, setExactText] = useState(null)
  const text = query.trim()
  const hasQuery = text.length > 0
  const { data, loading, error, retry } = useSearchApi(query, { current: vertical, exactQuery: exactText })
  const events = useEvents()
  const logged = useRef(null)
  const wanted = useRef(null) // lo que la persona terminó de buscar y aún espera su respuesta

  // Para el panel, solo búsquedas terminadas (Enter, salir del campo o una sugerencia), no palabras a medio
  // escribir, y con lo que la API respondió: cuántos productos y si no hubo nada (`unmet`).
  const record = useCallback(
    (term, found) => {
      logged.current = term
      wanted.current = null
      events.track('search', {
        query: term,
        modality: 'texto',
        results: found.groups.reduce((sum, group) => sum + group.products.length, 0),
        unmet: found.unmet,
        vertical,
        // Lo que buscó la API si corrigió un error de tipeo: el panel separa esas búsquedas de las que calzaron.
        ...(found.correctedQuery && { payload: { corregida: found.correctedQuery } }),
      })
    },
    [events, vertical],
  )

  // La respuesta de `text` está lista cuando ya no carga y trae datos (con error o con menos de 2 letras no hay).
  const ready = data !== null && !loading
  useEffect(() => {
    if (ready && wanted.current === text) record(text, data)
  }, [ready, data, text, record])

  // «Tal cual» vale para ese texto: cuando llega la respuesta de otro, la API vuelve a poder corregir (se ajusta al
  // renderizar, como un valor derivado: sin un render de más).
  if (ready && exactText !== null && data.query !== exactText) setExactText(null)

  const logSearch = (term) => {
    const clean = term.trim()
    if (!clean || clean === logged.current) return
    // Si la respuesta de lo buscado aún no llega, se registra al llegar.
    if (ready && clean === text) record(clean, data)
    else wanted.current = clean
  }

  /** Una búsqueda reciente: se escribe en el campo y se registra al llegar su respuesta. */
  const pick = (term) => {
    setQuery(term)
    logSearch(term)
  }

  const searchExact = (term) => {
    setExactText(term)
    logged.current = null
    wanted.current = term
  }

  return { query, setQuery, data, loading, error, retry, hasQuery, logSearch, pick, searchExact }
}
