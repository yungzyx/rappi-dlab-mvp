// Nombre visible y pantalla de cada vertical. Un solo lugar para el agente con la API y las pantallas.

/** Por id de pantalla del prototipo (screens/vertical/data.js; Turbo y restaurantes tienen pantalla propia). */
export const VERTICAL_NAMES = {
  grocery: 'Súper',
  liquor: 'Licores',
  pharmacy: 'Farmacia',
  retail: 'Rappi Mall',
  express: 'Express',
  turbo: 'Turbo',
  pet: 'Mascotas',
  chocolates: 'Chocolatería',
  restaurants: 'Restaurantes',
  travel: 'Viajes',
}

// Códigos de vertical de la API → pantalla del prototipo. La API agrupa Turbo con Express (`prototype_vertical`),
// pero aquí Turbo abre su propia pantalla.
const BACKEND_SCREENS = {
  supermercado: 'grocery',
  licores: 'liquor',
  farmacia: 'pharmacy',
  mall: 'retail',
  conveniencia: 'express',
  turbo: 'turbo',
  chocolateria: 'chocolates',
  restaurantes: 'restaurants',
}
const OWN_SCREENS = new Set(['turbo', 'restaurants', 'travel', 'favor'])

export const screenForBackend = (vertical) => BACKEND_SCREENS[vertical] ?? null

/** Ruta de navegación que abre la pantalla de una vertical. */
export const routeForScreen = (screen) => (OWN_SCREENS.has(screen) ? [screen] : ['vertical', { id: screen }])
