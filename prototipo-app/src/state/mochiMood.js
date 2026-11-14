import { useEffect, useSyncExternalStore } from 'react'
import { QUIET_EVENT, isQuiet } from './agentQuiet'
import { today } from '../utils/today'

// El ánimo de Mochi (la mascota): lo que hace con el cuerpo según lo que pasa en la app. No es texto ni un globo: la
// pose y el movimiento los pone Mascot.jsx con mascot.css. Hay dos clases de ánimo:
// - De fondo, mientras algo dura: "pensando" (`thinking`, una búsqueda o una respuesta en camino) y "con sueño"
//   (`quiet`: silenciado por hoy, agentQuiet.js). Mandan sobre las emociones: mientras duran, no entra ninguna y la que
//   corría se corta.
// - Emociones breves (`emote`), una a la vez, que vuelven solas a quieto. Una más importante (`rank`) entra aunque otra
//   esté corriendo; una igual o menos importante espera a que termine la anterior y pase el enfriamiento (si no, se
//   descarta: no se encolan, así Mochi no encadena una tras otra).
// Las disparan los eventos que registra la app (`observeMood`, desde EventsContext: `track`) y algunos estados que ya
// conocen los componentes (la búsqueda cargando, el pedido hecho, una oferta nueva en la Home).

/** Las emociones breves: cuánto duran (ms) y cuánto importan (una de rango mayor reemplaza a la que corre). */
export const EMOTIONS = {
  happy: { ms: 900, rank: 1 }, // llegaron resultados
  surprised: { ms: 1100, rank: 2 }, // una oferta nueva en la Home
  worried: { ms: 1800, rank: 2 }, // sin resultados o sin conexión
  celebrate: { ms: 1500, rank: 3 }, // aceptó algo de Mochi
  dance: { ms: 2600, rank: 4 }, // pedido confirmado
}
/** Tras una emoción, cuánto espera una igual o menos importante. */
export const COOLDOWN_MS = 1500
/** "Pensando" solo si la espera pasa de esto: una respuesta rápida no hace parpadear la pose. */
export const THINK_DELAY_MS = 300

const readQuiet = () => isQuiet(today())

// Lo que leen las mascotas: un objeto nuevo con cada cambio (useSyncExternalStore compara por referencia). `id` sube con
// cada emoción: la mascota la usa de llave para que la misma emoción dos veces vuelva a correr su animación.
let state = { emotion: null, id: 0, thinking: false, quiet: readQuiet() }
let playing = null // la emoción que corre: { rank }
let last = { rank: 0, endedAt: -Infinity } // la última que terminó, para el enfriamiento
let timer = null
const thinkers = new Set()
const listeners = new Set()

function set(change) {
  state = { ...state, ...change }
  listeners.forEach((listener) => listener())
}

function stop(now = Date.now()) {
  clearTimeout(timer)
  timer = null
  if (playing) last = { rank: playing.rank, endedAt: now }
  playing = null
  if (state.emotion) set({ emotion: null })
}

/**
 * Mochi muestra la emoción `name` (ver EMOTIONS) por `ms` (por defecto, la suya) y vuelve solo a quieto. Devuelve si
 * entró: no entra mientras manda un estado de fondo, ni si otra igual o más importante está corriendo o acaba de terminar.
 */
export function emote(name, { ms } = {}) {
  const spec = EMOTIONS[name]
  if (!spec || state.thinking || state.quiet) return false
  const now = Date.now()
  if (playing ? spec.rank <= playing.rank : spec.rank <= last.rank && now - last.endedAt < COOLDOWN_MS) return false
  clearTimeout(timer)
  playing = { rank: spec.rank }
  timer = setTimeout(() => stop(), ms ?? spec.ms)
  set({ emotion: name, id: state.id + 1 })
  return true
}

/** `token` (cualquier valor único) empieza o termina una espera: Mochi piensa mientras quede alguna. */
export function setThinking(token, on) {
  if (on) thinkers.add(token)
  else thinkers.delete(token)
  const thinking = thinkers.size > 0
  if (thinking === state.thinking) return
  if (thinking) stop()
  set({ thinking })
}

/** Vuelve a leer el silencio de hoy (lo avisa agentQuiet.js al silenciar o despertar). */
function refreshQuiet() {
  const quiet = readQuiet()
  if (quiet === state.quiet) return
  if (quiet) stop()
  set({ quiet })
}
globalThis.window?.addEventListener(QUIET_EVENT, refreshQuiet)
globalThis.window?.addEventListener('storage', refreshQuiet) // otra pestaña lo silenció

/**
 * Mira cada evento que registra la app (EventsContext: `track`): una búsqueda con resultados alegra a Mochi y una sin
 * nada lo preocupa; aceptar algo que propuso (un producto de su sugerencia, su oferta, "Ver en…") lo hace celebrar.
 */
export function observeMood(event) {
  if (event.type === 'search') {
    if (event.unmet) emote('worried')
    else if (event.results > 0) emote('happy')
  }
  if (event.type === 'suggestion_accepted') emote('celebrate')
}

function subscribe(listener) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** El ánimo de ahora: `{ emotion, id, thinking, quiet }`. */
export function useMochiMood() {
  return useSyncExternalStore(subscribe, () => state)
}

/**
 * Mochi piensa mientras `active` sea verdadero (una búsqueda o una respuesta en camino), si la espera pasa de
 * THINK_DELAY_MS. Al desmontarse, la espera termina.
 */
export function useMochiThinking(active) {
  useEffect(() => {
    if (!active) return undefined
    const token = {}
    const start = setTimeout(() => setThinking(token, true), THINK_DELAY_MS)
    return () => {
      clearTimeout(start)
      setThinking(token, false)
    }
  }, [active])
}

/** Para los tests y el "Panel de la demo" (que muestra una emoción sin esperar): como una pestaña nueva. */
export function resetMochiMood() {
  clearTimeout(timer)
  timer = null
  playing = null
  last = { rank: 0, endedAt: -Infinity }
  thinkers.clear()
  set({ emotion: null, id: 0, thinking: false, quiet: readQuiet() })
}
