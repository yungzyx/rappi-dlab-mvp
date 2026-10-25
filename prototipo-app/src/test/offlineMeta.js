// Una muestra mínima para los tests de la API simulada (no se importa desde la app; la muestra real, snapshot.json, no
// está en git). Copia del backend, a mano (si cambian allá, cambiar acá):
// - COMBOS: rappi-ia/src/rappi_ia/motor/combos.toml ([grupos], retencion_m1 de cada [combinaciones], [rendimiento_
//   decreciente] y [servicios]) y, de motor/combos.py, FINE_ORDER, SERVICES y OWN_SIGNALS_ONLY;
// - LABELS: VERTICAL_LABELS de rappi-ia/src/rappi_ia/agent/tools.py;
// - SCREENS: SCREEN_VERTICALS de rappi-ia/src/rappi_ia/agent/grouped_search.py;
// - SERVICES: id, nombre y ruta de RappiFavor y RappiTravel en concepts/taxonomy.toml (el `pitch` está acortado);
// - FEATURED: rappi-ia/src/rappi_ia/offers/destacado.toml (precio mínimo, conceptos fuera y, acortadas, secciones de
//   relleno, en palabras como las escribe scripts/demo-snapshot-meta.py).
// CONCEPTS y los productos son inventados (con los grupos y la marca `offerable` que daría offers/guards.py).

export const COMBOS = {
  groups: {
    rest: ['restaurantes'],
    turbo: ['turbo'],
    retail: ['supermercado', 'conveniencia', 'farmacia', 'licores', 'mall', 'chocolateria'],
  },
  retention: {
    rest: 0.47,
    turbo: 0.5,
    'rest+turbo': 0.82,
    retail: 0.41,
    'rest+retail': 0.76,
    'rest+turbo+retail': 0.93,
    'turbo+retail': 0.8,
    favor: 0.44,
  },
  diminishing: { reduction_base: 0.1, decay: 0.5, service: 0.05 },
  services: { favor: 'rappifavor', travel: 'rappitravel' },
  fine_order: [
    ...['restaurantes', 'turbo', 'supermercado', 'conveniencia', 'mall', 'chocolateria', 'farmacia', 'licores'],
    ...['favor', 'travel'],
  ],
  service_keys: ['favor', 'travel'],
  own_signals_only: ['farmacia', 'licores'],
}

export const LABELS = {
  supermercado: 'el súper',
  conveniencia: 'Express',
  turbo: 'Turbo',
  mall: 'Rappi Mall',
  farmacia: 'farmacia',
  licores: 'Licores',
  chocolateria: 'chocolaterías',
  restaurantes: 'restaurantes',
}

export const SCREENS = {
  supermercado: 'grocery',
  licores: 'liquor',
  farmacia: 'pharmacy',
  mall: 'retail',
  conveniencia: 'express',
  turbo: 'turbo',
  chocolateria: 'chocolates',
  restaurantes: 'restaurants',
}

// `keywords`, `alone` y `avoid` van normalizados, como los escribe scripts/demo-snapshot-meta.py.
export const CONCEPTS = {
  cafe: {
    name: 'Café',
    emoji: '☕',
    group: 'bebidas',
    offerable: true,
    keywords: ['cafe', 'espresso'],
    avoid: ['taza'],
  },
  galletas: { name: 'Galletas', emoji: '🍪', group: 'dulces', offerable: true, keywords: ['galletas', 'galleta'] },
  cerveza: {
    name: 'Cerveza',
    emoji: '🍺',
    group: 'alcohol',
    offerable: false,
    keywords: ['cerveza'],
    alone: ['chela'],
  },
  panales: { name: 'Pañales', emoji: '👶', group: 'bebe', offerable: false, keywords: ['panales'] },
  analgesicos: { name: 'Analgésicos', emoji: '💊', group: 'salud', offerable: false },
  hielo: { name: 'Hielo', emoji: '🧊', group: 'bebidas', offerable: true, keywords: ['hielo'] },
  juguetes: {
    name: 'Juguetes',
    emoji: '🧸',
    group: 'juguetes',
    offerable: true,
    keywords: ['juguetes', 'juguete', 'peluche'],
  },
}

export const SERVICES = {
  favor: { id: 'rappifavor', name: 'RappiFavor', pitch: 'un Rappitendero lleva lo que necesites', route: 'favor' },
  travel: { id: 'rappitravel', name: 'RappiTravel', pitch: 'vuelos y hoteles', route: 'travel' },
}

export const FEATURED = {
  min_main_price: 3000,
  not_main: ['cafe', 'helados', 'pasteleria', 'postres'],
  side_sections: [['agregados'], ['extras'], ['bebidas'], ['salsas']],
}

export const META = {
  combos: COMBOS,
  featured: FEATURED,
  vertical_labels: LABELS,
  screen_verticals: SCREENS,
  concepts: CONCEPTS,
  services: SERVICES,
  occasion_keywords: ['asado', 'carrete'],
  filler_words: ['hola', 'quiero', 'busco'],
}

/** Un producto con lo que trae la API. */
export const product = (entityId, fields = {}) => ({
  id: `cat-${entityId}`,
  entity_type: 'catalog_item',
  entity_id: String(entityId),
  name: `Producto ${entityId}`,
  vertical: 'supermercado',
  concept: 'cafe',
  price: '$1.000',
  price_value: 1000,
  before: null,
  discount: null,
  store: 'Tienda de prueba',
  store_id: 1,
  img: null,
  age_restricted: false,
  presentation: null,
  ...fields,
})

/** La oferta grabada de un paso de la escalera (como la escribe `npm run demo:snapshot`). */
export const recordedStep = (vertical, products) => ({
  moment: 'vertical_por_probar',
  text: `Lo más pedido en ${LABELS[vertical]}.`,
  products,
  vertical,
  prototype_vertical: SCREENS[vertical],
  reason: {
    text: `Porque aún no pides en ${LABELS[vertical]}: esto es lo que más se pide.`,
    basis: [
      { kind: 'combinacion', id: 'grabada', source: 'rappi+poblacion:synthetic' },
      { kind: 'lo_mas_pedido', id: vertical, source: 'poblacion:synthetic' },
    ],
  },
  actions: [{ label: `Abrir ${LABELS[vertical]}`, route: [SCREENS[vertical]] }],
})
