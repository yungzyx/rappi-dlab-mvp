"""El contador de las guardias: cuántos candidatos sacaron las guardias de ofertas (`guards.py`) al armar lo que Mochi
propone por su cuenta, por día, población, momento y motivo (`guards.GUARD_REASONS`), sin persona ni producto
(migración 062, tabla `guard_blocks`).

Un candidato es un producto que salió de una búsqueda o de las ofertas del catálogo y que una guardia sacó (en
`agent/tools.py: _with_prices` y `engine._offerable_products`), o una vertical bloqueada donde Mochi iba a buscar
(`guards.offerable_verticals`). Cuenta lo que se sacó, no las ofertas: el mismo producto, buscado dos veces, cuenta dos.
No cuenta lo que se descarta antes por la historia de la persona (una recompra de Farmacia, un interés en vino): diría
algo de ella. Lo que queda guardado en la caché del catálogo ya filtrado no vuelve a contarse.

La API cuenta mientras arma una respuesta (`counting`) y guarda al final (`save`); fuera de eso, `count` no hace nada
(los trabajos, los tests y las evaluaciones no cuentan). Las búsquedas en paralelo (`contextvars.copy_context`) suman
al mismo contador.
"""

import threading
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from psycopg import Connection

from .guards import GUARD_REASONS

_COUNTS: ContextVar[Counter | None] = ContextVar("guard_blocks", default=None)
_LOCK = threading.Lock()  # los hilos de una búsqueda en paralelo comparten el contador


@contextmanager
def counting() -> Iterator[Counter]:
    """Mientras dura, `count` suma en el contador que entrega (motivo → candidatos sacados)."""
    counts: Counter = Counter()
    token = _COUNTS.set(counts)
    try:
        yield counts
    finally:
        _COUNTS.reset(token)


def count(reason: str | None) -> None:
    """Suma un candidato sacado por `reason` (uno de `guards.GUARD_REASONS`; None no cuenta), si se está contando."""
    counts = _COUNTS.get()
    if counts is None or reason is None:
        return
    if reason not in GUARD_REASONS:
        raise ValueError(f"Motivo de guardia desconocido: {reason!r}")
    with _LOCK:
        counts[reason] += 1


def save(conn: Connection, moment: str, counts: Counter, source: str = "prototype") -> None:
    """Suma `counts` a los de hoy (hora de Chile: la de la conexión) de ese momento y población. Sin nada, no escribe.
    No confirma la transacción: la cierra quien llama."""
    rows = [(source, moment, reason, n) for reason, n in sorted(counts.items()) if n > 0]
    if not rows:
        return
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO guard_blocks (day, source, moment, reason, blocked)
               VALUES (current_date, %s, %s, %s, %s)
               ON CONFLICT (day, source, moment, reason)
               DO UPDATE SET blocked = guard_blocks.blocked + EXCLUDED.blocked""",
            rows,
        )
