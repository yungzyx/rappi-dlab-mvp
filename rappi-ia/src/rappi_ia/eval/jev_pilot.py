"""Piloto de Jev: mide los dos roles contra las planillas juzgadas a mano y propone (o no) adoptarlos.

- Rol A (categorías): Jev etiqueta las categorías de `planilla-categorias.csv` con las instrucciones en español y en
  inglés (mismas opciones). Para cada umbral T de `THRESHOLDS`, con la tabla de decisión de `jev_map.decide`:
  - precisión: de las categorías que Jev mapea (confianza ≥ T), las que coinciden con el concepto de la persona
    (si la persona puso «ninguno», mapear es un error);
  - cobertura: de las categorías del grupo «sin mapear», las que Jev mapea;
  - acuerdo con el control: de las categorías del grupo «acuerdo» que Jev mapea, las que coinciden con el concepto en
    que ya coincidían los dos mapeadores;
  - sensibles: categorías que la persona dio por sensibles o +18 y Jev mapea solo a un concepto que no lo es.
  `T_auto` es el menor T que cumple los cuatro criterios; una variante pasa si tiene `T_auto`.
- Rol B (juez): Jev juzga los pares de `planilla-busqueda.csv` (con caché en `eval_judgments`). κ binario «sirve»
  contra el resto, como el juez por concepto: Jev dice «sirve» con ganancia esperada ≥ ¾ (`jev_level`). Se adopta si
  κ(Jev, personas) ≥ 0,6 y supera a κ(juez por concepto, personas) en los mismos pares. El κ ponderado de tres
  niveles se informa, no decide.

Escribe `data/eval/jev-piloto.md` y `eval/jev-adopcion.propuesta.json`. La propuesta no adopta nada: la persona la
renombra a `jev-adopcion.json` y la sube a git.
"""

import json
import math
from collections import Counter
from datetime import date
from pathlib import Path

from psycopg import Connection

from .. import config
from ..concepts.jev_map import build_questions, decide
from ..concepts.taxonomy import Taxonomy
from ..jev import ADOPTION_FILE, DEFAULT_T_AUTO, VARIANTS
from . import sheets
from .judge import JevJudgment, judge_pairs
from .judgments import sheet_report

THRESHOLDS = tuple(round(0.6 + 0.05 * i, 2) for i in range(8))  # 0,60 … 0,95
MIN_PRECISION = 0.9
MIN_COVERAGE = 0.5
MIN_CONTROL = 0.9
MIN_KAPPA = 0.6
MIN_JUDGED = 0.9  # de cada planilla, lo mínimo juzgado por la persona para correr el piloto
MIN_ANSWERED = 0.9  # de lo que se le pidió, lo mínimo que Jev debe responder para que las cifras valgan
REPORT_NAME = "jev-piloto.md"
PROPOSAL_FILE = ADOPTION_FILE.with_name("jev-adopcion.propuesta.json")
VARIANT_NAMES = {"es": "español", "en": "inglés"}


# --- requisitos y lectura --------------------------------------------------------------------------------------------


def requirements(
    has_key: bool, sheet_dir: Path | None = None, ids_dir: Path | None = None
) -> tuple[list[str], list[str]]:
    """(lo que impide correr el piloto, avisos), en palabras de la persona. Basta con `MIN_JUDGED` de cada planilla
    juzgada: lo que falte se avisa y las cifras usan lo juzgado."""
    sheet_dir, ids_dir = sheet_dir or sheets.sheet_dir(), ids_dir or sheets.EVAL_DIR
    blocking = [] if has_key else ["la clave de Jev: TYPESAFE_API_KEY en rappi-ia/.env"]
    warnings = []
    for sheet, ids_file, read in (
        (sheets.CATEGORY_SHEET, sheets.CATEGORY_IDS_FILE.name, _category_judgments),
        (sheets.SEARCH_SHEET, sheets.SEARCH_IDS_FILE.name, _search_judgments),
    ):
        if not (ids_dir / ids_file).exists() or not (sheet_dir / sheet).exists():
            blocking.append(f"{sheet} juzgada: genera las planillas con `rappi-ia jev-planillas` y llénalas")
            continue
        if ids_file == sheets.SEARCH_IDS_FILE.name and not _has_entities(ids_dir / ids_file):
            blocking.append(
                f"{ids_file} es de una versión anterior (sin entity_type ni entity_id): regenera las planillas con"
                " `rappi-ia jev-planillas`"
            )
            continue
        counts: Counter = Counter()
        keys, judged = read(sheet_dir, ids_dir, counts)
        left = sum(key not in judged for key in keys)
        need = math.ceil(MIN_JUDGED * len(keys))
        if len(keys) - left < need:
            blocking.append(
                f"{sheet}: faltan {left} de {len(keys)} por juzgar ({counts['vacias']} vacías,"
                f" {counts['invalidas']} inválidas); el piloto necesita al menos {need} de {len(keys)} juzgadas"
            )
        elif left:
            warnings.append(f"{sheet}: faltaron {left} de {len(keys)} por juzgar; las cifras usan las juzgadas")
    return blocking, warnings


