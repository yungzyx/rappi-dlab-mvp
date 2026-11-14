// Respuestas de los simulados de antes del 14-11-2026, que no guardaban el momento de la oferta (todo caía en
// "sin momento"): el panel lo dice en vez de una tabla vacía. Desde esa fecha el generador las anota como `carrito`.
export const OFFERS_WITHOUT_MOMENT = {
  personas: 12,
  momentos: [
    {
      momento: 'sin_momento',
      mostradas: 16,
      aceptadas: 7,
      rechazadas: 9,
      abiertas: 0,
      por_que_abiertos: 0,
      aceptacion_pct: 43.8,
    },
  ],
  autopedidos: { pedidos: 0, personas: 0 },
}
