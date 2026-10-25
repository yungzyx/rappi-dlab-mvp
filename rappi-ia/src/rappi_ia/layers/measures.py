"""Medidas normalizadas de cada ítem: cantidad por unidad, unidad base (g, ml, und, cm), pack y total.

Base: `catalog_items.quantity` y `unit_type` (Rappi, normalizados a g/ml/und/cm). El nombre las corrige cuando Rappi
dice «1 und» pero el nombre trae «3 L». Para los platos solo se extrae una etiqueta de tamaño («familiar», «para 2»).
"""

import logging
import re
from dataclasses import dataclass, replace
from pathlib import Path

from psycopg import Connection

from ..text import normalize
from .runs import finish_layer_run, rules_version, start_layer_run

log = logging.getLogger(__name__)

RULES_VERSION = "2026-10-06"

# (unidad de Rappi o del nombre) → (unidad base, factor)
_UNITS = {
    "g": ("g", 1.0), "gr": ("g", 1.0), "grs": ("g", 1.0), "gramo": ("g", 1.0), "gramos": ("g", 1.0),
    "kg": ("g", 1000.0), "kilo": ("g", 1000.0), "kilos": ("g", 1000.0),
    "mg": ("g", 0.001), "mcg": ("g", 0.000001), "lb": ("g", 453.592), "oz": ("g", 28.3495),
    "ml": ("ml", 1.0), "cc": ("ml", 1.0), "l": ("ml", 1000.0), "lt": ("ml", 1000.0), "lts": ("ml", 1000.0),
    "litro": ("ml", 1000.0), "litros": ("ml", 1000.0),
    "cm": ("cm", 1.0), "mt": ("cm", 100.0), "mm": ("cm", 0.1),
    "und": ("und", 1.0),
}  # fmt: skip
# Del nombre solo se leen peso y volumen (mg, lb o mm en un nombre suelen ser dosis o medidas de otra cosa).
NAME_MEASURE = re.compile(
    r"(?<![\w.,\-+/])(\d+(?:[.,]\d+)?)\s*(kg|kilos?|grs?|gr|g|gramos?|ml|cc|lts?|l|litros?)(?![\w/])", re.IGNORECASE
)
_THOUSANDS = re.compile(r"^\d{1,3}\.\d{3}$")
_PACK_WORDS = {"six": 6, "doce": 12, "tres": 3}
_NAME_PACK = [
    # «6 x 350 ml» sí; «70 x 50 cm» o «12x15cm» son dimensiones, no un pack de 70 o de 12
    re.compile(
        r"\b(\d{1,2})\s*x\s*\d++(?:[.,]\d++)?+\s*+(?:ml|cc|lts?|l|gr?s?|kg|oz|und|unid\w*|un|pzs?|piezas)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(\d+)\s*-?\s*pack\b", re.IGNORECASE),
    re.compile(r"\bpack\s*(?:de\s*)?(\d+)\b", re.IGNORECASE),
    re.compile(r"\b(six|doce|tres)\s*pack\b", re.IGNORECASE),
]
_PRESENTATION_PACK = re.compile(r"^\s*(\d+)\s*x\s*\d", re.IGNORECASE)
_PACK_SIZE = re.compile(r"^x(\d+)$", re.IGNORECASE)
# Medidas que casi seguro son un error de carga de Rappi («Almendra Tostada: 1 mg», «Mix Frutas: 44.682 kg»)
MAX_PLAUSIBLE = {"g": 100_000, "ml": 100_000, "und": 1_000}
MIN_PLAUSIBLE_G = 0.001
MAX_UND_AS_PACK = 24  # «4Und» en un producto con medida en el nombre: 4 envases; más que esto es un conteo de dosis


@dataclass(frozen=True)
class Measure:
    quantity: float | None
    unit: str | None
    pack: int
    total: float | None
    size_label: str | None
    source: str
    evidence: str
    suspect: str | None = None