def _has_entities(path: Path) -> bool:
    return all("entity_type" in pair and "entity_id" in pair for pair in _ids(path, "pares"))


def _category_judgments(sheet_dir: Path, ids_dir: Path, counts: Counter) -> tuple[list[str], dict[str, str]]:
    keys = [row["clave"] for row in _ids(ids_dir / sheets.CATEGORY_IDS_FILE.name, "categorias")]
    return keys, sheets.read_category_sheet(sheet_dir / sheets.CATEGORY_SHEET, counts)


def _search_judgments(sheet_dir: Path, ids_dir: Path, counts: Counter) -> tuple[list[str], dict[str, int]]:
    keys = [row["id"] for row in _ids(ids_dir / sheets.SEARCH_IDS_FILE.name, "pares")]
    return keys, sheets.read_search_sheet(sheet_dir / sheets.SEARCH_SHEET, counts)


def _ids(path: Path, key: str) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))[key]


def load_category_rows(sheet_dir: Path, ids_dir: Path) -> list[dict]:
    """Una fila por categoría de la planilla: su grupo, el concepto de control, el de la persona (o None) y el estado
    que ve Jev, armado con lo mismo que vio la persona (vertical, nombre y ejemplos de la planilla)."""
    path = sheet_dir / sheets.CATEGORY_SHEET
    human = sheets.read_category_sheet(path)
    texts = {row.get("categoria", "").strip().lower(): row for row in sheets.read_table(path)}
    rows = []
    for entry in _ids(ids_dir / sheets.CATEGORY_IDS_FILE.name, "categorias"):
        text = texts.get(entry["clave"])
        if text is None:
            continue
        examples = [e.strip() for e in text.get("ejemplos", "").split(" | ") if e.strip()]
        rows.append(
            {
                "clave": entry["clave"],
                "grupo": entry["grupo"],
                "control": entry["concepto_propuesto"] or None,
                "humano": human.get(entry["clave"]),
                "state": {"vertical": text.get("vertical", ""), "categoria": text["categoria"], "ejemplos": examples},
            }
        )
    return rows


def load_search_pairs(sheet_dir: Path, ids_dir: Path) -> tuple[list[dict], dict[str, int]]:
    """Los pares de la planilla con lo que `judge_pairs` necesita (de los ids versionados y del texto de la planilla)
    y el nivel que les dio la persona."""
    path = sheet_dir / sheets.SEARCH_SHEET
    human = sheets.read_search_sheet(path)
    texts = {row.get("id", "").strip(): row for row in sheets.read_table(path)}
    pairs = [
        {
            **entry,
            "nombre": texts.get(entry["id"], {}).get("nombre", ""),
            "tienda": texts.get(entry["id"], {}).get("tienda", ""),
        }
        for entry in _ids(ids_dir / sheets.SEARCH_IDS_FILE.name, "pares")
    ]
    return pairs, human


# --- rol A: categorías -----------------------------------------------------------------------------------------------


def category_metrics(rows: list[dict], answers: list, taxonomy: Taxonomy, t: float) -> dict:
    """Las cuatro cifras del rol A con el umbral `t` (una respuesta None, que Jev no dio, cuenta como no mapeada)."""
    mapped = {}
    for row, answer in zip(rows, answers, strict=True):
        if answer is not None and (decision := decide(answer, taxonomy, t)).kind == "mapear":
            mapped[row["clave"]] = decision.concept_id
    judged = [r for r in rows if r["clave"] in mapped and r["humano"]]
    unmapped = [r for r in rows if r["grupo"] == "sin_mapear"]
    control = [r for r in rows if r["grupo"] == "acuerdo" and r["clave"] in mapped and r["control"]]
    return {
        "t": t,
        "mapeadas": len(mapped),
        "precision": _share([mapped[r["clave"]] == r["humano"] for r in judged]),
        "cobertura": _share([r["clave"] in mapped for r in unmapped]),
        "control": _share([mapped[r["clave"]] == r["control"] for r in control]),
        "control_n": len(control),
        "sensibles": sum(_breach(taxonomy, r["humano"], mapped[r["clave"]]) for r in judged),
    }


