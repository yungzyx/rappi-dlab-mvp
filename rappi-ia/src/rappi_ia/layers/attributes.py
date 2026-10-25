"""Atributos de ítem (sin gluten, vegano, familiar…): lo que Rappi declara, lo que dicen el nombre y la descripción,
y lo derivado de precios y marcas. Las reglas viven en `concepts/attributes.toml`."""

import logging
import tomllib
from dataclasses import dataclass
from pathlib import Path

from psycopg import Connection

from ..text import LEAFLET_WARNINGS, normalize
from .runs import finish_layer_run, rules_version, start_layer_run

log = logging.getLogger(__name__)

RULES_FILE = Path(__file__).resolve().parents[1] / "concepts" / "attributes.toml"
RAPPI_CONFIDENCE = 0.95
RULE_CONFIDENCE = 0.8
FAMILIES = {"dieta", "alergenos", "publico", "formato", "precio", "origen", "sustentable", "ocasion", "platos"}
_TRUE = {"true", "si", "sí", "yes", "1"}
DERIVED_CONFIDENCE = 0.9
# Las descripciones son largas y mencionan de todo («apta para vidrio», «con papas fritas»): solo son fiables en lo
# que el producto declara ser (dieta, alérgenos, sustentabilidad). El resto sale del nombre y la categoría.
DESCRIPTION_FAMILIES = {"dieta", "alergenos", "sustentable"}
MIN_CONCEPT_ITEMS_FOR_PRICE = 8  # «económico» exige al menos tantos ítems del concepto en la vertical para comparar


@dataclass(frozen=True)
class AttributeRule:
    attribute_id: str
    name: str
    family: str
    applies_to: str  # catalog_item | menu_item | both
    value_type: str
    description: str
    rappi: tuple[dict, ...] = ()
    phrases: tuple[str, ...] = ()
    catalog_phrases: tuple[str, ...] = ()  # como `phrases`, pero solo en productos: en un plato son un ingrediente
    negations: tuple[str, ...] = ()
    derived: bool = False
    use_description: bool | None = None  # None: según la familia (DESCRIPTION_FAMILIES)
    only_groups: tuple[str, ...] = ()  # las frases solo valen si el concepto del ítem es de uno de estos grupos

    def applies(self, entity_type: str) -> bool:
        return self.applies_to in ("both", entity_type)


@dataclass(frozen=True)
class Detected:
    attribute_id: str
    value: str | None
    source: str
    confidence: float
    evidence: str


def load_attribute_rules(path: Path | None = None) -> tuple[str, list[AttributeRule]]:
    raw = tomllib.loads((path or RULES_FILE).read_text(encoding="utf-8"))
    rules = [
        AttributeRule(
            attribute_id=a["id"],
            name=a["name"],
            family=a["family"],
            applies_to=a["applies_to"],
            value_type=a.get("value_type", "flag"),
            description=a.get("description", ""),
            rappi=tuple(a.get("rappi", ())),
            phrases=tuple(a.get("phrases", ())),
            catalog_phrases=tuple(a.get("catalog_phrases", ())),
            negations=tuple(a.get("negations", ())),
            derived=a.get("derived", False),
            use_description=a.get("use_description"),
            only_groups=tuple(a.get("only_groups", ())),
        )
        for a in raw["attribute"]
    ]
    return raw["version"], rules


def _stem(word: str) -> str:
    """Raíz para comparar singular y plural («ninos» = «nino», «panales» = «panal», «mujeres» = «mujer»)."""
    if len(word) > 4 and word.endswith("es") and word[-3] not in "aeiou":
        return word[:-2]
    if len(word) > 3 and word.endswith("s"):
        return word[:-1]
    return word


def phrase_key(phrase: str) -> tuple[str, ...]:
    return tuple(_stem(w) for w in normalize(phrase).split())


