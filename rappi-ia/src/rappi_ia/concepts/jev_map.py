"""Rol A de Jev: propone el concepto de las categorías del catálogo que no tienen mapeo revisado.

Una petición por categoría, con 4 preguntas sobre el mismo estado (vertical, nombre y 8 ejemplos): el concepto (una
hoja de la taxonomía o «ninguno»), si los ejemplos mezclan tipos de producto, y dos guardias que se preguntan aparte
—salud sensible y solo para mayores de 18— para detectar cuando el concepto elegido contradice al producto. Jev solo
entrega probabilidades: los umbrales y las guardias los decide `decide`.

Lo que pasa `T_auto` queda en `category_map` con `method = 'jev'` (y `concepts` lo hereda a los productos); lo dudoso
va a `data/concepts/revision-jev.csv`. El CSV versionado no se toca aquí: `map-categories --jev --exportar` deja
ambas cosas en un CSV con su mismo formato, para revisarlas y pasarlas a mano a `category_map.csv`.
"""

import csv
from dataclasses import dataclass
from pathlib import Path

from psycopg import Connection

from .. import config
from ..eval.sheets import category_details
from ..jev import VARIANTS, Choice, Noul
from .report import CATEGORY_MAP_COLUMNS, jev_review_path
from .store import NO_CONCEPT, categories_reviewed_without_concept
from .taxonomy import Concept, Taxonomy

MIX_MAX = 0.5  # desde esta probabilidad de «mezcla», un solo concepto no describe la categoría
GUARD = 0.5  # desde esta probabilidad, la guardia (salud sensible, solo adultos) se considera cierta
REVIEW_MIN = 0.6  # bajo esta confianza no vale la pena ni revisarla

# Categorías con productos que no tienen mapeo revisado (curado o LLM) ni están revisadas sin concepto (filas
# «ninguno» del CSV). Con `only_new`, tampoco las que Jev ya mapeó.
TARGETS = """
SELECT lower(trim(c.name)), count(DISTINCT ci.master_product_id)
FROM categories c JOIN catalog_items ci USING (category_id)
WHERE trim(c.name) <> '' AND lower(trim(c.name)) <> ALL(%(reviewed)s)
  AND NOT EXISTS (SELECT 1 FROM category_map m
                  WHERE m.source_kind = 'categoria' AND m.source_key = lower(trim(c.name))
                    AND (m.method <> 'jev' OR %(only_new)s))
GROUP BY 1 ORDER BY 1
"""


@dataclass(frozen=True)
class Decision:
    kind: str  # 'mapear' | 'revisar' | 'nada'
    concept_id: str | None
    confidence: float
    reason: str


# Las instrucciones de cada pregunta, en dos idiomas con el mismo sentido (la doc de Jev advierte que el español puede
# rendir menos). Las opciones (`criteria`) son las mismas en las dos: solo cambia cómo se pregunta.
INSTRUCTIONS = {
    "es": {
        "concepto": "¿Qué concepto describe los productos de `categoria`? Usa `ejemplos` como evidencia. "
        "Si ninguno calza con la mayoría de los ejemplos, elige «ninguno».",
        "mezcla": "¿`ejemplos` mezcla productos de tipos muy distintos, de modo que un solo concepto no describe la"
        " categoría?",
        "salud_sensible": "¿Los productos son medicamentos, anticonceptivos, pruebas de embarazo o productos de salud o"
        " bienestar sexual?",
        "solo_adultos": "¿Los productos se venden solo a mayores de 18 (alcohol, cigarrillos, vapeo, accesorios para"
        " fumar o juguetes sexuales)?",
    },
    "en": {
        "concepto": "Which concept describes the products in `categoria`? Use `ejemplos` as evidence. "
        "If none fits most of the examples, choose «ninguno».",
        "mezcla": "Does `ejemplos` mix very different kinds of products, so that a single concept does not describe the"
        " category?",
        "salud_sensible": "Are the products medicines, contraceptives, pregnancy tests, or sexual health or wellness"
        " products?",
        "solo_adultos": "Are the products sold only to people over 18 (alcohol, cigarettes, vaping, smoking accessories"
        " or sex toys)?",
    },
}