def _share(hits: list[bool]) -> float | None:
    return sum(hits) / len(hits) if hits else None


def _breach(taxonomy: Taxonomy, human: str, mapped: str) -> bool:
    """La persona dio la categoría por sensible o +18 y Jev la mapeó a un concepto que no lo es."""
    truth, given = taxonomy.concepts.get(human), taxonomy.concepts[mapped]
    if truth is None:  # «ninguno»: no se sabe qué guardia aplicaría
        return False
    return (truth.sensitive and not given.sensitive) or (truth.age_restricted and not given.age_restricted)


def category_criteria(metrics: dict) -> dict[str, bool]:
    def at_least(value, target):
        return value is not None and value >= target

    return {
        "precision": at_least(metrics["precision"], MIN_PRECISION),
        "cobertura": at_least(metrics["cobertura"], MIN_COVERAGE),
        "control": at_least(metrics["control"], MIN_CONTROL),
        "sensibles": metrics["sensibles"] == 0,
    }


def evaluate_variant(rows: list[dict], answers: list, taxonomy: Taxonomy) -> dict:
    """Las cifras en cada umbral y `t_auto`, el menor que cumple los cuatro criterios (None si ninguno)."""
    by_threshold = [category_metrics(rows, answers, taxonomy, t) for t in THRESHOLDS]
    passing = [m["t"] for m in by_threshold if all(category_criteria(m).values())]
    return {
        "umbrales": by_threshold,
        "t_auto": passing[0] if passing else None,
        "sin_respuesta": sum(a is None for a in answers),
    }


def choose_variant(results: dict[str, dict]) -> str | None:
    """De las variantes que pasan, la de más cobertura en su `T_auto` (luego más precisión; si empatan, el español)."""

    def at_t_auto(variant):
        result = results[variant]
        metrics = next(m for m in result["umbrales"] if m["t"] == result["t_auto"])
        return (metrics["cobertura"], metrics["precision"])

    passing = [v for v in VARIANTS if v in results and results[v]["t_auto"] is not None]
    return max(passing, key=at_t_auto) if passing else None


# --- rol B: juez -----------------------------------------------------------------------------------------------------


def jev_level(gain: float) -> int:
    """Nivel 0, 1 o 2 desde la ganancia esperada: el más cercano (½ y 1 son las ganancias de «a medias» y «sirve»).
    Jev dice «sirve» (nivel 2) con ganancia ≥ ¾, el punto medio entre las dos. `RELEVANT_GAIN` (½) es otro corte: el
    del MRR, que cuenta «a medias» como relevante; aquí el binario de las personas es «sirve» contra el resto."""
    return min(2, int(gain * 2 + 0.5))


def judge_kappas(pairs: list[dict], human: dict[str, int], judgments: dict[str, JevJudgment]) -> dict:
    """κ de Jev y del juez por concepto contra las personas, en los mismos pares (los que ambos, Jev y la persona,
    juzgaron)."""
    rows = [p for p in pairs if p["id"] in human and p["id"] in judgments]
    result = {
        "n": len(rows),
        "sin_juicio_jev": sum(p["id"] in human and p["id"] not in judgments for p in pairs),
        "kappa_jev": None,
        "kappa_ponderado_jev": None,
        "kappa_concepto": None,
        "kappa_ponderado_concepto": None,
    }
    if not rows:
        return result
    people = [human[p["id"]] for p in rows]
    jev = [jev_level(judgments[p["id"]].gain) for p in rows]
    concept = sheet_report(rows, human)
    return result | {
        "kappa_jev": round(sheets.cohen_kappa([int(h == 2) for h in people], [int(j == 2) for j in jev]), 3),
        "kappa_ponderado_jev": round(sheets.weighted_kappa(people, jev), 3),
        "kappa_concepto": concept["kappa"],
        "kappa_ponderado_concepto": concept["kappa_ponderado"],
    }


def judge_criteria(kappas: dict) -> dict[str, bool]:
    jev, concept = kappas["kappa_jev"], kappas["kappa_concepto"]
    return {
        "kappa_minimo": jev is not None and jev >= MIN_KAPPA,
        "mejor_que_concepto": jev is not None and concept is not None and jev > concept,
    }


