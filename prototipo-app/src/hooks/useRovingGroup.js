import { useRef } from 'react'

const STEPS = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }

/**
 * Un grupo de opciones (role radiogroup o tablist) que se recorre con las flechas, como en el patrón de ARIA: una sola
 * parada de Tab (la opción elegida o, si no hay, la primera habilitada), las flechas pasan a la siguiente o a la
 * anterior (con vuelta) e Inicio y Fin a los extremos. Moverse enfoca y elige (`onSelect(index)`); las opciones con
 * `isDisabled(index)` se saltan. `onKeyDown` va en el contenedor e `itemProps(index)` en cada opción.
 */
export function useRovingGroup(count, selectedIndex, onSelect, isDisabled = () => false) {
  const refs = useRef([])

  // Desde `from`, la próxima opción habilitada en la dirección `step`; `from` si no hay otra.
  const next = (from, step) => {
    for (let i = 1; i <= count; i += 1) {
      const index = (((from + step * i) % count) + count) % count
      if (!isDisabled(index)) return index
    }
    return from
  }
  const stop = selectedIndex >= 0 && !isDisabled(selectedIndex) ? selectedIndex : Math.max(next(-1, 1), 0)

  const onKeyDown = (event) => {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return
    const from = refs.current.slice(0, count).findIndex((el) => el?.contains(event.target))
    if (from < 0) return
    let to
    if (event.key in STEPS) to = next(from, STEPS[event.key])
    else if (event.key === 'Home') to = next(-1, 1)
    else if (event.key === 'End') to = next(count, -1)
    else return
    event.preventDefault()
    if (to === from || to < 0 || to >= count) return
    refs.current[to]?.focus()
    onSelect(to)
  }

  const itemProps = (index) => ({
    tabIndex: index === stop ? 0 : -1,
    ref: (el) => {
      refs.current[index] = el
    },
  })

  return { onKeyDown, itemProps }
}