def build_questions(taxonomy: Taxonomy, variant: str = VARIANTS[0]) -> dict:
    """Las 4 preguntas con las instrucciones en `variant` («es» o «en»)."""
    text = INSTRUCTIONS[variant]
    options = {c.id: {"what": c.name, "examples": list(c.keywords[:5])} for c in taxonomy.concepts.values()}
    options[NO_CONCEPT] = "Ningún concepto describe la mayoría de los ejemplos"
    return {
        "concepto": Choice(text["concepto"], options),
        "mezcla": Noul(text["mezcla"]),
        "salud_sensible": Noul(text["salud_sensible"]),
        "solo_adultos": Noul(text["solo_adultos"]),
    }


def category_state(conn: Connection, category: str) -> dict | None:
    """Lo que Jev ve de una categoría: su vertical, su nombre y los 8 productos que más tiendas venden."""
    key = category.strip().lower()
    details = category_details(conn, [key]).get(key)
    return _state(details) if details else None


def decide(answer: dict, taxonomy: Taxonomy, t_auto: float) -> Decision:
    """Tabla de decisión: «ninguno» o mezcla → nada; guardia en conflicto → revisar (nunca automático);
    confianza ≥ T_auto → mapear; entre 0,6 y T_auto → revisar; menos → nada."""
    chosen = answer["concepto"]
    concept_id = chosen.choice
    confidence = chosen.confidence if chosen.confidence is not None else chosen.probabilities.get(concept_id, 0.0)
    if concept_id == NO_CONCEPT:
        return Decision("nada", None, confidence, "ningún concepto calza")
    concept = taxonomy.concepts.get(concept_id)
    if concept is None:
        return Decision("nada", None, confidence, f"concepto desconocido: {concept_id}")
    if (mix := answer["mezcla"].noul) >= MIX_MAX:
        return Decision("nada", concept_id, confidence, f"mezcla tipos de producto ({mix:.2f})")
    if conflict := _guard_conflict(answer, concept):
        return Decision("revisar", concept_id, confidence, conflict)
    if confidence >= t_auto:
        return Decision("mapear", concept_id, confidence, f"confianza {confidence:.2f} ≥ {t_auto:.2f}")
    if confidence >= REVIEW_MIN:
        return Decision("revisar", concept_id, confidence, f"confianza {confidence:.2f} bajo {t_auto:.2f}")
    return Decision("nada", concept_id, confidence, f"confianza {confidence:.2f} bajo {REVIEW_MIN:.2f}")


def _guard_conflict(answer: dict, concept: Concept) -> str | None:
    """Un concepto +18 pide que la categoría lo parezca, y al revés. Un concepto sensible pide que la categoría
    parezca de salud o, si también es +18 (tabaco, bienestar sexual), solo para adultos; uno no sensible no puede
    recibir una categoría de salud."""
    health = answer["salud_sensible"].noul >= GUARD
    adults = answer["solo_adultos"].noul >= GUARD
    if adults and not concept.age_restricted:
        return f"guardia +18: parece solo para adultos y «{concept.name}» no lo es"
    if concept.age_restricted and not adults:
        return f"guardia +18: «{concept.name}» es solo para adultos y la categoría no lo parece"
    if health and not concept.sensitive:
        return f"guardia de salud: parece de salud sensible y «{concept.name}» no es un concepto sensible"
    if concept.sensitive and not (health or adults):
        return f"guardia de salud: «{concept.name}» es sensible y la categoría no lo parece"
    return None


def map_categories(
    conn: Connection,
    client,
    taxonomy: Taxonomy,
    t_auto: float,
    only_new: bool = False,
    review_path: Path | None = None,
    variant: str = VARIANTS[0],
) -> dict:
    """Pregunta a Jev por cada categoría sin mapeo revisado, aplica `decide` y deja la cola de revisión.

    Sin `only_new` también se vuelven a preguntar las que Jev ya mapeó, y una que ya no pasa deja de estar mapeada.
    Una categoría sin respuesta (falla o tope de llamadas) queda como estaba, también en la cola. `variant` es el
    idioma de las instrucciones con que pasó el piloto. No hace commit."""
    review_path = review_path or jev_review_path()
    targets = dict(
        conn.execute(TARGETS, {"reviewed": categories_reviewed_without_concept(), "only_new": only_new}).fetchall()
    )
    details = category_details(conn, list(targets))
    keys = [key for key in targets if key in details]
    questions = build_questions(taxonomy, variant)
    answers = client.ask_many([(_state(details[key]), questions) for key in keys])
    known = {row[0] for row in conn.execute("SELECT concept_id FROM concepts")}

    decisions: dict[str, tuple[str, int, Decision]] = {}
    failed: set[str] = set()
    for key, answer in zip(keys, answers, strict=True):
        if answer is None:
            failed.add(key)
            continue
        decision = decide(answer, taxonomy, t_auto)
        if decision.kind == "mapear" and decision.concept_id not in known:
            decision = Decision(
                "revisar",
                decision.concept_id,
                decision.confidence,
                f"«{decision.concept_id}» aún no está en la base (falta correr `rappi-ia concepts`)",
            )
        decisions[key] = (details[key]["nombre"], targets[key], decision)
    write_decisions(conn, decisions, client.model)

    kept = [row for row in _read_rows(review_path) if row["nombre"].strip().lower() in failed]
    fresh = [
        _review_row(name, products, decision, client.model, details[key]["ejemplos"])
        for key, (name, products, decision) in decisions.items()
        if decision.kind == "revisar"
    ]
    _write_rows(review_path, sorted(kept + fresh, key=lambda r: (-int(r["productos"]), r["nombre"])))

    kinds = [decision.kind for _, _, decision in decisions.values()]
    return {
        "consultadas": len(keys),
        "mapear": kinds.count("mapear"),
        "revisar": kinds.count("revisar"),
        "nada": kinds.count("nada"),
        "sin_respuesta": len(failed),
    }


