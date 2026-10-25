import { useEffect, useRef, useState } from 'react'

const INITIAL = { stack: [{ name: 'home', params: {} }], homeTab: 'home' }

// Lo que se puede abrir desde un enlace escrito a mano: pestañas de la Home y pantallas que no necesitan parámetros.
const HOME_TABS = new Set(['home', 'offers', 'favorites', 'account'])
const LINKABLE_SCREENS = new Set(['restaurants', 'turbo', 'search', 'travel', 'favor', 'loyalty', 'orders'])

/** URL legible (#/vertical/store) para que cada pantalla tenga su propio link. */
function hashFor(nav) {
  const names = nav.stack.slice(1).map((entry) => entry.name)
  return `#/${names.length > 0 ? names.join('/') : nav.homeTab}`
}

/** Lo inverso de hashFor, para un hash escrito a mano: lo que no se puede abrir sin parámetros se ignora. */
function navFromHash(hash) {
  const names = hash.replace(/^#\/?/, '').split('/').filter(Boolean)
  if (names.length === 1 && HOME_TABS.has(names[0])) return { ...INITIAL, homeTab: names[0] }
  const screens = names.filter((name) => LINKABLE_SCREENS.has(name)).map((name) => ({ name, params: {} }))
  return { ...INITIAL, stack: [...INITIAL.stack, ...screens] }
}

// history.state solo acepta datos clonables: el viaje por JSON descarta funciones o componentes que se cuelen.
const toState = (nav, extra = {}) => ({ nav: JSON.parse(JSON.stringify(nav)), ...extra })

function readInitial() {
  return window.history.state?.nav ?? navFromHash(window.location.hash)
}

/**
 * Pila de pantallas sincronizada con el historial del navegador:
 * - push agrega una entrada; { replace: true } reutiliza la entrada del historial actual (p. ej. la del
 *   asistente) y { swap: true } además cambia la pantalla actual por la nueva (checkout → seguimiento);
 * - back usa history.back(), así el gesto "volver" de Safari y el botón ‹ hacen lo mismo;
 * - reset vuelve a la Home sin dejar la pila anterior (p. ej. al terminar un pedido);
 * - al recargar se recupera la pantalla desde history.state; un hash escrito a mano también navega.
 */
export function useNavigation() {
  const [nav, setNav] = useState(readInitial)
  const [direction, setDirection] = useState('none')
  const navRef = useRef(nav)
  const backIsOurs = useRef(false)

  useEffect(() => {
    navRef.current = nav
  }, [nav])

  useEffect(() => {
    // Primera carga (o recarga con el asistente abierto): deja una entrada limpia de la pantalla actual.
    window.history.replaceState(toState(navRef.current), '', hashFor(navRef.current))

    const onPopState = (event) => {
      let next = event.state?.nav
      if (!next) {
        // Hash escrito a mano (sin estado nuestro): se lee la ruta y se deja una entrada limpia.
        next = navFromHash(window.location.hash)
        window.history.replaceState(toState(next, event.state ?? {}), '', hashFor(next))
      }
      // Si el retroceso vino del gesto de Safari, el navegador ya animó: no repetir la animación.
      setDirection(backIsOurs.current ? 'pop' : 'none')
      backIsOurs.current = false
      setNav(next)
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  const push = (name, params = {}, { replace = false, swap = false } = {}) => {
    const base = swap ? navRef.current.stack.slice(0, -1) : navRef.current.stack
    const next = { ...navRef.current, stack: [...base, { name, params }] }
    if (replace || swap) window.history.replaceState(toState(next), '', hashFor(next))
    else window.history.pushState(toState(next), '', hashFor(next))
    navRef.current = next
    setDirection('push')
    setNav(next)
  }

  const back = () => {
    if (navRef.current.stack.length <= 1) return
    backIsOurs.current = true
    window.history.back()
  }

  // Vuelve a la Home dejando solo esa pantalla; reemplaza la entrada actual (volver desde la Home no reabre lo cerrado).
  const reset = () => {
    const next = { ...INITIAL, homeTab: 'home' }
    window.history.replaceState(toState(next), '', hashFor(next))
    navRef.current = next
    setDirection('pop')
    setNav(next)
  }

  // Cambiar de pestaña no crea historial (como en la app real): solo actualiza la entrada actual.
  const setHomeTab = (homeTab) => {
    const next = { ...navRef.current, homeTab }
    window.history.replaceState(toState(next), '', hashFor(next))
    navRef.current = next
    setNav(next)
  }

  return { stack: nav.stack, homeTab: nav.homeTab, direction, push, back, reset, setHomeTab }
}
