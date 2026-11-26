// Las métricas de /analytics que lee el panel, por fuente. Las graba `npm run panel:snapshot` para el panel en un solo
// HTML; un test revisa que cada vista pida solo métricas de esta lista.
export const PANEL_METRICS = [
  'kpis',
  'weekly',
  'combos',
  'at-risk',
  'volver',
  'offers',
  'suggestions',
  'services',
  'motor',
  'opportunities',
  'unmet',
  'trends',
  'assortment',
  'ctr-posicion',
  'embudo-sesion',
  'pro',
  'presencia',
  'experimentos',
  'verticales',
  'audiencias',
  'guardias',
]

// Las que escribe `make contract` en rappi-ia (tests/integration/test_contract.py, PANEL_METRICS) en src/fixtures/:
// `npm run fixtures` no las toca. Un test compara las dos listas.
export const CONTRACT_METRICS = [
  'offers',
  'unmet',
  'combos',
  'motor',
  'volver',
  'ctr-posicion',
  'embudo-sesion',
  'pro',
  'presencia',
  'experimentos',
  'verticales',
  'audiencias',
  'guardias',
]