# --- corrida ---------------------------------------------------------------------------------------------------------


def estimated_cost(input_tokens: int, price_per_million: float) -> float:
    return input_tokens * price_per_million / 1_000_000


def run_pilot(
    conn: Connection,
    client,
    taxonomy: Taxonomy,
    sheet_dir: Path | None = None,
    ids_dir: Path | None = None,
    proposal_path: Path | None = None,
    today: date | None = None,
) -> dict:
    """Corre los dos roles, escribe el reporte y la propuesta y devuelve las cifras. Supone que `requirements` no
    bloquea; sus avisos van al reporte. Si se llegó al tope de llamadas o Jev respondió menos de `MIN_ANSWERED` de lo
    pedido, las cifras no valen y la propuesta no adopta nada. Guarda los juicios nuevos en `eval_judgments`; no hace
    commit."""
    sheet_dir, ids_dir = sheet_dir or sheets.sheet_dir(), ids_dir or sheets.EVAL_DIR
    proposal_path = proposal_path or PROPOSAL_FILE
    today = today or date.today()
    _, warnings = requirements(True, sheet_dir, ids_dir)

    rows = load_category_rows(sheet_dir, ids_dir)
    variants = {}
    for variant in VARIANTS:
        questions = build_questions(taxonomy, variant)
        answers = client.ask_many([(row["state"], questions) for row in rows])
        variants[variant] = evaluate_variant(rows, answers, taxonomy)
    chosen = choose_variant(variants)
    categories = {
        "filas": len(rows),
        "grupos": dict(Counter(r["grupo"] for r in rows)),
        "variantes": variants,
        "variante": chosen,
        "t_auto": variants[chosen]["t_auto"] if chosen else None,
        "pasa": chosen is not None,
    }

    pairs, human = load_search_pairs(sheet_dir, ids_dir)
    asked = [p for p in pairs if p["id"] in human]  # lo que la persona no juzgó no sirve para el κ: no se paga
    judgments = judge_pairs(conn, client, asked)
    kappas = judge_kappas(asked, human, judgments)
    judge = kappas | {"criterios": judge_criteria(kappas)}
    judge["pasa"] = all(judge["criterios"].values())

    stats = client.stats
    usage = {
        "llamadas": stats.requests,
        "tokens": stats.input_tokens,
        "fallos": stats.failures,
        "tope": stats.stopped_by_cap,
        "precio": config.JEV_PRICE_PER_MTOK_INPUT,
        "costo": estimated_cost(stats.input_tokens, config.JEV_PRICE_PER_MTOK_INPUT),
    }
    unreliable = _unreliable(usage, categories, len(asked) - kappas["sin_juicio_jev"], len(asked))
    proposal = {
        "categorias": categories["pasa"] and not unreliable,
        "juez": judge["pasa"] and not unreliable,
        "t_auto": categories["t_auto"] or DEFAULT_T_AUTO,
        "variante": chosen or VARIANTS[0],
        "model_version": client.model,
        "fecha": today.isoformat(),
    }
    sheets.write_json(proposal_path, proposal)
    report_path = sheet_dir / REPORT_NAME
    context = {
        "modelo": client.model,
        "fecha": today,
        "archivo_propuesta": proposal_path.name,
        "propuesta": proposal,
        "avisos": warnings,
        "no_confiable": unreliable,
    }
    report_path.write_text(render_report(categories, judge, usage, context), encoding="utf-8")
    return {
        "categorias": categories,
        "juez": judge,
        "uso": usage,
        "propuesta": proposal,
        "avisos": warnings,
        "no_confiable": unreliable,
        "reporte": report_path,
        "archivo_propuesta": proposal_path,
    }


def _unreliable(usage: dict, categories: dict, judged: int, asked: int) -> list[str]:
    """Por qué las cifras no valen para adoptar (vacío si valen)."""
    reasons = []
    if usage["tope"]:
        reasons.append("se llegó al tope de llamadas (`JEV_MAX_REQUESTS`) y faltaron respuestas")
    total = categories["filas"]
    for variant, result in categories["variantes"].items():
        answered = total - result["sin_respuesta"]
        if total and answered < MIN_ANSWERED * total:
            reasons.append(f"en la variante «{variant}», Jev respondió {answered} de {total} categorías")
    if asked and judged < MIN_ANSWERED * asked:
        reasons.append(f"Jev respondió {judged} de {asked} pares de búsqueda")
    return reasons


