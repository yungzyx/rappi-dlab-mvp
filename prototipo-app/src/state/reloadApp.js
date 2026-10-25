/**
 * Tras «Borrar mis datos» / «Olvidar» la app arranca de cero en la Home: el carro, los favoritos, la lealtad, la dirección y
 * la conversación con el agente viven en memoria, y recargar es la forma segura de que ninguno sobreviva.
 * (`#/home` y sin estado en el historial primero: useNavigation lee `history.state.nav` antes que el hash, y cambiar el
 * hash con `location.replace` no lo borra si ya era `#/home`; así la recarga no vuelve a la pantalla en que estaba.)
 */
export function reloadToHome() {
  window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}#/home`)
  window.location.reload()
}
