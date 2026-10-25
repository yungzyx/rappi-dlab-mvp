"""La tabla de combinaciones de verticales de Rappi (`combos.toml`) y el paso siguiente que sugiere.

Una combinación es el conjunto de grupos gruesos (`rest`, `turbo`, `retail`) que una persona usó en un mes. La tabla es
una correlación (quien pide mucho usa más verticales y además vuelve más), así que el motor la toma como punto de
partida: `expected_retention` la mezcla con lo que se aprende de las personas del prototipo cuando hay suficientes.

La combinación fina (`fine_key`) es el conjunto de verticales del catálogo, uno por uno, más los servicios RappiFavor y
RappiTravel. Su retención esperada (`expected_fine_retention`) parte de la gruesa y reduce la parte que no vuelve por
cada vertical extra dentro de un grupo, cada vez menos, y por cada servicio: un supuesto propio
(`[rendimiento_decreciente]` en `combos.toml`) que lo aprendido reemplaza cuando hay suficientes personas.
`next_fine_step` elige el paso con eso.
"""

import tomllib
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from rappi_scraper.storage.search import VERTICALS

FILE = Path(__file__).resolve().parent / "combos.toml"
GROUP_ORDER: tuple[str, ...] = ("rest", "turbo", "retail")
NONE_COMBO = "ninguna"
SERVICE_COMBO = "favor"  # RappiFavor: servicio sin catálogo, fuera de la agrupación
# Orden de las combinaciones finas: los verticales del catálogo y después los servicios sin catálogo.
FINE_ORDER: tuple[str, ...] = (
    *("restaurantes", "turbo", "supermercado", "conveniencia", "mall", "chocolateria", "farmacia", "licores"),
    *("favor", "travel"),
)
SERVICES: tuple[str, ...] = ("favor", "travel")
OWN_SIGNALS_ONLY = frozenset({"farmacia", "licores"})  # sin transición ni popularidad: nunca los empujan otros
# La retención de Rappi pesa como 100 personas al mezclarla con la aprendida; con menos de 30 personas de una
# combinación no se mezcla nada.
LEARNED_RETENTION_PRIOR = 100
LEARNED_RETENTION_MIN_USERS = 30
MAX_RETENTION = 1 - 1e-9  # la retención esperada nunca llega a 1


@dataclass(frozen=True)
class ComboRow:
    combo: str
    users: int
    pct_users: float
    pct_orders: float
    orders_per_user: float
    retention_m1: float
    spend_per_user: float


@dataclass(frozen=True)
class Diminishing:
    """El supuesto propio de la escalera fina (`[rendimiento_decreciente]`)."""

    reduction_base: float  # fracción de la parte que no vuelve que quita la 2.ª vertical de un grupo
    decay: float  # cada vertical siguiente quita esto veces lo que quitó la anterior
    service: float  # fracción que quita cada servicio usado
    note: str


@dataclass(frozen=True)
class Combos:
    version: str
    groups: dict[str, tuple[str, ...]]
    group_of: dict[str, str]
    rappi: dict[str, ComboRow]
    rappi_total: ComboRow
    source_note: str
    diminishing: Diminishing
    services: dict[str, str]  # servicio → `payload.servicio` del evento `service_opened`


@dataclass(frozen=True)
class Step:
    """El paso fino: la vertical (o el servicio) que más retención esperada suma. `used_assumption` dice si la reducción
    del supuesto propio pesó en la retención de la combinación actual o en la del objetivo."""

    vertical: str
    current: str
    target: str
    gain: float
    used_assumption: bool


def _row(combo: str, data: dict) -> ComboRow:
    row = ComboRow(
        combo=combo,
        users=int(data["usuarios"]),
        pct_users=float(data["pct_usuarios"]),
        pct_orders=float(data["pct_pedidos"]),
        orders_per_user=float(data["pedidos_por_usuario"]),
        retention_m1=float(data["retencion_m1"]),
        spend_per_user=float(data["gasto_por_usuario"]),
    )
    if not 0 <= row.retention_m1 <= 1:
        raise ValueError(f"combos.toml: la retención de «{combo}» debe ser una fracción entre 0 y 1")
    return row


