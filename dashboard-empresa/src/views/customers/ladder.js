// La escalera de la tabla de Rappi («verticales usados juntos», /analytics/combos → rappi.filas): para cada
// combinación de grupos (rest, turbo, retail), la combinación con un grupo más que más retiene al mes siguiente.
// Es una correlación, no un efecto: quien pide mucho usa más verticales y además vuelve más.

const groupsOf = (combo) => combo.split('+')

/**
 * Un paso por combinación de partida que tiene a dónde subir: `{ from, to, added, fromPct, toPct, gain }`, con las
 * retenciones en % (la API las da como fracción) y `gain` en puntos. Ordenados por la parte de los usuarios que está
 * en la combinación de partida: arriba, donde está la mayoría. Las combinaciones sin retención o sin una combinación
 * con un grupo más (Favor) quedan fuera.
 */
export function ladderSteps(rows) {
  const measured = rows.filter((row) => row.retencion_m1 !== null && row.retencion_m1 !== undefined)
  return measured
    .map((from) => {
      const groups = groupsOf(from.combo)
      const next = measured
        .filter((to) => {
          const target = groupsOf(to.combo)
          return target.length === groups.length + 1 && groups.every((group) => target.includes(group))
        })
        .sort((a, b) => b.retencion_m1 - a.retencion_m1)[0]
      if (!next) return null
      const fromPct = from.retencion_m1 * 100
      const toPct = next.retencion_m1 * 100
      return {
        from,
        to: next,
        added: groupsOf(next.combo).find((group) => !groups.includes(group)),
        fromPct,
        toPct,
        gain: toPct - fromPct,
      }
    })
    .filter(Boolean)
    .sort((a, b) => b.from.pct_usuarios - a.from.pct_usuarios)
}

/** El paso donde está la mayoría de los usuarios (el primero de la escalera), o null si la tabla no trae ninguno. */
export function biggestStep(rows) {
  return ladderSteps(rows)[0] ?? null
}

/** Dominio del eje de retención: desde la decena bajo el menor valor (con aire) hasta 100%. */
export function retentionDomain(steps) {
  const lowest = Math.min(100, ...steps.flatMap((step) => [step.fromPct, step.toPct]))
  return [Math.max(0, Math.floor((lowest - 5) / 10) * 10), 100]
}