def _to_base(quantity: float | None, unit: str | None) -> tuple[float | None, str | None]:
    if quantity is None:
        return None, None
    base = _UNITS.get((unit or "und").strip().lower())
    if base is None:
        return None, None
    return round(quantity * base[1], 6), base[0]


_RANGE_BEFORE = re.compile(r"\d\s*(?:a|-|–|al)\s*$")


def _name_measure(name: str) -> tuple[float, str, str, str] | None:
    """(cantidad, unidad base, texto que la dijo, unidad escrita) de la primera medida de peso o volumen del nombre."""
    for match in NAME_MEASURE.finditer(name):
        before = name[: match.start()].lower().rstrip()
        if before.endswith(("hasta", "talla")) or _RANGE_BEFORE.search(before):
            continue  # «hasta 15 kg», «3.5 a 7 kg»: son pesos de uso del producto, no su contenido
        digits, unit = match.group(1), match.group(2)
        if _THOUSANDS.match(digits) and unit.lower() in ("ml", "cc", "g", "gr", "grs"):
            value = float(digits.replace(".", ""))
        else:
            value = float(digits.replace(",", "."))
        quantity, base = _to_base(value, unit)
        if quantity and quantity <= MAX_PLAUSIBLE[base]:  # «600 L» de una tetera o «3028 L» de un filtro: no es tamaño
            return quantity, base, match.group(0).strip(), unit
    return None


def _pack(name: str, pack_size: str | None, presentation: str | None) -> int:
    if presentation and (m := _PRESENTATION_PACK.match(presentation)) and int(m.group(1)) > 1:
        return int(m.group(1))
    if pack_size and (m := _PACK_SIZE.match(pack_size.strip())) and int(m.group(1)) > 1:
        return int(m.group(1))
    for pattern in _NAME_PACK:
        if m := pattern.search(name):
            token = m.group(1).lower()
            value = _PACK_WORDS.get(token) or int(token)
            if 1 < value <= MAX_UND_AS_PACK:  # «N°312 Pack 6» o «Doy Pack 500 Gr»: el número grande no es el pack
                return value
    return 1


def _suspect(m: Measure) -> Measure:
    reason = None
    if m.total is not None and m.unit in MAX_PLAUSIBLE and m.total > MAX_PLAUSIBLE[m.unit]:
        reason = f"más de {MAX_PLAUSIBLE[m.unit]:,} {m.unit}".replace(",", ".")
    elif m.total is not None and m.unit == "g" and m.total <= MIN_PLAUSIBLE_G:
        reason = "un miligramo o menos"
    return replace(m, suspect=reason) if reason else m


def _implausible(rappi_qty: float | None, name_qty: float) -> bool:
    """El valor de Rappi es un relleno («1 g» de una yerba de 500 g) o un absurdo (1000 L de un vino)."""
    if not rappi_qty:
        return True
    return (rappi_qty == 1 and name_qty > 1) or max(rappi_qty, name_qty) / min(rappi_qty, name_qty) >= 50


def _parse_measure(
    name: str,
    quantity: float | None,
    unit_type: str | None,
    pack_size: str | None,
    presentation: str | None = None,
) -> Measure:
    pack = _pack(name, pack_size, presentation)
    if quantity is not None and quantity <= 0:  # «0 Und» y «0 cm» de Rappi: no es una medida
        quantity = None
    rappi_qty, rappi_unit = _to_base(quantity, unit_type or ("und" if quantity is not None else None))
    from_name = _name_measure(name)
    if from_name and from_name[3].lower() == "g" and from_name[0] < 10 and rappi_unit == "und":
        from_name = None  # «Honor 400 Pro 5g» es la red 5G, no cinco gramos
    # El nombre corrige a Rappi cuando éste dice «und», una dimensión distinta («Coca-Cola 3 L» con 1 und) o, en la
    # misma dimensión, un valor de relleno o absurdo.
    if from_name and (
        rappi_unit in (None, "und") or rappi_unit != from_name[1] or _implausible(rappi_qty, from_name[0])
    ):
        name_qty, name_unit, text, _written = from_name
        if rappi_unit == "und" and rappi_qty and 1 < rappi_qty <= MAX_UND_AS_PACK and pack == 1:
            pack = int(rappi_qty)  # «Shampoo 1 L» con 4Und: cuatro envases
        return Measure(name_qty, name_unit, pack, round(name_qty * pack, 6), None, "regla", text)
    if rappi_unit == "und" and rappi_qty == pack:  # «Pack 50» con 50Und: el pack ya es la cantidad
        pack = 1
    if rappi_qty is None:
        return Measure(None, None, pack, None, None, "rappi", "")
    return Measure(rappi_qty, rappi_unit, pack, round(rappi_qty * pack, 6), None, "rappi", f"{quantity:g} {unit_type}")


