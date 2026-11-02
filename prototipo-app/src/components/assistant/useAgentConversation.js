import { useCallback, useEffect, useRef, useState } from 'react'

const MIN_TYPING_MS = 450
const OFFLINE = 'Sin conexión'
export const STOPPED = 'Listo, paré aquí.'

let nextId = 1

/**
 * La conversación del buscador con Mochi: los mensajes, su ánimo (`mood`) y la fila de respuestas. Cada respuesta sale
 * cuando la anterior ya está en pantalla, con "escribiendo…" mientras tanto; "Cancelar" corta la que está en camino y,
 * sin conexión, la respuesta trae un "Reintentar". Los temporizadores (`later`) se limpian al desmontar.
 */
export function useAgentConversation() {
  const [messages, setMessages] = useState([])
  const [mood, setMood] = useState('idle')
  const [chipRound, setChipRound] = useState(0)
  const timers = useRef([])
  // Preguntas en fila: la siguiente sale cuando la respuesta anterior ya está en pantalla.
  const askQueue = useRef(Promise.resolve())
  // La respuesta en curso, para "Cancelar" (su AbortController).
  const pending = useRef(null)
  // La respuesta en pantalla: un autopedido que sale cuando ya no se ve avisa con un toast.
  const shownAnswer = useRef(null)

  // Cada temporizador sale de la lista al correr (si no, crecía toda la sesión).
  const later = (fn, ms) => {
    const id = setTimeout(() => {
      timers.current = timers.current.filter((t) => t !== id)
      fn()
    }, ms)
    timers.current.push(id)
    return id
  }
  useEffect(() => () => timers.current.forEach(clearTimeout), [])

  useEffect(() => {
    shownAnswer.current = messages.findLast((m) => m.from === 'bot')
  }, [messages])

  const addMessage = (message) => setMessages((prev) => [...prev, { id: nextId++, ...message }])

  /**
   * Muestra "escribiendo…" hasta que llega la respuesta de la API, con un mínimo para que se note.
   * Devuelve una promesa que se cumple cuando la respuesta ya está en pantalla.
   */
  const botSays = useCallback((responseOrPromise, { cancellable = false } = {}) => {
    const typingId = nextId++
    const startedAt = Date.now()
    setMood('think')
    setMessages((prev) => [...prev, { id: typingId, from: 'bot', typing: true, cancellable }])
    return Promise.resolve(responseOrPromise).then(
      (response) =>
        new Promise((shown) => {
          const wait = Math.max(0, MIN_TYPING_MS - (Date.now() - startedAt))
          later(() => {
            setMood('talk')
            // Id nuevo: si reutilizara el del indicador, React conservaría su estado y mostraría las tarjetas antes del texto.
            setMessages((prev) => [
              ...prev.filter((m) => m.id !== typingId),
              { id: nextId++, from: 'bot', animate: true, ...response },
            ])
            setChipRound((r) => r + 1)
            shown()
          }, wait)
        }),
    )
  }, [])

  /**
   * Pone una respuesta en la fila: la siguiente sale cuando esta ya está en pantalla. `run(signal)` la pide; mientras
   * espera, "Cancelar" corta la petición y Mochi dice que paró (lo que llegue después se descarta). El saludo no se
   * cancela (`cancellable: false`).
   */
  const ask = (run, { cancellable = true } = {}) => {
    askQueue.current = askQueue.current.then(() => {
      if (!cancellable) return botSays(run())
      const controller = new AbortController()
      pending.current = controller
      const stopped = new Promise((resolve) =>
        controller.signal.addEventListener('abort', () => resolve({ text: STOPPED }), { once: true }),
      )
      return botSays(Promise.race([run(controller.signal), stopped]), { cancellable: true }).finally(() => {
        if (pending.current === controller) pending.current = null
      })
    })
  }
  const cancelAnswer = () => pending.current?.abort()

  /**
   * Cuando la API no contesta: "Sin conexión" y un botón que vuelve a pedir lo mismo, una sola vez (dos toques no
   * encolan dos respuestas; si vuelve a fallar, el nuevo "Sin conexión" trae su propio botón).
   */
  const offline = (run) => {
    let used = false
    return {
      text: OFFLINE,
      retry: () => {
        if (used) return
        used = true
        ask(run)
      },
    }
  }

  const markStreamed = useCallback((id) => {
    setMood((m) => (m === 'talk' ? 'idle' : m))
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, animate: false } : m)))
  }, [])

  return {
    messages,
    mood,
    setMood,
    chipRound,
    nextChipRound: () => setChipRound((r) => r + 1),
    later,
    addMessage,
    ask,
    cancelAnswer,
    offline,
    markStreamed,
    shownAnswer,
    // Lo que está en la fila ("Olvidar" lo espera antes de borrar).
    queued: () => askQueue.current,
  }
}
