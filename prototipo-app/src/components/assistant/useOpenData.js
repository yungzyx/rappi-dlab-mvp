import { useRef, useState } from 'react'
import { profileLadder, tasteProfiles } from '../../api/agent'
import { profile as remoteProfile, recommendations } from '../../api/client'
import { noteShown } from '../../api/suggestions'
import { userId } from '../../api/user'
import { useEvents } from '../../state/EventsContext'
import { useOrders } from '../../state/OrdersContext'
import { useProfile } from '../../state/ProfileContext'

const DISCOVER_ROWS = 3

// Lo que se pide al abrir el buscador (lo aprendido, "Para ti" y "Descubre", el perfil de gusto con su escalera) se
// guarda OPEN_CACHE_MS por clave (`openKey`: la persona, la generación de su perfil y sus pedidos): abrir y cerrar el
// buscador seguido no lo vuelve a pedir, y lo que la persona busca aparece en "Aprendiendo de ti" al minuto. "Olvidar",
// un pedido (o una cancelación) o cambiar de persona en la demo cambian la clave. Lo que falla no se guarda: la próxima
// apertura lo vuelve a pedir.
export const OPEN_CACHE_MS = 60_000
let opened = { key: null, requests: {} }
function onOpen(key, name, load) {
  if (opened.key !== key) opened = { key, requests: {} }
  const { requests } = opened
  if (!requests[name] || Date.now() - requests[name].at >= OPEN_CACHE_MS) {
    const request = load()
    requests[name] = { request, at: Date.now() }
    request.catch(() => {
      if (requests[name]?.request === request) delete requests[name]
    })
  }
  return requests[name].request
}

/**
 * El perfil de gusto principal de la persona (`GET /profile/{id}/gustos`) con su escalera (el momento `perfil`), o
 * null si no tiene o no hay escalera: entonces el panel queda como siempre (también si la API no contesta).
 */
async function loadTaste() {
  const [main] = await tasteProfiles()
  const ladder = main ? await profileLadder(main.id) : null
  return ladder?.steps.length ? { profile: main, ladder } : null
}

/**
 * Lo que el buscador con Mochi pide al abrir: lo aprendido (`learnedRemote`), las filas de "Descubre" (`discoverRows`) y
 * el perfil de gusto con su escalera (`taste`; sin perfil, null). `load()` lo pide (o lo toma de la caché) y devuelve
 * las promesas que espera el saludo; `forget()` lo borra al "Olvidar", y lo que llegue después de borrar se ignora.
 */
export function useOpenData() {
  const profile = useProfile()
  const orders = useOrders()
  const events = useEvents()
  const generation = useRef(0) // sube al "Olvidar": un perfil remoto pedido antes ya no vale
  const [learnedRemote, setLearnedRemote] = useState(null)
  const [discoverRows, setDiscoverRows] = useState([])
  // El perfil de gusto de la persona y su escalera (`{ profile, ladder }`); sin perfil, null y el panel de siempre.
  const [taste, setTaste] = useState(null)

  /**
   * Muestra el perfil y cuenta sus productos como sugerencias mostradas (una vez por pestaña, como las demás). Cuentan
   * todos los peldaños: la escalera se pinta entera (una fila horizontal, como "Para ti"), aunque no quepa en pantalla.
   */
  const showTaste = (found) => {
    setTaste(found)
    for (const step of found?.ladder.steps ?? [])
      noteShown(events.track, step.products, {
        origin: 'agent-perfil',
        reason: found.ladder.reason,
        generation: profile.resets,
      })
  }

  const load = () => {
    // Si mientras tanto se tocó "Olvidar", la respuesta es de antes de borrar: se ignora.
    const current = generation.current
    const fresh = () => current === generation.current
    const person = userId()
    const ordersKey = `${orders?.orders.length ?? 0}:${orders?.orders.filter((o) => o.cancelled).length ?? 0}`
    const openKey = `${person}|${profile.resets}|${current}|${ordersKey}`
    const learned = onOpen(openKey, 'profile', () => remoteProfile(person))
      .then((data) => fresh() && setLearnedRemote(data.interests.slice(0, 3)))
      .catch(() => fresh() && setLearnedRemote(null))
    // Una sola petición sirve a "Para ti" y a "Descubre con el agente".
    const rows = onOpen(openKey, 'rows', () =>
      recommendations(person).then((data) => data.rows.filter((row) => row.products.length > 0)),
    ).catch(() => [])
    rows.then((list) => fresh() && setDiscoverRows(list.slice(0, DISCOVER_ROWS)))
    // Solo si sigue siendo la misma persona ("Olvidar" mientras llegaba): ni se muestra ni se cuenta.
    const taste = onOpen(openKey, 'taste', loadTaste).catch(() => null)
    taste.then((found) => fresh() && showTaste(found))
    return { rows, taste: taste.then((found) => (fresh() ? found : null)), learned }
  }

  const forget = () => {
    generation.current++
    setLearnedRemote(null)
    setDiscoverRows([])
    setTaste(null)
  }

  return { learnedRemote, discoverRows, taste, load, forget }
}