@cache
def load_combos() -> Combos:
    data = tomllib.loads(FILE.read_text(encoding="utf-8"))
    groups = {name: tuple(verticals) for name, verticals in data["grupos"].items()}
    if tuple(groups) != GROUP_ORDER:
        raise ValueError(f"combos.toml: los grupos deben ser {', '.join(GROUP_ORDER)}")
    group_of: dict[str, str] = {}
    for group, verticals in groups.items():
        for vertical in verticals:
            if vertical in group_of:
                raise ValueError(f"combos.toml: el vertical «{vertical}» está en dos grupos")
            group_of[vertical] = group
    missing = set(VERTICALS) - set(group_of)
    unknown = set(group_of) - set(VERTICALS)
    if missing or unknown:
        raise ValueError(f"combos.toml: verticales sin grupo {sorted(missing)} o desconocidos {sorted(unknown)}")
    rappi = {}
    for combo, values in data["combinaciones"].items():
        parts = combo.split("+")
        known = combo == SERVICE_COMBO or (
            all(p in GROUP_ORDER for p in parts) and combo == combo_key(parts) and len(set(parts)) == len(parts)
        )
        if not known:
            raise ValueError(f"combos.toml: la combinación «{combo}» no es de grupos conocidos en orden")
        rappi[combo] = _row(combo, values)
    if set(FINE_ORDER) - set(SERVICES) != set(VERTICALS):
        raise ValueError("combos.py: FINE_ORDER debe tener todos los verticales del catálogo")
    dim = data["rendimiento_decreciente"]
    diminishing = Diminishing(
        reduction_base=float(dim["reduccion_base"]),
        decay=float(dim["decaimiento"]),
        service=float(dim["servicio"]),
        note=dim["nota"],
    )
    d = diminishing
    if not (0 <= d.reduction_base < 1 and 0 <= d.service < 1 and 0 <= d.decay <= 1):
        raise ValueError("combos.toml: las reducciones deben estar entre 0 y 1 (sin 1) y el decaimiento entre 0 y 1")
    services = dict(data["servicios"])
    if tuple(services) != SERVICES:
        raise ValueError(f"combos.toml: los servicios deben ser {', '.join(SERVICES)}")
    return Combos(
        version=data["version"],
        groups=groups,
        group_of=group_of,
        rappi=rappi,
        rappi_total=_row("total", data["total"]),
        source_note=data["nota"],
        diminishing=diminishing,
        services=services,
    )


def combo_key(groups: Iterable[str]) -> str:
    """El nombre canónico de un conjunto de grupos: en el orden rest, turbo, retail, unidos por «+»."""
    present = set(groups)
    unknown = present - set(GROUP_ORDER)
    if unknown:
        raise ValueError(f"Grupo desconocido: {sorted(unknown)}")
    return "+".join(g for g in GROUP_ORDER if g in present) or NONE_COMBO


def combo_of_verticals(verticals: Iterable[str]) -> str:
    verticals = list(verticals)  # se recorre dos veces: un generador llegaría vacío a `combo_key`
    group_of = load_combos().group_of
    unknown = {v for v in verticals if v not in group_of}
    if unknown:
        raise ValueError(f"Vertical desconocido: {sorted(unknown)}")
    return combo_key(group_of[v] for v in verticals)


def expected_retention(combo: str, learned: dict[str, tuple[int, float]] | None = None) -> float | None:
    """La retención M+1 esperada de una combinación: la de Rappi, mezclada con la aprendida `(personas, retención)` si
    hay al menos `LEARNED_RETENTION_MIN_USERS`; solo la aprendida si Rappi no tiene la fila; `None` si no hay
    ninguna."""
    row = load_combos().rappi.get(combo)
    n, ret = (learned or {}).get(combo, (0, 0.0))
    enough = n >= LEARNED_RETENTION_MIN_USERS
    if row is None:
        return ret if enough else None
    if not enough:
        return row.retention_m1
    return (row.retention_m1 * LEARNED_RETENTION_PRIOR + ret * n) / (LEARNED_RETENTION_PRIOR + n)


def fine_key(members: Iterable[str]) -> str:
    """El nombre canónico de una combinación fina: verticales y servicios en el orden `FINE_ORDER`, unidos por «+»."""
    present = set(members)
    unknown = present - set(FINE_ORDER)
    if unknown:
        raise ValueError(f"Vertical o servicio desconocido: {sorted(unknown)}")
    return "+".join(m for m in FINE_ORDER if m in present) or NONE_COMBO