def parse_measure(
    name: str,
    quantity: float | None,
    unit_type: str | None,
    pack_size: str | None,
    presentation: str | None = None,
) -> Measure:
    return _suspect(_parse_measure(name, quantity, unit_type, pack_size, presentation))


_DISH_SIZES = [
    (re.compile(r"\bpara\s+(\d+)\b"), lambda m: f"para {m.group(1)}"),
    (re.compile(r"\b(\d+)\s+personas?\b"), lambda m: f"para {m.group(1)}"),
    (re.compile(r"\bfamiliar\b"), lambda m: "familiar"),
    (re.compile(r"\bxxl\b"), lambda m: "xxl"),
    (re.compile(r"\bxl\b"), lambda m: "xl"),
    (re.compile(r"\bindividual\b"), lambda m: "individual"),
    (re.compile(r"\bgrande\b"), lambda m: "grande"),
    (re.compile(r"\bmedian[oa]\b"), lambda m: "mediano"),
    (re.compile(r"\bchic[oa]\b|\bjunior\b"), lambda m: "chico"),
]


def parse_dish_size(name: str) -> str | None:
    said = normalize(name)
    for pattern, label in _DISH_SIZES:
        if m := pattern.search(said):
            size = label(m)
            return "individual" if size == "para 1" else size  # una persona no es «para compartir»
    return None


def build_measures(conn: Connection) -> dict:
    """Recalcula `item_measures` de todos los productos y platos (idempotente)."""
    run = start_layer_run(conn, "measures", rules_version(RULES_VERSION, Path(__file__)))
    rows = conn.execute(
        """SELECT master_product_id::text, name, quantity::float, unit_type, presentation, attributes->>'pack_size'
           FROM catalog_items"""
    ).fetchall()
    out, fixed = [], 0
    for item_id, name, quantity, unit_type, presentation, pack_size in rows:
        m = parse_measure(name or "", quantity, unit_type, pack_size, presentation)
        fixed += m.source == "regla"
        out.append(
            ("catalog_item", item_id, m.quantity, m.unit, m.pack, m.total, None, m.suspect, m.source, m.evidence, run)
        )
    dishes = 0
    for item_id, name in conn.execute("SELECT item_id::text, name FROM menu_items").fetchall():
        label = parse_dish_size(name or "")
        if label:
            dishes += 1
            out.append(("menu_item", item_id, None, None, 1, None, label, None, "regla", label, run))
    conn.execute("DELETE FROM item_measures")
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO item_measures (entity_type, entity_id, quantity, unit, pack, total, size_label, suspect,
                                          source, evidence, run_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            out,
        )
    suspects = sum(1 for o in out if o[7])
    conn.execute("ANALYZE item_measures")  # sin estadísticas, las vistas de `capa` tardan minutos en un plan malo
    counts = {"productos": len(rows), "platos": dishes, "corregidos": fixed, "sospechosas": suspects}
    finish_layer_run(conn, run, counts)
    log.info("Medidas: %s", counts)
    return counts