# --- reporte ---------------------------------------------------------------------------------------------------------


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.0f} %"


def fmt_num(value: float | None, decimals: int = 2) -> str:
    return "—" if value is None else f"{value:.{decimals}f}".replace(".", ",")


def fmt_int(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _ok(passed: bool) -> str:
    return "cumple" if passed else "no cumple"


def render_report(categories: dict, judge: dict, usage: dict, context: dict) -> str:
    groups = categories["grupos"]
    proposal = context["propuesta"]
    adopt = proposal["categorias"] or proposal["juez"]
    lines = [
        f"# Piloto de Jev ({context['fecha'].isoformat()})",
        "",
        "## Resultado",
        "",
        f"- Categorías: {'sí' if proposal['categorias'] else 'no'}"
        + (
            f" (instrucciones en {VARIANT_NAMES[proposal['variante']]}, T_auto = {fmt_num(proposal['t_auto'])})"
            if proposal["categorias"]
            else ""
        ),
        f"- Juez: {'sí' if proposal['juez'] else 'no'}",
        "",
        "Siguiente paso: "
        + (
            f"para adoptar, renombra eval/{context['archivo_propuesta']} a eval/jev-adopcion.json y súbelo a git"
            " (en `rappi-ia/src/rappi_ia/`)."
            if adopt
            else "no se adopta: todo sigue igual sin Jev."
        ),
    ]
    if context["no_confiable"]:
        lines += ["", "**Las cifras no valen para adoptar, aunque pasen los criterios:**"]
        lines += [f"- {reason}" for reason in context["no_confiable"]]
    if context["avisos"]:
        lines += ["", "Avisos:"] + [f"- {warning}" for warning in context["avisos"]]
    lines += [
        "",
        f"Modelo `{context['modelo']}`. {fmt_int(usage['llamadas'])} llamadas, {fmt_int(usage['tokens'])} tokens de"
        f" entrada; costo estimado US$ {fmt_num(usage['costo'], 4)} (a US$ {fmt_num(usage['precio'], 3)} por millón de"
        " tokens de entrada, `JEV_PRICE_PER_MTOK_INPUT`; la salida no se cobra). Los pares ya juzgados salen de la"
        " caché y no se cobran de nuevo.",
        "",
        "## Glosario",
        "",
        "- **κ (kappa de Cohen)**: cuánto coinciden dos jueces más allá de lo que coincidirían por azar. 0 = lo del"
        " azar, 0,6 = bueno, 1 = acuerdo total.",
        "- **T_auto**: la confianza mínima con que Jev etiqueta una categoría sola, sin que una persona la revise.",
        "- **Ganancia esperada**: el puntaje de Jev para un resultado de búsqueda, de 0 (no sirve) a 1 (sirve),"
        " promediando sus probabilidades de «no sirve» (0), «a medias» (½) y «sirve» (1).",
        "- **Guardias**: dos preguntas aparte (¿es de salud sensible?, ¿es solo para mayores de 18?) que mandan a"
        " revisión humana una categoría cuando contradicen el concepto que eligió Jev.",
    ]
    lines += [
        "",
        "## Rol A: etiquetar categorías",
        "",
        f"Planilla A: {categories['filas']} categorías ({groups.get('sin_mapear', 0)} sin mapear,"
        f" {groups.get('juez', 0)} decididas por el juez, {groups.get('acuerdo', 0)} de control). Con cada umbral T,"
        " Jev mapea las categorías con confianza ≥ T que pasan la tabla de decisión (sin mezcla ni guardias en"
        " conflicto). Precisión: mapeadas que coinciden con la persona. Cobertura: sin mapear que Jev mapea. Control:"
        " mapeadas del grupo de control que coinciden con el concepto de control. Sensibles: categorías sensibles o +18"
        " (según la persona) que Jev mapea solo a un concepto que no lo es.",
    ]
    for variant, result in categories["variantes"].items():
        lines += [
            "",
            f"### Instrucciones en {VARIANT_NAMES[variant]} (variante «{variant}»)",
            "",
            "| T | Mapeadas | Precisión | Cobertura sin mapear | Acuerdo control | Sensibles mal mapeadas | Cumple |",
            "|---|---|---|---|---|---|---|",
        ]
        for m in result["umbrales"]:
            control = f"{_pct(m['control'])} (n={m['control_n']})"
            lines.append(
                f"| {fmt_num(m['t'])} | {m['mapeadas']} | {_pct(m['precision'])} | {_pct(m['cobertura'])} | {control}"
                f" | {m['sensibles']} | {'sí' if all(category_criteria(m).values()) else 'no'} |"
            )
        lines.append("")
        if result["sin_respuesta"]:
            lines.append(f"Jev no respondió {result['sin_respuesta']} categorías (cuentan como no mapeadas).")
        lines.append(
            f"T_auto = {fmt_num(result['t_auto'])}"
            if result["t_auto"]
            else "Ningún umbral cumple los cuatro criterios."
        )
    lines += ["", "### Criterios de adopción del rol A", ""]
    lines += _category_criteria_table(categories)
    lines.append("")
    if categories["pasa"]:
        lines.append(
            f"Cumple los criterios con la variante «{categories['variante']}» y T_auto ="
            f" {fmt_num(categories['t_auto'])}."
        )
    else:
        lines.append("No se propone adoptar el rol A: ninguna variante cumple los cuatro criterios en un mismo umbral.")

    criteria = judge["criterios"]
    lines += [
        "",
        "## Rol B: juez de la búsqueda",
        "",
        f"{judge['n']} pares juzgados por la persona y por Jev"
        + (f" ({judge['sin_juicio_jev']} quedaron sin juicio de Jev)" if judge["sin_juicio_jev"] else "")
        + ". Jev dice «sirve» con ganancia esperada ≥ 0,75; κ binario: «sirve» contra el resto.",
        "",
        "| Juez | κ binario | κ ponderado (3 niveles) |",
        "|---|---|---|",
        f"| Jev | {fmt_num(judge['kappa_jev'], 3)} | {fmt_num(judge['kappa_ponderado_jev'], 3)} |",
        f"| Juez por concepto | {fmt_num(judge['kappa_concepto'], 3)}"
        f" | {fmt_num(judge['kappa_ponderado_concepto'], 3)} |",
        "",
        "| Criterio | Meta | Resultado |",
        "|---|---|---|",
        f"| κ Jev | ≥ {fmt_num(MIN_KAPPA, 1)} | {_ok(criteria['kappa_minimo'])} |",
        f"| κ Jev > κ juez por concepto | mayor | {_ok(criteria['mejor_que_concepto'])} |",
        "",
        "Cumple los criterios: Jev coincide con las personas mejor que el juez por concepto."
        if judge["pasa"]
        else "No se propone adoptar a Jev como juez: el juez por concepto sigue solo.",
        "",
        "## Propuesta",
        "",
        f"Queda en `rappi-ia/src/rappi_ia/eval/{context['archivo_propuesta']}`. No adopta nada por sí sola: para"
        " adoptar, renómbrala a"
        " `jev-adopcion.json` y súbela a git. Mientras no exista ese archivo, Jev queda apagado.",
        "",
    ]
    return "\n".join(lines)


def _category_criteria_table(categories: dict) -> list[str]:
    """Una columna por variante, con las cifras en su T_auto o, si no tiene, en el umbral que más criterios cumple."""
    shown = {}
    for variant, result in categories["variantes"].items():
        metrics = result["umbrales"]
        best = next((m for m in metrics if m["t"] == result["t_auto"]), None) or max(
            metrics, key=lambda m: (sum(category_criteria(m).values()), -m["t"])
        )
        shown[variant] = (best, category_criteria(best))
    header = "| Criterio | Meta | " + " | ".join(f"«{v}» (T = {fmt_num(m['t'])})" for v, (m, _) in shown.items()) + " |"
    rows = [header, "|---|---|" + "---|" * len(shown)]
    for name, label, goal, value in (
        ("precision", "Precisión", f"≥ {_pct(MIN_PRECISION)}", lambda m: _pct(m["precision"])),
        ("cobertura", "Cobertura sin mapear", f"≥ {_pct(MIN_COVERAGE)}", lambda m: _pct(m["cobertura"])),
        ("control", "Acuerdo con el control", f"≥ {_pct(MIN_CONTROL)}", lambda m: _pct(m["control"])),
        ("sensibles", "Sensibles mal mapeadas", "0", lambda m: str(m["sensibles"])),
    ):
        cells = [f"{value(m)} ({_ok(ok[name])})" for m, ok in shown.values()]
        rows.append(f"| {label} | {goal} | " + " | ".join(cells) + " |")
    return rows