def fine_of(verticals: Iterable[str], services: Iterable[str] = ()) -> str:
    """La combinación fina de unos verticales del catálogo y unos servicios (`favor`, `travel`)."""
    verticals, services = list(verticals), list(services)
    not_vertical = {v for v in verticals if v not in load_combos().group_of}
    not_service = {s for s in services if s not in SERVICES}
    if not_vertical or not_service:
        raise ValueError(f"Vertical desconocido {sorted(not_vertical)} o servicio desconocido {sorted(not_service)}")
    return fine_key([*verticals, *services])


def _members(fine: str) -> list[str]:
    if fine == NONE_COMBO:
        return []
    parts = fine.split("+")
    if fine_key(parts) != fine or len(set(parts)) != len(parts):
        raise ValueError(f"La combinación fina «{fine}» no está en el orden canónico")
    return parts


def group_counts(fine: str) -> dict[str, int]:
    """Cuántos verticales del catálogo usa la combinación en cada grupo grueso (solo los grupos presentes)."""
    group_of = load_combos().group_of
    counts = Counter(group_of[m] for m in _members(fine) if m not in SERVICES)
    return {g: counts[g] for g in GROUP_ORDER if counts[g]}


def fine_churn_factor(fine: str) -> float:
    """Qué fracción de la parte que no vuelve queda con el supuesto propio: Π (1 − f). La j-ésima vertical de un grupo
    (j ≥ 2) tiene f = reduccion_base·decaimiento^(j−2) y cada servicio usado, f = `servicio`. Si la combinación es solo
    de servicios con Favor, Favor es la base (la fila «favor» de Rappi) y no reduce nada. Siempre es mayor que 0: la
    retención esperada nunca llega a 1."""
    dim = load_combos().diminishing
    members = _members(fine)
    factor = 1.0
    for k in group_counts(fine).values():
        for j in range(2, k + 1):
            factor *= 1 - dim.reduction_base * dim.decay ** (j - 2)
    services = [m for m in members if m in SERVICES]
    if len(services) == len(members) and SERVICE_COMBO in services:
        services.remove(SERVICE_COMBO)
    return factor * (1 - dim.service) ** len(services)


def _group_of(fine: str) -> str:
    """La combinación gruesa de los verticales del catálogo de una fina («ninguna» si solo hay servicios)."""
    return combo_of_verticals(m for m in _members(fine) if m not in SERVICES)


def _fine_expectation(
    fine: str,
    learned_coarse: dict[str, tuple[int, float]] | None,
    learned_fine: dict[str, tuple[int, float]] | None,
) -> tuple[float | None, bool]:
    """`(retención esperada, ¿pesó la reducción del supuesto?)` de una combinación fina.

    Lo aprendido fino solo corrige la diferencia dentro del grupo; el nivel lo pone la combinación gruesa. Con al menos
    `LEARNED_RETENTION_MIN_USERS` personas en la fila fina y en la gruesa aprendida de su grupo, la estimación aprendida
    es la gruesa mezclada más (fina aprendida − gruesa aprendida), y pesa n/(n + 100) frente a la esperada con el
    supuesto. Mezclar la fina aprendida directo arrastraba el nivel (la retención simulada queda bajo la de Rappi: desde
    el 17-10, hasta 0,063 en 6 de las 7 filas; antes, hasta 0,097) más en las combinaciones con muchas personas que en
    las con pocas, y eso daba vuelta la escalera gruesa."""
    members = _members(fine)
    catalog = [m for m in members if m not in SERVICES]
    group = combo_of_verticals(catalog) if catalog else None
    if catalog:
        prior = expected_retention(group, learned_coarse)
    elif SERVICE_COMBO in members:
        prior = expected_retention(SERVICE_COMBO, learned_coarse)
    elif not members:
        prior = expected_retention(NONE_COMBO, learned_coarse)
    else:  # solo RappiTravel: no está en la tabla de Rappi
        prior = None
    coarse_blended = prior
    used = False
    factor = fine_churn_factor(fine)
    if prior is not None and factor < 1:  # con factor 1 no se recalcula: la gruesa queda tal cual, sin redondeo
        reduced = 1 - (1 - prior) * factor
        used = reduced > prior
        prior = reduced
    n, ret = (learned_fine or {}).get(fine, (0, 0.0))
    if n < LEARNED_RETENTION_MIN_USERS:
        return prior, used
    group_n, group_ret = (learned_coarse or {}).get(group, (0, 0.0)) if group else (0, 0.0)
    if group_n >= LEARNED_RETENTION_MIN_USERS:  # solo la diferencia dentro del grupo: el nivel es el de la gruesa
        learned_estimate = coarse_blended + (ret - group_ret)
        weight = n / (n + LEARNED_RETENTION_PRIOR)
        return min(max((1 - weight) * prior + weight * learned_estimate, 0.0), MAX_RETENTION), used
    # Sin gruesa aprendida del grupo (o solo servicios): la fina aprendida se mezcla tal cual.
    if prior is None:
        return ret, False
    return (prior * LEARNED_RETENTION_PRIOR + ret * n) / (LEARNED_RETENTION_PRIOR + n), used


