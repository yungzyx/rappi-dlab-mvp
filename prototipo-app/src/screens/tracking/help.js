// «Ayuda con este pedido», mínima y de demostración: problemas con productos (cuáles y por qué), dónde va el reembolso y
// el plazo. No se mueve dinero. El plazo para pedir ayuda y los días del reembolso son SUPUESTOS de la demo (la app de
// Rappi dice que hay un «tiempo límite» y que «aplican T&C», sin el número): se rotulan «de ejemplo».

export const HELP_WINDOW_HOURS = 48

export const HELP_REASONS = [
  { id: 'faltante', label: 'No llegó' },
  { id: 'mal_estado', label: 'Llegó en mal estado' },
  { id: 'equivocado', label: 'Me llegó otro producto' },
  { id: 'precio', label: 'Me cobraron otro precio' },
]

export const REFUND_METHODS = [
  { id: 'creditos', label: 'Créditos de ejemplo', when: 'Al instante, para tu próximo pedido' },
  { id: 'medio_pago', label: 'Medio de pago (Visa •••• 4242)', when: 'De 5 a 10 días hábiles' },
]

/** Hasta cuándo se puede pedir ayuda (ms): el plazo de ejemplo desde la entrega. */
export const helpDeadline = (deliveredAt) => deliveredAt + HELP_WINDOW_HOURS * 3_600_000

/** «martes 27 a las 15:30»: el día y la hora de `ts`, en la hora del teléfono. */
export const clockAndDay = (ts) => {
  const date = new Date(ts)
  const day = date.toLocaleDateString('es-CL', { weekday: 'long', day: 'numeric' })
  return `${day} a las ${date.toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })}`
}
