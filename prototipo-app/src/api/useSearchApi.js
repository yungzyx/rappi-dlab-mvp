import { useEffect, useState } from 'react'
import { searchAll } from './search'
import { useApi } from './useApi'

const MIN_CHARS = 2
const DEBOUNCE_MS = 250

/**
 * Resultados de buscar `query` (grupos por vertical, ver `searchAll`): `{ data, loading, error, retry }`.
 * - No consulta con menos de 2 caracteres (entonces `data` es null y no carga) y espera 250 ms tras la última tecla;
 *   si ya viene con texto al montar (p. ej. una categoría), consulta de inmediato.
 * - Mientras espera o carga, `data` sigue siendo el resultado anterior (la lista no parpadea) y `loading` es true.
 * - Una respuesta vieja nunca reemplaza a una más nueva.
 * - `vertical` busca solo en esa vertical; `current` es la vertical de la pantalla (la API la suma a las que busca).
 * - `exactQuery`: el texto que se pide tal cual, sin que la API corrija errores de tipeo. Se compara con lo que se
 *   consulta (ya pasada la espera de la tecla), así que escribir no repite la consulta anterior con corrección.
 */
export function useSearchApi(query, { vertical, current, exactQuery = null } = {}) {
  const text = query.trim()
  const searchable = text.length >= MIN_CHARS
  const [settled, setSettled] = useState(text)

  useEffect(() => {
    const timer = setTimeout(() => setSettled(text), DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [text])

  const target = searchable && settled.length >= MIN_CHARS ? settled : null
  const exact = target !== null && target === exactQuery
  const api = useApi(
    () => (target === null ? Promise.resolve(null) : searchAll(target, { vertical, current, exact })),
    [target, vertical ?? null, current ?? null, exact],
    { keepPrevious: true },
  )

  if (!searchable) return { data: null, loading: false, error: null, retry: api.retry }
  // `settled` queda atrás de lo escrito durante la espera de la tecla: sigue cargando.
  return { ...api, loading: api.loading || settled !== text }
}
