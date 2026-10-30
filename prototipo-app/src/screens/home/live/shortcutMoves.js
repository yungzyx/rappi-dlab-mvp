import { useEffect, useState } from 'react'
import { userId } from '../../../api/user'
import { SHORTCUTS } from '../../../data/home'

// Cuando cambia el orden de los accesos (GET /profile/{id}/verticales), Mochi los mueve a la vista y dice por qué. Para
// saber qué cambió se recuerda el último orden que la persona vio, en este navegador y con su id: al volver (o al
// recargar) con otro orden, también se ve el cambio. La primera vez, sin un orden anterior, no hay nada que explicar.

export const SEEN_KEY = 'rappi-proto-accesos-vistos'

/** El último orden que vio esta persona (códigos del backend), o null si no hay (o es de otra persona). */
export function readSeen(user) {
  try {
    const seen = JSON.parse(localStorage.getItem(SEEN_KEY))
    return seen?.user === user && Array.isArray(seen.order) ? seen.order : null
  } catch {
    return null
  }
}

function writeSeen(user, order) {
  try {
    localStorage.setItem(SEEN_KEY, JSON.stringify({ user, order }))
  } catch {
    // Sin almacenamiento: al recargar no se sabrá qué cambió, y Mochi no lo explica.
  }
}

const sameOrder = (a, b) => a?.length === b?.length && a.every((id, i) => id === b[i])

/**
 * El acceso que más lugares subió de `before` a `after`: `{ vertical, from, to }` (lugares desde 0). A igual subida, el
 * que quedó más adelante. Null si ninguno subió.
 */
export function biggestRise(before, after) {
  let best = null
  after.forEach((vertical, to) => {
    const from = before.indexOf(vertical)
    if (from > to && (!best || from - to > best.from - best.to)) best = { vertical, from, to }
  })
  return best
}

/** El nombre del acceso tal como se ve en la fila de la Home. */
export const shortcutName = (vertical) => SHORTCUTS.find((item) => item.vertical === vertical)?.label ?? vertical

/**
 * Lo que dice Mochi al mover un acceso. Con la razón de la API (`reason.text`, «Porque entras seguido a Rappi Mall.»)
 * dice esa razón; sin ella (la API solo la da al primero), que el orden sigue lo que más usa.
 */
export function moveText({ vertical, to, reason }) {
  const where = to === 0 ? 'al primer lugar' : 'más adelante'
  const because = reason?.text
    ?.trim()
    .replace(/^porque\s+/i, '')
    .replace(/\.$/, '')
  return because
    ? `Moví ${shortcutName(vertical)} ${where}: ${because}.`
    : `Moví ${shortcutName(vertical)} ${where}, según lo que más usas.`
}

/** «¿Por qué?» del globo: cómo se ordenan los accesos (motor/home.py), con la señal de la API. */
export const moveWhy = (reason) => ({
  text: 'Ordeno estos accesos por lo que más usas: lo que pides y lo que abres. Restaurantes y Turbo no se mueven.',
  basis: reason?.basis ?? [],
})

/**
 * El orden que muestra la fila (`order`) y el último cambio (`move`: `{ key, vertical, from, to, reason, requestId }`,
 * con una `key` nueva en cada cambio). Mientras la Home no está arriba (`active`), la fila queda como la vio la persona:
 * el cambio se ve al volver. Al abrir, la fila parte del último orden visto. Tras «Olvidar» (cambian las `resets`),
 * el orden fijo.
 */
export function useShortcutMove({ order, entries, requestId }, { active, resets }) {
  const [shown, setShown] = useState(() => ({ order: readSeen(userId()), resets, move: null }))
  const current = shown.resets === resets
  if (active && order && !(current && sameOrder(shown.order, order))) {
    const before = current ? shown.order : null
    const rise = before && biggestRise(before, order)
    const reason = rise ? (entries?.find((entry) => entry.id === rise.vertical)?.reason ?? null) : null
    setShown({
      order,
      resets,
      move: rise ? { ...rise, reason, requestId, key: (shown.move?.key ?? 0) + 1 } : shown.move,
    })
  }

  useEffect(() => {
    if (shown.order && shown.resets === resets) writeSeen(userId(), shown.order)
  }, [shown, resets])

  return { order: current ? shown.order : null, move: current ? shown.move : null }
}
