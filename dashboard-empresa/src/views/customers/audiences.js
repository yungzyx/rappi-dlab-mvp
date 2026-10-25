// Audiencias de rescate: las personas en riesgo o perdidas que entrega /analytics/at-risk (hasta 100, primero las en
// riesgo más atrasadas respecto de su ritmo), agrupadas por lo que más pedían. El concepto top nunca es sensible: la
// API ya lo filtra. Sin concepto (solo pedidos sensibles o sin líneas) van en su propio grupo.

export const NO_CONCEPT = 'Sin concepto top'

/**
 * `[{ concept, people, atRisk, withConsent }]` de mayor a menor, desempatado por nombre. `people` cuenta en riesgo y
 * perdidas; `withConsent`, las que aceptan avisos fuera de la app.
 */
export function riskAudiences(rows) {
  const groups = new Map()
  for (const row of rows) {
    const concept = row.concepto_top ?? NO_CONCEPT
    const group = groups.get(concept) ?? { concept, people: 0, atRisk: 0, withConsent: 0 }
    group.people += 1
    if (row.estado === 'en_riesgo') group.atRisk += 1
    if (row.consiente_avisos) group.withConsent += 1
    groups.set(concept, group)
  }
  return [...groups.values()].sort((a, b) => b.people - a.people || a.concept.localeCompare(b.concept, 'es'))
}

/** Cuántas de las filas aceptan avisos fuera de la app. */
export const withConsent = (rows) => rows.filter((row) => row.consiente_avisos).length
