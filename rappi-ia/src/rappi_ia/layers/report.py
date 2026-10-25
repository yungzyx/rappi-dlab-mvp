"""Reporte de calidad de las capas de perfiles: cobertura, fuentes y una muestra revisable a ojo."""

from psycopg import Connection


def _table(header: list[str], rows: list[tuple]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join("" if v is None else str(v) for v in row) + " |" for row in rows]
    return lines


def layer_report(conn: Connection, sample: int = 20) -> str:
    out = ["# Capas de perfiles", ""]
    # Una por capa y fuente: `motor` corre una vez por cada una (la fuente va en `counts`).
    runs = conn.execute(
        """SELECT DISTINCT ON (layer, counts->>'fuente')
                  layer || coalesce(' (' || (counts->>'fuente') || ')', ''), rules_version, status, finished_at::date,
                  counts::text
           FROM layer_runs ORDER BY layer, counts->>'fuente', run_id DESC"""
    ).fetchall()
    out += (
        ["## Última corrida de cada capa", ""] + _table(["Capa", "Reglas", "Estado", "Fecha", "Conteos"], runs) + [""]
    )

    items = conn.execute(
        """SELECT d.vertical, count(*) AS items,
                  round(100.0 * count(*) FILTER (WHERE EXISTS (
                    SELECT 1 FROM item_attributes a WHERE a.entity_type = d.entity_type AND a.entity_id = d.entity_id))
                    / count(*), 1) AS con_atributo,
                  round(100.0 * count(m.entity_id) FILTER (WHERE m.total > 0) / count(*), 1) AS con_medida
           FROM search_documents d
           LEFT JOIN item_measures m ON m.entity_type = d.entity_type AND m.entity_id = d.entity_id
           WHERE d.entity_type <> 'store' GROUP BY 1 ORDER BY 1"""
    ).fetchall()
    out += ["## Cobertura por vertical (% de ítems)", ""]
    out += _table(["Vertical", "Ítems", "Con algún atributo", "Con medida"], items) + [""]

    coverage = conn.execute(
        """SELECT a.attribute_id, d.family, count(*) AS items,
                  count(*) FILTER (WHERE a.source = 'rappi') AS rappi,
                  count(*) FILTER (WHERE a.source = 'regla') AS regla,
                  count(*) FILTER (WHERE a.source = 'derivado') AS derivado,
                  count(*) FILTER (WHERE a.source = 'curado') AS curado
           FROM item_attributes a JOIN attribute_defs d USING (attribute_id)
           GROUP BY 1, 2 ORDER BY d.family, 3 DESC"""
    ).fetchall()
    out += ["## Atributos: ítems y fuente", ""]
    out += _table(["Atributo", "Familia", "Ítems", "rappi", "regla", "derivado", "curado"], coverage) + [""]

    measures = conn.execute(
        """SELECT unit, count(*), count(*) FILTER (WHERE source = 'regla'), count(*) FILTER (WHERE pack > 1)
           FROM item_measures WHERE entity_type = 'catalog_item' GROUP BY 1 ORDER BY 2 DESC"""
    ).fetchall()
    out += ["## Medidas de productos", ""]
    out += _table(["Unidad base", "Ítems", "Corregidas por el nombre", "Con pack"], measures) + [""]

    odd = conn.execute(
        """SELECT r.vertical, r.concept_id, coalesce(ci.name, mi.name), round(r.unit_price::numeric), r.per,
                  round(r.median_price::numeric), round(r.ratio::numeric, 1)
           FROM capa.unit_price_ratios r
           LEFT JOIN catalog_items ci ON r.entity_type = 'catalog_item' AND ci.master_product_id::text = r.entity_id
           LEFT JOIN menu_items mi ON r.entity_type = 'menu_item' AND mi.item_id::text = r.entity_id
           WHERE r.items_in_group >= 8 AND (r.ratio >= 8 OR r.ratio <= 0.1)
           ORDER BY greatest(r.ratio, 1 / nullif(r.ratio, 0)) DESC LIMIT 25"""
    ).fetchall()
    out += ["## Precios por unidad atípicos (8 veces la mediana de su concepto, o menos de una décima)", ""]
    out += _table(["Vertical", "Concepto", "Ítem", "$/unidad", "por", "Mediana", "Veces"], odd) + [""]

    suspects = conn.execute(
        """SELECT m.suspect, count(*), (array_agg(left(ci.name, 40) ORDER BY ci.name))[1:3]::text
           FROM item_measures m JOIN catalog_items ci ON m.entity_type = 'catalog_item'
                AND ci.master_product_id::text = m.entity_id
           WHERE m.suspect IS NOT NULL GROUP BY 1 ORDER BY 2 DESC"""
    ).fetchall()
    out += ["## Medidas sospechosas de Rappi (fuera de `capa.item_unit_prices`)", ""]
    out += _table(["Motivo", "Ítems", "Ejemplos"], suspects) + [""]

    brands = conn.execute(
        """SELECT d.vertical, count(*) AS items,
                  round(100.0 * count(b.entity_id) / count(*), 1) AS con_marca,
                  count(*) FILTER (WHERE b.source = 'regla') AS deducidas,
                  count(c.master_product_id) AS con_canonico
           FROM search_documents d
           LEFT JOIN item_brands b ON b.entity_type = d.entity_type AND b.entity_id = d.entity_id
           LEFT JOIN item_canonical c ON d.entity_type = 'catalog_item' AND c.master_product_id::text = d.entity_id
           WHERE d.entity_type <> 'store' GROUP BY 1 ORDER BY 1"""
    ).fetchall()
    out += ["## Marcas y producto canónico por vertical", ""]
    out += _table(["Vertical", "Ítems", "% con marca", "Marca deducida del nombre", "Con producto canónico"], brands)
    out += [""]
    top = conn.execute(
        """SELECT p.name, p.kind, p.is_store_brand, p.items, count(a.alias) AS escrituras
           FROM product_brands p LEFT JOIN brand_aliases a USING (brand_key)
           GROUP BY p.brand_key, p.name, p.kind, p.is_store_brand, p.items ORDER BY p.items DESC LIMIT 15"""
    ).fetchall()
    out += (
        ["## Marcas con más ítems", ""] + _table(["Marca", "Tipo", "Marca propia", "Ítems", "Escrituras"], top) + [""]
    )
    shared = conn.execute(
        """SELECT label, items, array_to_string(verticals, ', ') FROM capa.canonical_products
           WHERE cardinality(verticals) >= 3 AND items > 1 ORDER BY items DESC, label LIMIT 15"""
    ).fetchall()
    out += ["## Productos canónicos con ids distintos de Rappi en 3 o más verticales", ""]
    out += _table(["Producto", "Ids de Rappi", "Verticales"], shared) + [""]

    out += _segment_sections(conn)

    out += [f"## Muestra revisable ({sample} ítems por atributo, orden fijo)", ""]
    for attribute_id, _family, *_ in coverage:
        rows = conn.execute(
            """SELECT a.entity_type, a.entity_id, coalesce(ci.name, mi.name), a.source, a.evidence
               FROM item_attributes a
               LEFT JOIN catalog_items ci ON a.entity_type = 'catalog_item' AND ci.master_product_id::text = a.entity_id
               LEFT JOIN menu_items mi ON a.entity_type = 'menu_item' AND mi.item_id::text = a.entity_id
               WHERE a.attribute_id = %s ORDER BY md5(a.entity_id || a.attribute_id) LIMIT %s""",
            (attribute_id, sample),
        ).fetchall()
        out += [f"### {attribute_id}", ""] + [
            f"- {name} _({source}: {evidence})_" for _t, _i, name, source, evidence in rows
        ]
        out.append("")
    return "\n".join(out)


