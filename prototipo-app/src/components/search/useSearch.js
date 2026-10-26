import { useCallback, useEffect, useRef, useState } from 'react'
import { envelope } from '../../api/attribution'
import { useSearchApi } from '../../api/useSearchApi'
import { userId } from '../../api/user'
import { useDemo } from '../../state/DemoContext'
import { useEvents } from '../../state/EventsContext'

// De dónde salió el texto buscado (`payload.fuente`): escrito, una sugerencia (una idea, una búsqueda reciente
// —`reciente`— o «Lo más buscado» —`lo-mas-buscado`—) o el aviso de la corrección («buscar tal cual»). Equivale a
// SEARCH_SOURCE de la app de Rappi.
const TYPED = 'tipeada'
const SUGGESTED = 'sugerencia'
const CORRECTION = 'correccion'

/**
 * Búsqueda en vivo en el catálogo de la API (todas las verticales, agrupada). La comparten el buscador de «Rappi hoy»
 * y el del agente (prototipo final). `vertical`: la de la pantalla desde la que se abrió (la API la suma a las que busca
 * y el embudo del panel se mide por vertical). Con `only`, busca solo en esa vertical («Ver todos en…» de un grupo).
 * Devuelve `{ query, setQuery, data, loading, error, retry, hasQuery, logSearch, pick, searchExact }`; `data`,
 * `loading` y `error` son los de `useSearchApi`. Si la API corrigió un error de tipeo (`data.correctedQuery`),
 * `searchExact(term)` vuelve a buscar `term` tal cual, hasta que llegue la respuesta de otro texto; esa búsqueda
 * también se registra. En el prototipo final la búsqueda va con la persona: su dieta y sus alergias (las que le dijo
 * a Mochi) filtran los resultados; en «Rappi hoy», no.
 */
export function useSearch({ initial = '', vertical, only = false } = {}) {
  const [query, setQuery] = useState(initial)
  const [exactText, setExactText] = useState(null)
  const text = query.trim()
  const hasQuery = text.length > 0
  const person = useDemo()?.isFinal ? userId() : undefined
  const scope =
    only && vertical ? { vertical, userId: person } : { current: vertical, exactQuery: exactText, userId: person }
  const { data, loading, error, retry } = useSearchApi(query, scope)
  const events = useEvents()
  const logged = useRef(null)
  const wanted = useRef(null) // lo que la persona terminó de buscar y aún espera su respuesta
  const source = useRef(TYPED) // de dónde salió lo que se busca (`fuente`)

  // Para el panel, solo búsquedas terminadas (Enter, salir del campo o una sugerencia), no palabras a medio
  // escribir, y con lo que la API respondió: cuántos productos y si no hubo nada (`unmet`). El `request_id` de la
  // respuesta es el id de la búsqueda (search_id): los productos de los resultados lo llevan a sus eventos, con su
  // posición. `alcance` es global (todas las verticales, agrupada) o vertical.
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
        ...envelope({ surface: 'search', requestId: found.requestId }),
        payload: {
          alcance: found.scope ?? 'global',
          fuente: source.current,
          // Lo que buscó la API si corrigió un error de tipeo: el panel separa esas búsquedas de las que calzaron.
          ...(found.correctedQuery && { corregida: found.correctedQuery }),
        },
      })
      source.current = TYPED
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

  const logSearch = (term, from = TYPED) => {
    const clean = term.trim()
    if (!clean || clean === logged.current) return
    source.current = from
    // Si la respuesta de lo buscado aún no llega, se registra al llegar.
    if (ready && clean === text) record(clean, data)
    else wanted.current = clean
  }

  /** Una sugerencia (`from`: la fuente; una idea por defecto): se escribe en el campo y se registra al llegar su respuesta. */
  const pick = (term, from = SUGGESTED) => {
    setQuery(term)
    logSearch(term, from)
  }

  const searchExact = (term) => {
    setExactText(term)
    logged.current = null
    wanted.current = term
    source.current = CORRECTION
  }

  return { query, setQuery, data, loading, error, retry, hasQuery, logSearch, pick, searchExact }
}
