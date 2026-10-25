"""Mide la mezcla de combinaciones de los simulados contra la tabla de Rappi y ajusta `ARCHETYPE_CALIBRATION`, sin
escribir en la base.

Corre `events.synth.generate` en memoria con el catálogo de la base (leído en una transacción de solo lectura) y una
conexión falsa que guarda lo que se copiaría; mide como el motor (`combo_months` y `combo_stats`, nivel grueso).

- Sin `--ajustar`: la parte de personas-mes y la retención M+1 de cada combinación, por
  semilla, junto a la tabla de Rappi sin Favor (renormalizada a 100, porque Favor no tiene catálogo).
- Con `--ajustar`: simula `--altas` personas de cada arquetipo por separado (cada persona se simula sola, así que los
  meses que deja un alta de un arquetipo no dependen de la mezcla), arma la matriz arquetipo × combinación y busca los
  pesos de alta no negativos cuya mezcla de personas-mes es la de la tabla (NNLS, con scipy del extra `ml`). Imprime
  el factor de cada arquetipo (peso ajustado / parte en la tabla) para copiarlo a `ARCHETYPE_CALIBRATION`.

Uso (desde rappi-ia/):
    .venv/bin/python scripts/calibrar_simulados.py --base rappi_staging --semillas 7 11 23
    .venv/bin/python scripts/calibrar_simulados.py --base rappi_staging --ajustar --altas 12000 --hasta 2026-10-17

Con `--ajustar`, `--hasta` es obligatoria (el ajuste depende de la ventana) y la semilla es FIT_SEED: con el mismo
catálogo, la misma orden da los mismos factores.

Simulado: no es evidencia. No se importa desde el paquete.
"""

import argparse
from datetime import date, datetime

import psycopg

from rappi_ia.events import synth
from rappi_ia.motor.combos import SERVICE_COMBO, load_combos
from rappi_ia.motor.data import Order
from rappi_ia.motor.model import combo_months, combo_stats

FIT_SEED = 101  # semilla de las altas por arquetipo al ajustar


class _CaptureConn:
    """Lo mínimo que usa `generate`: no borra ni confirma nada; `_copy` se reemplaza para guardar los pedidos."""

    def execute(self, *args, **kwargs):
        return None

    def commit(self):
        return None


def simulate(catalog: synth.Catalog, users: int, seed: int, until: date, archetype: str | None = None) -> list[Order]:
    """Los pedidos de una corrida de `generate` (todas del `archetype` si se da), sin tocar la base."""
    copied: dict[str, str] = {}
    saved = (synth.load_catalog, synth._copy, dict(synth.ARCHETYPES))
    synth.load_catalog = lambda conn: catalog
    synth._copy = lambda conn, target, buffer: copied.__setitem__(target.split(" ")[0], buffer.getvalue())
    if archetype:
        synth.ARCHETYPES.clear()
        synth.ARCHETYPES[archetype] = 1.0
    try:
        synth.generate(_CaptureConn(), users=users, seed=seed, until=until)
    finally:
        synth.load_catalog, synth._copy = saved[0], saved[1]
        synth.ARCHETYPES.clear()
        synth.ARCHETYPES.update(saved[2])
    orders = []
    for line in copied["app_orders"].splitlines():
        order_id, user_id, _session, cart_id, ts, vertical, total, _source = line.split("\t")
        orders.append(Order(user_id, order_id, cart_id, datetime.fromisoformat(ts), vertical, float(total), ()))
    return orders


def target() -> dict[str, float]:
    """La parte de cada combinación en la tabla de Rappi, sin Favor y renormalizada a 1."""
    rows = {c: r.pct_users for c, r in load_combos().rappi.items() if c != SERVICE_COMBO}
    return {c: share / sum(rows.values()) for c, share in rows.items()}


