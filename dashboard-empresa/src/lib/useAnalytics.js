import { use, useSyncExternalStore } from 'react'
import { getFallbacks, loadAnalytics, subscribeConnection } from './api.js'

/** Datos de una métrica. Suspende mientras carga: envolver en <Async>. */
export function useAnalytics(name, source) {
  return use(loadAnalytics(name, source)).data
}

/** Varias métricas a la vez: pide todas antes de esperar la primera (sin cascada de requests). */
export function useAnalyticsMany(names, source) {
  const pending = names.map((name) => loadAnalytics(name, source))
  const results = []
  for (const promise of pending) results.push(use(promise).data)
  return results
}

/** Consultas que cayeron a los datos guardados: [{ key, name, reason }]. */
export function useFallbacks() {
  return useSyncExternalStore(subscribeConnection, getFallbacks)
}