def expected_fine_retention(
    fine: str,
    learned_coarse: dict[str, tuple[int, float]] | None = None,
    learned_fine: dict[str, tuple[int, float]] | None = None,
) -> float | None:
    """La retención M+1 esperada de una combinación fina: 1 − (1 − gruesa)·`fine_churn_factor`, con la gruesa de
    `expected_retention` de sus grupos (y `learned_coarse`). La fina aprendida `(personas, retención)` de `learned_fine`
    solo corrige la diferencia dentro del grupo (el nivel lo pone la gruesa), con al menos `LEARNED_RETENTION_MIN_USERS`
    personas en la fila fina y en la gruesa aprendida del grupo; sin gruesa aprendida, se mezcla tal cual. Solo
    servicios: Favor parte de la fila «favor» de Rappi; solo Travel no tiene base (`None`, salvo que haya suficiente
    aprendido)."""
    return _fine_expectation(fine, learned_coarse, learned_fine)[0]


def next_fine_step(
    fine: str,
    candidates: Sequence[str],
    learned_coarse: dict[str, tuple[int, float]] | None = None,
    learned_fine: dict[str, tuple[int, float]] | None = None,
) -> Step | None:
    """La vertical (o servicio) de `candidates` que más retención esperada suma a la combinación fina. Los candidatos
    vienen en el orden de preferencia de la persona, que desempata. Una vertical del catálogo que suma algo va antes que
    cualquier servicio; Farmacia y Licores nunca son paso. `None` si la persona no tiene pedidos, si su combinación no
    tiene retención esperada o si nada suma.

    Dentro del mismo grupo grueso, un objetivo sin fina aprendida suficiente parte de la retención de la combinación
    actual (con lo que se aprendió de ella) y solo le aplica la reducción del supuesto: 1 − (1 − actual)·(factor del
    objetivo / factor de la actual). Así una corrección aprendida de la actual no detiene la escalera; sin nada
    aprendido da lo mismo que calcular el objetivo desde cero."""
    if fine == NONE_COMBO:
        return None
    current, current_used = _fine_expectation(fine, learned_coarse, learned_fine)
    if current is None:
        return None
    have = set(_members(fine))
    group = _group_of(fine)
    best: dict[bool, Step] = {}  # ¿es servicio? → mejor paso
    for vertical in candidates:
        if vertical in have or vertical in OWN_SIGNALS_ONLY:
            continue
        target = fine_key([*have, vertical])
        learned_target = (learned_fine or {}).get(target, (0, 0.0))[0] >= LEARNED_RETENTION_MIN_USERS
        if _group_of(target) == group and not learned_target:
            ratio = fine_churn_factor(target) / fine_churn_factor(fine)
            expected, target_used = 1 - (1 - current) * ratio, ratio < 1
        else:
            expected, target_used = _fine_expectation(target, learned_coarse, learned_fine)
        if expected is None or expected <= current:
            continue
        step = Step(vertical, fine, target, expected - current, current_used or target_used)
        is_service = vertical in SERVICES
        if is_service not in best or step.gain > best[is_service].gain:
            best[is_service] = step
    return best.get(False) or best.get(True)
