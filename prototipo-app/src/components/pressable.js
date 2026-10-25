/**
 * Props para elementos que no son <button> pero actúan como uno (tarjetas con otros botones adentro):
 * se pueden enfocar y activar con Enter o Espacio, como un botón real.
 */
export function pressable(handler) {
  return {
    role: 'button',
    tabIndex: 0,
    onClick: handler,
    onKeyDown: (event) => {
      // Solo el elemento mismo: un Enter en un botón interno no debe activar también la tarjeta.
      if (event.target !== event.currentTarget) return
      if (event.key !== 'Enter' && event.key !== ' ') return
      event.preventDefault()
      handler(event)
    },
  }
}
