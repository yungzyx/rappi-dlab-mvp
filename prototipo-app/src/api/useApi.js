import { useCallback, useEffect, useState } from 'react'

const sameDeps = (a, b) => a.length === b.length && a.every((value, i) => Object.is(value, b[i]))

/**
 * Carga datos de la API al montar y cada vez que cambian `deps`: `{ data, error, loading, retry }`.
 * - `load` devuelve una promesa (o lanza); `error` es lo que falló, p. ej. un `ApiError`.
 * - Mientras carga, o si las dependencias cambiaron, `data` y `error` son `null`: nunca se muestra lo de otra llamada.
 * - La respuesta de una llamada vieja (otras dependencias, u otro intento) se ignora, y desmontar también la descarta.
 * - `retry()` vuelve a llamar a `load` con las mismas dependencias.
 * - Con `keepPrevious`, mientras carga la nueva llamada `data` sigue siendo la del último resultado (con `loading`
 *   en true): para listas que se refrescan al escribir y no deben parpadear. El `error` de antes sí se descarta.
 */
export function useApi(load, deps = [], { keepPrevious = false } = {}) {
  const [attempt, setAttempt] = useState(0)
  // La última respuesta, con las dependencias y el intento que la pidieron: solo vale mientras sigan siendo los actuales.
  const [result, setResult] = useState(null)

  useEffect(() => {
    let current = true
    ;(async () => {
      let outcome
      try {
        outcome = { data: await load(), error: null }
      } catch (error) {
        outcome = { data: null, error }
      }
      if (current) setResult({ deps, attempt, ...outcome })
    })()
    return () => {
      current = false
    }
    // `load` es el de esta vuelta (las pantallas lo pasan en línea): solo `deps` y `retry` piden otra llamada.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, attempt])

  const retry = useCallback(() => setAttempt((n) => n + 1), [])

  const settled = result !== null && result.attempt === attempt && sameDeps(result.deps, deps)
  return {
    data: settled || keepPrevious ? (result?.data ?? null) : null,
    error: settled ? result.error : null,
    loading: !settled,
    retry,
  }
}
