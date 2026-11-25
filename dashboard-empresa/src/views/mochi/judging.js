// "Juzgar la búsqueda": la muestra de pares (consulta, resultado) a ciegas y el juicio de quien juzga, que la API guarda
// en search_judgments (rappi-ia/src/rappi_ia/eval/human_judgments.py). Habla directo con la API: no tiene respaldo
// guardado ni foto, y en el HTML suelto (sin API) no escribe nada.
import { API_URL, LIVE_API } from '../../lib/api.js'

const TIMEOUT_MS = 30_000
const BASE = '/analytics/juicio-busqueda'

/** Los valores en el orden de los botones, con su tecla (la misma cifra que guarda la base). */
export const VERDICTS = [
  { level: 2, label: 'Sirve', hint: 'Es lo que esa persona quería encontrar.' },
  { level: 1, label: 'A medias', hint: 'Se parece o sirve para parte de lo pedido (otra marca o formato).' },
  { level: 0, label: 'No sirve', hint: 'No tiene que ver con lo que pedía.' },
]

/** Un rótulo como "J1": letras, números, - y _, hasta 16 (lo mismo que la tabla). Vacío vale. */
export const JUDGE_PATTERN = /^[A-Za-z0-9_-]{0,16}$/

export class JudgingError extends Error {}

async function request(path, options) {
  if (!LIVE_API) throw new JudgingError('Este archivo no tiene una API detrás: aquí no se juzga.')
  let response
  try {
    response = await fetch(`${API_URL}${path}`, { ...options, signal: AbortSignal.timeout(TIMEOUT_MS) })
  } catch {
    throw new JudgingError('La API no responde.')
  }
  if (response.status === 404 && !path.includes('/pares/')) {
    throw new JudgingError('Esta API no tiene encendidas las rutas del panel (API_ENABLE_ANALYTICS).')
  }
  if (!response.ok) throw new JudgingError(`La API respondió ${response.status}.`)
  return response.json()
}

/** `{ juez, muestra, fuera_del_catalogo, pares: [{ id, consulta, vertical, nombre, tienda, precio, imagen, … }] }`. */
export function loadPairs(judge) {
  return request(`${BASE}/pares?juez=${encodeURIComponent(judge)}`)
}

/** Guarda (o reemplaza) el juicio; devuelve el avance de ese juez. */
export function saveJudgment(pairId, level, judge) {
  return request(`${BASE}/pares/${encodeURIComponent(pairId)}`, {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ nivel: level, juez: judge }),
  })
}

/** El primer par sin juicio desde `from` (dando la vuelta); si todos tienen, -1. */
export function nextUnjudged(pairs, judgments, from = 0) {
  for (let step = 0; step < pairs.length; step += 1) {
    const index = (from + step) % pairs.length
    if (!(pairs[index].id in judgments)) return index
  }
  return -1
}

/** La tecla de un atajo (2, 1 o 0) o null: nunca mientras se escribe en un campo, ni con Ctrl, Alt o Cmd. */
export function shortcutLevel(event) {
  if (event.ctrlKey || event.metaKey || event.altKey) return null
  const target = event.target
  if (target?.closest?.('input, textarea, select, [contenteditable="true"]')) return null
  return VERDICTS.find((verdict) => String(verdict.level) === event.key)?.level ?? null
}
