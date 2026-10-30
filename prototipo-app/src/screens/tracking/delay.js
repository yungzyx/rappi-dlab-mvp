// Atraso con compensación, solo de demostración: lo gatilla el "Panel de la demo" (components/demo/). El pedido se
// queda en su paso unos segundos, el tiempo estimado sube y llega un mensaje proactivo. En Turbo se cumple la garantía
// "min o gratis" con Créditos.
//
// La garantía, sus minutos, el monto y la regla son SUPUESTOS de la demo (la app de Rappi muestra "%@ min o gratis",
// pero la regla y la compensación las decide su servidor): se rotulan "de ejemplo" y nunca como política de Rappi.

/** Lo que se atrasa el pedido: segundos de la demo detenido en su paso y minutos que suma al tiempo estimado. */
export const DELAY = { seconds: 8, minutes: 12 }

// Supuesto: la garantía de Turbo de la demo. Si el pedido pasa de esos minutos, el pedido sale gratis en Créditos.
export const TURBO_GUARANTEE = { minutes: 15 }

/** El evento que manda el "Panel de la demo" para atrasar el pedido en curso (lo escucha OrdersContext). */
export const DEMO_DELAY_EVENT = 'rappi-demo-delay'

/** La compensación de un atraso: en Turbo, el total del pedido en Créditos de ejemplo; en las demás, ninguna. */
export const delayCompensation = (flow, order) => (flow.id === 'turbo' ? order.total : 0)
