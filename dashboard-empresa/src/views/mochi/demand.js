// Lo que buscan y encuentran poco: /analytics/assortment cruza el surtido real (la muestra pública) con la demanda de
// la fuente. Sin ítems, la API divide por 1 y la razón no significa nada: esos ya están en la demanda no satisfecha.

/** Los conceptos con más personas buscando que ítems en el catálogo (al menos uno), de mayor a menor razón. */
export function thinAssortment(rows, limit = 5) {
  return rows
    .filter((row) => row.items_en_catalogo > 0 && row.usuarios_por_item >= 1)
    .sort((a, b) => b.usuarios_por_item - a.usuarios_por_item)
    .slice(0, limit)
}
