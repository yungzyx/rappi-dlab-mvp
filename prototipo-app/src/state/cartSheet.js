/**
 * Evento de ventana con que otro lugar de la app (el menú de Mochi: "Revisar mi carro") abre la hoja del carro de la
 * barra "Ver carro" (CartBar), sin buscar su botón en la página.
 */
export const OPEN_CART_EVENT = 'carro-abrir'

/** Abre la hoja del carro (la escucha CartBar mientras está montada). */
export const openCartSheet = () => window.dispatchEvent(new Event(OPEN_CART_EVENT))
