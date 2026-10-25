/**
 * Separa /analytics/trends (una sola lista ordenada por cambio absoluto) en los que suben y los que bajan,
 * cada uno del cambio más fuerte al más débil. `max` es la escala común para comparar largos entre ambas listas.
 */
export function splitTrends(rows) {
  const withChange = rows.filter((row) => row.crecimiento_pct !== null && row.crecimiento_pct !== 0)
  const rising = withChange
    .filter((row) => row.crecimiento_pct > 0)
    .sort((a, b) => b.crecimiento_pct - a.crecimiento_pct)
  const falling = withChange
    .filter((row) => row.crecimiento_pct < 0)
    .sort((a, b) => a.crecimiento_pct - b.crecimiento_pct)
  const max = Math.max(0, ...withChange.map((row) => Math.abs(row.crecimiento_pct)))
  return { rising, falling, max }
}