class _Detector:
    """Cada atributo se busca por separado: a diferencia de los conceptos, dos atributos pueden calzar las mismas
    palabras («sin azúcar» y «zero»), y la negación de uno no debe tapar la frase de otro."""

    def __init__(self, rules: list[AttributeRule]):
        self.rules = [r for r in rules if not r.derived]
        self.phrases: dict[tuple[str, ...], list[tuple[str, str, bool]]] = {}
        self.negations: dict[tuple[str, ...], list[str]] = {}
        for r in self.rules:
            for p in r.phrases:
                self.phrases.setdefault(phrase_key(p), []).append((r.attribute_id, p, False))
            for p in r.catalog_phrases:
                self.phrases.setdefault(phrase_key(p), []).append((r.attribute_id, p, True))
            for n in r.negations:
                self.negations.setdefault(phrase_key(n), []).append(r.attribute_id)
        self.longest = max(len(k) for k in [*self.phrases, *self.negations])

    def hits(self, text: str, entity_type: str = "catalog_item") -> tuple[dict[str, str], set[str]]:
        """({atributo: primera frase que calzó}, atributos negados) en el texto."""
        words = [_stem(w) for w in normalize(text).split()]
        found: dict[str, str] = {}
        negated: set[str] = set()
        for start in range(len(words)):
            for size in range(1, min(self.longest, len(words) - start) + 1):
                key = tuple(words[start : start + size])
                for attribute_id, phrase, catalog_only in self.phrases.get(key, ()):
                    if not catalog_only or entity_type == "catalog_item":
                        found.setdefault(attribute_id, phrase)
                if self.negations.get(key) and not (start and words[start - 1] in ("no", "sin")):
                    negated.update(self.negations[key])  # «no contiene azúcar» no es «contiene azúcar»
        return found, negated


_CACHE: list = []  # [(reglas, detector)]: se guarda la lista misma para que su id no se reutilice


def _detector(rules: list[AttributeRule]) -> _Detector:
    if not _CACHE or _CACHE[0][0] is not rules:
        _CACHE[:] = [(rules, _Detector(rules))]
    return _CACHE[0][1]


def _rappi_says(rule: AttributeRule, rappi: dict) -> tuple[str | None, bool]:
    """(campo que lo dice, bloqueado): un `false` explícito de Rappi en una bandera bloquea las frases."""
    blocked = False
    for spec in rule.rappi:
        values = spec.get("values")
        for key in spec["keys"]:
            if key not in rappi:
                continue
            value = rappi[key]
            if values:
                if str(value).strip().lower() in {v.lower() for v in values}:
                    return key, False
            elif values is not None:  # `values = []`: basta con que el campo traiga algo
                if value not in (None, "", False):
                    return key, False
            elif value is True or str(value).strip().lower() in _TRUE:
                return key, False
            elif value is False or str(value).strip().lower() in ("false", "no", "0"):
                blocked = True
    return None, blocked


def detect_attributes(
    entity_type: str,
    name: str,
    category: str | None,
    description: str | None,
    rappi: dict | None,
    rules: list[AttributeRule],
    group: str | None = None,
) -> list[Detected]:
    """Los atributos de un ítem. `group` es el grupo de su concepto (para las reglas con `only_groups`). La descripción
    solo cuenta para las familias de DESCRIPTION_FAMILIES (o las reglas que lo piden con `use_description`)."""
    detector = _detector(rules)
    rappi = rappi or {}
    head = description or ""
    if m := LEAFLET_WARNINGS.search(normalize(head)):
        head = normalize(head)[: m.start()]
    name_hits, name_neg = detector.hits(". ".join(part for part in (name, category) if part), entity_type)
    full_hits, full_neg = detector.hits(". ".join(part for part in (name, category, head) if part), entity_type)
    found = []
    for rule in detector.rules:
        if not rule.applies(entity_type):
            continue
        key, blocked = _rappi_says(rule, rappi)
        if key is not None:
            found.append(Detected(rule.attribute_id, None, "rappi", RAPPI_CONFIDENCE, key))
            continue
        if blocked or (rule.only_groups and not _in_groups(rule, entity_type, group)):
            continue
        uses_description = (
            rule.use_description if rule.use_description is not None else rule.family in DESCRIPTION_FAMILIES
        )
        hits, negated = (full_hits, full_neg) if uses_description else (name_hits, name_neg)
        if rule.attribute_id in hits and rule.attribute_id not in negated:
            found.append(Detected(rule.attribute_id, None, "regla", RULE_CONFIDENCE, hits[rule.attribute_id]))
    if any(d.attribute_id == "vegano" for d in found) and not any(d.attribute_id == "vegetariano" for d in found):
        found.append(Detected("vegetariano", None, "derivado", DERIVED_CONFIDENCE, "vegano"))  # todo vegano lo es
    return found