def measure(catalog: synth.Catalog, seeds: list[int], users: int, until: date) -> None:
    rappi, goal = load_combos().rappi, target()
    stats = {seed: combo_stats(combo_months(simulate(catalog, users, seed, until))) for seed in seeds}
    print("| Combinación | Rappi sin Favor % | " + " | ".join(f"Semilla {s} %" for s in seeds) + " | Retención Rappi | "
          + " | ".join(f"Semilla {s} (n)" for s in seeds) + " |")  # fmt: skip
    print("|---|---:|" + "---:|" * len(seeds) + "---:|" + "---:|" * len(seeds))
    for combo in sorted(goal, key=lambda c: -goal[c]):
        shares = [f"{stats[s][combo]['pct_users']:.1f}" if combo in stats[s] else "0" for s in seeds]
        kept = []
        for s in seeds:
            row = stats[s].get(combo)
            kept.append(
                "—" if not row or row["retention_m1"] is None else f"{row['retention_m1']:.3f} ({row['retention_n']})"
            )
        print(f"| {combo} | {100 * goal[combo]:.1f} | " + " | ".join(shares)
              + f" | {rappi[combo].retention_m1:.2f} | " + " | ".join(kept) + " |")  # fmt: skip
    for s in seeds:
        gaps = [abs(stats[s].get(c, {}).get("pct_users", 0.0) - 100 * goal[c]) for c in goal]
        print(f"Semilla {s}: distancia {sum(gaps):.1f} puntos, la mayor {max(gaps):.1f}")


def fit(catalog: synth.Catalog, users: int, until: date) -> None:
    import numpy as np
    from scipy.optimize import nnls

    goal = target()
    combos = list(goal)
    months = np.zeros((len(combos), len(combos)))  # arquetipo × combinación: personas-mes por alta
    for i, archetype in enumerate(combos):
        for m in combo_months(simulate(catalog, users, FIT_SEED, until, archetype)):
            months[i, combos.index(m.combo)] += 1
    months /= users
    t = np.array([goal[c] for c in combos])
    # Σ_a x_a·M[a, c] = t_c · Σ_a x_a·meses_a para cada combinación, y Σ x = 1 (fila con peso 10).
    system = np.vstack([months.T - np.outer(t, months.sum(axis=1)), 10 * np.ones(len(combos))])
    weights, _ = nnls(system, np.concatenate([np.zeros(len(combos)), [10.0]]))
    weights /= weights.sum()
    mix = months.T @ weights
    mix /= mix.sum()
    print("| Arquetipo | Personas-mes por alta | Alta ajustada % | Tabla % | Factor | Mezcla esperada % |")
    print("|---|---:|---:|---:|---:|---:|")
    for i, c in enumerate(combos):
        print(f"| {c} | {months[i].sum():.2f} | {100 * weights[i]:.1f} | {100 * t[i]:.1f} | {weights[i] / t[i]:.2f} | "
              f"{100 * mix[i]:.1f} |")  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser(description="Mide y ajusta la mezcla de los simulados, sin escribir en la base.")
    parser.add_argument("--base", default="rappi_staging", help="base de la que se lee el catálogo")
    parser.add_argument("--semillas", type=int, nargs="+", default=[7, 11, 23])
    parser.add_argument("--usuarios", type=int, default=synth.DEFAULT_USERS, help="personas por semilla al medir")
    parser.add_argument("--hasta", type=date.fromisoformat, help="fecha final AAAA-MM-DD (al medir, por defecto hoy)")
    parser.add_argument("--ajustar", action="store_true", help="ajusta ARCHETYPE_CALIBRATION")
    parser.add_argument("--altas", type=int, default=12000, help="personas por arquetipo al ajustar")
    args = parser.parse_args()
    if args.ajustar and args.hasta is None:
        parser.error("--ajustar necesita --hasta: los factores dependen de la ventana simulada")
    with psycopg.connect(f"postgresql:///{args.base}") as conn:
        conn.read_only = True
        catalog = synth.load_catalog(conn)
        conn.rollback()
    if args.ajustar:
        fit(catalog, args.altas, args.hasta)
    else:
        measure(catalog, args.semillas, args.usuarios, args.hasta or date.today())


if __name__ == "__main__":
    main()