MIN_SENSITIVE_GROUP = 5  # los segmentos sensibles solo se muestran con al menos tantas personas


def _segment_sections(conn: Connection) -> list[str]:
    families = conn.execute(
        """SELECT d.family, count(DISTINCT d.segment_id) AS definidos,
                  count(DISTINCT s.segment_id) AS con_personas, count(DISTINCT s.user_id) AS personas
           FROM segment_defs d LEFT JOIN user_segments s USING (segment_id)
           GROUP BY 1 ORDER BY 1"""
    ).fetchall()
    out = ["## Segmentos por familia", ""]
    out += _table(["Familia", "Definidos", "Con personas", "Personas distintas"], families) + [""]
    biggest = conn.execute(
        """SELECT source, segment_id, family, personas, pct FROM (
               SELECT u.source, s.segment_id, d.family, count(*) AS personas,
                      round(100.0 * count(*) / p.n, 1) AS pct,
                      row_number() OVER (PARTITION BY u.source ORDER BY count(*) DESC, s.segment_id) AS rank
               FROM user_segments s JOIN segment_defs d USING (segment_id)
               JOIN app_users u USING (user_id)
               JOIN (SELECT source, count(*) AS n FROM app_users GROUP BY 1) p ON p.source = u.source
               GROUP BY u.source, s.segment_id, d.family, d.sensitive, p.n
               HAVING NOT d.sensitive OR count(*) >= %s) t
           WHERE rank <= 15 ORDER BY source, rank""",
        (MIN_SENSITIVE_GROUP,),
    ).fetchall()
    out += ["## Segmentos más grandes (% de las personas de su fuente; sensibles solo con 5 o más)", ""]
    out += _table(["Fuente", "Segmento", "Familia", "Personas", "%"], biggest) + [""]
    empty = conn.execute(
        """SELECT segment_id, family FROM segment_defs d
           WHERE NOT EXISTS (SELECT 1 FROM user_segments s WHERE s.segment_id = d.segment_id)
           ORDER BY family, segment_id"""
    ).fetchall()
    out += ["## Segmentos sin ningún usuario (regla muy estricta, o el simulador no cubre ese comportamiento)", ""]
    out += _table(["Segmento", "Familia"], empty) + [""]
    return out