# Un plato sin concepto sigue siendo comida: las reglas acotadas a grupos de comida valen para él.
_FOOD_GROUPS = frozenset({"alcohol", "bebidas", "snacks", "dulces", "despensa", "frescos", "comida"})


def _in_groups(rule: AttributeRule, entity_type: str, group: str | None) -> bool:
    if group is None and entity_type == "menu_item":
        return bool(_FOOD_GROUPS & set(rule.only_groups))
    return group in rule.only_groups


_COLUMNS = "entity_type, entity_id, attribute_id, value, source, confidence, evidence, rules_version, run_id"

# Precio y descuento vigentes, como los ve la búsqueda (las ofertas vigentes de v_latest_offers).
_DISCOUNTED = f"""
INSERT INTO item_attributes ({_COLUMNS})
SELECT 'catalog_item', sp.master_product_id::text, 'con-descuento', NULL, 'derivado', %(conf)s,
       '-' || round(max(100 * (1 - lp.price / lp.real_price)))::int || '%%', %(version)s, %(run)s
FROM store_products sp
JOIN v_latest_offers lp ON lp.store_id = sp.store_id AND lp.sku = sp.sku
WHERE sp.master_product_id IS NOT NULL AND lp.current
  AND lp.real_price > 0 AND lp.price > 0 AND lp.price < lp.real_price
GROUP BY sp.master_product_id
ON CONFLICT DO NOTHING
"""

# «Económico» compara el precio por unidad (kg, l, und) dentro del concepto, la vertical y la unidad: un sobre de 15 g
# es barato en la góndola y caro por gramo. Sin medida comparable, se compara el precio de góndola.
_CHEAP = f"""
WITH priced AS (
    SELECT sd.entity_id, sd.vertical, ic.concept_id,
           coalesce(m.unit, 'precio') AS per,
           CASE WHEN m.total > 0 AND m.suspect IS NULL THEN sd.price_min / m.total ELSE sd.price_min END AS metric,
           CASE WHEN m.total > 0 AND m.suspect IS NULL THEN m.unit ELSE NULL END AS measured
    FROM search_documents sd
    JOIN item_concepts ic ON ic.entity_type = sd.entity_type AND ic.entity_id = sd.entity_id
    LEFT JOIN item_measures m ON m.entity_type = sd.entity_type AND m.entity_id = sd.entity_id
    WHERE sd.entity_type = 'catalog_item' AND sd.price_min > 0
), grouped AS (
    SELECT entity_id, vertical, concept_id, coalesce(measured, 'precio') AS per, metric FROM priced
), cutoffs AS (
    SELECT concept_id, vertical, per, percentile_cont(0.25) WITHIN GROUP (ORDER BY metric) AS p25
    FROM grouped GROUP BY concept_id, vertical, per HAVING count(*) >= %(min_items)s
)
INSERT INTO item_attributes ({_COLUMNS})
SELECT DISTINCT ON (g.entity_id) 'catalog_item', g.entity_id, 'economico', NULL, 'derivado', %(conf)s,
       'p25 de ' || g.concept_id || ' en ' || g.vertical || ' (' || g.per || ')', %(version)s, %(run)s
FROM grouped g JOIN cutoffs c USING (concept_id, vertical, per)
WHERE g.metric <= c.p25
ORDER BY g.entity_id, g.vertical
ON CONFLICT DO NOTHING
"""

_STORE_BRAND = f"""
INSERT INTO item_attributes ({_COLUMNS})
SELECT b.entity_type, b.entity_id, 'marca-propia', NULL, 'derivado', %(conf)s, p.name, %(version)s, %(run)s
FROM item_brands b JOIN product_brands p USING (brand_key)
WHERE p.is_store_brand AND b.entity_type = 'catalog_item'
ON CONFLICT DO NOTHING
"""

