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
]