def write_decisions(conn: Connection, decisions: dict[str, tuple[str, int, Decision]], model_version: str) -> None:
    """Escribe en category_map lo que se mapea y saca los mapeos de Jev que ya no pasan. Solo toca filas `jev`:
    un mapeo revisado nunca se pisa."""
    for key, (name, _, decision) in decisions.items():
        if decision.kind != "mapear":
            conn.execute(
                "DELETE FROM category_map WHERE source_kind = 'categoria' AND source_key = %s AND method = 'jev'",
                (key,),
            )
            continue
        conn.execute(
            """INSERT INTO category_map (source_kind, source_key, source_name, concept_id, method, confidence,
                                         model_version, note)
               VALUES ('categoria', %s, %s, %s, 'jev', %s, %s, %s)
               ON CONFLICT (source_kind, source_key) DO UPDATE SET
                 source_name = EXCLUDED.source_name, concept_id = EXCLUDED.concept_id,
                 confidence = EXCLUDED.confidence, model_version = EXCLUDED.model_version, note = EXCLUDED.note,
                 valid_from = CASE WHEN category_map.concept_id = EXCLUDED.concept_id
                                   THEN category_map.valid_from ELSE now() END
               WHERE category_map.method = 'jev'""",
            (key, name, decision.concept_id, decision.confidence, model_version, decision.reason),
        )


def export_path() -> Path:
    return config.DATA_DIR / "concepts" / "categorias-jev.csv"


def export_for_review(conn: Connection, review_path: Path | None = None, out_path: Path | None = None) -> int:
    """Los mapeos de Jev (revisión «aplicada») y su cola de revisión («pendiente») en el formato de
    category_map.csv: se revisan, se cambia el método a «curado» y se copian al mapa versionado."""
    rows = [
        {
            "tipo": "categoria",
            "nombre": name,
            "concept_id": concept_id,
            "confianza": f"{confidence:.2f}",
            "metodo": "jev",
            "revision": "aplicada",
            "nota": f"{model_version}: {note}",
            "productos": products,
        }
        for name, concept_id, confidence, model_version, note, products in conn.execute(
            """SELECT m.source_name, m.concept_id, m.confidence, m.model_version, m.note,
                      (SELECT count(DISTINCT ci.master_product_id)
                       FROM catalog_items ci JOIN categories c USING (category_id)
                       WHERE lower(trim(c.name)) = m.source_key)
               FROM category_map m WHERE m.source_kind = 'categoria' AND m.method = 'jev'
               ORDER BY 6 DESC, 1"""
        )
    ]
    rows += _read_rows(review_path or jev_review_path())
    _write_rows(out_path or export_path(), rows)
    return len(rows)


def _state(details: dict) -> dict:
    return {"vertical": details["vertical"], "categoria": details["nombre"], "ejemplos": details["ejemplos"]}


def _review_row(name: str, products: int, decision: Decision, model_version: str, examples: list[str]) -> dict:
    return {
        "tipo": "categoria",
        "nombre": name,
        "concept_id": decision.concept_id,
        "confianza": f"{decision.confidence:.2f}",
        "metodo": "jev",
        "revision": "pendiente",
        "nota": f"{model_version}: {decision.reason}; ejemplos: {' | '.join(examples[:3])}",
        "productos": products,
    }


def _read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CATEGORY_MAP_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