_FROM_MEASURES = f"""
INSERT INTO item_attributes ({_COLUMNS})
SELECT entity_type, entity_id, 'pack', NULL, 'derivado', %(conf)s, 'x' || pack, %(version)s, %(run)s
FROM item_measures WHERE entity_type = 'catalog_item' AND pack > 1
UNION ALL
SELECT entity_type, entity_id,
       CASE WHEN size_label = 'familiar' THEN 'familiar'
            WHEN size_label LIKE 'para %%' THEN 'para-compartir'
            WHEN size_label = 'individual' THEN 'individual' END,
       NULL, 'regla', 0.8, size_label, %(version)s, %(run)s
FROM item_measures
WHERE entity_type = 'menu_item' AND (size_label IN ('familiar', 'individual') OR size_label LIKE 'para %%')
ON CONFLICT DO NOTHING
"""


def _seed_definitions(conn: Connection, rules: list[AttributeRule], version: str) -> None:
    for r in rules:
        conn.execute(
            """INSERT INTO attribute_defs
                 (attribute_id, name, family, applies_to, value_type, description, rules_version)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (attribute_id) DO UPDATE SET name = EXCLUDED.name, family = EXCLUDED.family,
                 applies_to = EXCLUDED.applies_to, value_type = EXCLUDED.value_type,
                 description = EXCLUDED.description, rules_version = EXCLUDED.rules_version""",
            (r.attribute_id, r.name, r.family, r.applies_to, r.value_type, r.description, version),
        )
    conn.execute(
        """DELETE FROM attribute_defs d WHERE d.attribute_id <> ALL(%s)
           AND NOT EXISTS (
             SELECT 1 FROM item_attributes i WHERE i.attribute_id = d.attribute_id AND i.source = 'curado')""",
        ([r.attribute_id for r in rules],),
    )


def build_attributes(conn: Connection) -> dict:
    """Recalcula `item_attributes` de todos los productos y platos (idempotente). Lo `curado` a mano no se toca."""
    version, rules = load_attribute_rules()
    version = rules_version(version, RULES_FILE, Path(__file__))
    run = start_layer_run(conn, "attributes", version)
    _seed_definitions(conn, rules, version)
    conn.execute("DELETE FROM item_attributes WHERE source <> 'curado'")
    curated = {
        (e, i, a) for e, i, a in conn.execute("SELECT entity_type, entity_id, attribute_id FROM item_attributes")
    }
    groups = {
        (e, i): g
        for e, i, g in conn.execute(
            "SELECT ic.entity_type, ic.entity_id, c.parent_id FROM item_concepts ic JOIN concepts c USING (concept_id)"
        )
    }
    counts = {"definiciones": len(rules), "productos": 0, "platos": 0}
    sources = {"catalog_item": """SELECT ci.master_product_id::text, ci.name, c.name, ci.description, ci.attributes
                                  FROM catalog_items ci LEFT JOIN categories c USING (category_id)""",
               "menu_item": "SELECT item_id::text, name, NULL, description, NULL FROM menu_items"}  # fmt: skip
    for entity_type, sql in sources.items():
        rows = conn.execute(sql).fetchall()  # antes del COPY: la conexión no admite otra consulta mientras copia
        with conn.cursor().copy(f"COPY item_attributes ({_COLUMNS}) FROM STDIN") as copy:
            for item_id, name, category, description, rappi in rows:
                found = detect_attributes(
                    entity_type, name or "", category, description, rappi, rules, groups.get((entity_type, item_id))
                )
                counts["productos" if entity_type == "catalog_item" else "platos"] += bool(found)
                for d in found:
                    if (entity_type, item_id, d.attribute_id) not in curated:
                        copy.write_row(
                            (entity_type, item_id, d.attribute_id, d.value, d.source, d.confidence, d.evidence,
                             version, run)
                        )  # fmt: skip
    params = {"conf": DERIVED_CONFIDENCE, "version": version, "run": run, "min_items": MIN_CONCEPT_ITEMS_FOR_PRICE}
    counts["derivados"] = sum(
        conn.execute(sql, params).rowcount for sql in (_DISCOUNTED, _CHEAP, _FROM_MEASURES, _STORE_BRAND)
    )
    conn.execute("ANALYZE item_attributes")
    finish_layer_run(conn, run, counts)
    log.info("Atributos: %s", counts)
    return counts
