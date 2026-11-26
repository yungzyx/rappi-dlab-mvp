// Lo que viaja en el panel en un solo HTML (npm run panel:html): el archivo se comparte suelto, fuera del repositorio, y
// no lleva datos por persona del prototipo. La lista de riesgo del prototipo (/analytics/at-risk) es de personas que
// probaron la app: de cada fila queda solo lo que cuentan las audiencias por concepto (estado, concepto top y si acepta
// avisos), sin id, perfil, ritmo ni días, y en un orden que no dice quién iba más atrasada. Los simulados no son
// personas y quedan como están. vite.config.js lo aplica al armar el HTML, también a una foto grabada antes.

const KEPT = ['estado', 'concepto_top', 'consiente_avisos']

const sortKey = (row) => `${row.estado}\u0000${row.concepto_top ?? ''}\u0000${row.consiente_avisos ? 1 : 0}`

/** La foto (`{ grabado, catalogo, respuestas }`) lista para compartir; no cambia la que recibe. */
export function shareableSnapshot(snapshot) {
  const atRisk = snapshot.respuestas['at-risk.prototype']
  if (!Array.isArray(atRisk?.data) || atRisk.data.length === 0) return snapshot
  const data = atRisk.data
    .map((row) => Object.fromEntries(KEPT.map((key) => [key, row[key] ?? null])))
    .sort((a, b) => sortKey(a).localeCompare(sortKey(b)))
  return { ...snapshot, respuestas: { ...snapshot.respuestas, 'at-risk.prototype': { ...atRisk, data } } }
}
