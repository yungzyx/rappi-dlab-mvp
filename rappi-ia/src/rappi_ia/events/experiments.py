"""Experimentos (migración 047; docs/capa-de-datos.md): la variante de cada persona, asignada una vez y estable.

- `modo_app` (propuesta o actual) no es al azar: lo elige quien presenta la demo. La variante de la persona es el modo
  de su primera sesión (`assign_mode`, desde lo que la app cuenta de la sesión); el de cada sesión queda en
  `app_sessions.mode`. Comparar sus variantes describe, no mide un efecto.
- `ofertas_control` sí es al azar: un sorteo estable con el id de la persona (`bucket`) la deja en `control` si cae bajo
  `config.OFFERS_CONTROL_PCT`. En 0 (lo de siempre) nadie entra: no se asigna ni se retiene nada. Quien ya tenía una
  variante la conserva aunque el porcentaje cambie.

Las asignaciones llevan la población de la persona (`app_users.source`): un trigger de la base lo exige, y quien compare
variantes lo hace dentro de una sola.
"""

import hashlib

from psycopg import Connection

from .. import config

MODE = "modo_app"
OFFERS_CONTROL = "ofertas_control"
CONTROL = "control"
TREATMENT = "tratamiento"


def bucket(user_id: str, experiment_id: str) -> int:
    """El lugar estable (0 a 99) de la persona en el experimento: el mismo id da siempre el mismo."""
    digest = hashlib.sha256(f"{experiment_id}:{user_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % 100


def assign(conn: Connection, user_id: str, experiment_id: str, variant: str) -> str:
    """La variante de la persona: la que ya tenía o, si no tenía, `variant` (desde ahora la suya)."""
    conn.execute(
        """INSERT INTO experiment_assignments (user_id, experiment_id, variant, source)
           SELECT user_id, %s, %s, source FROM app_users WHERE user_id = %s
           ON CONFLICT (user_id, experiment_id) DO NOTHING""",
        (experiment_id, variant, user_id),
    )
    row = conn.execute(
        "SELECT variant FROM experiment_assignments WHERE user_id = %s AND experiment_id = %s",
        (user_id, experiment_id),
    ).fetchone()
    return row[0] if row else variant


def offers_variant(conn: Connection, user_id: str, pct: int | None = None) -> str | None:
    """La variante de la persona en `ofertas_control`, o None si el experimento está apagado (porcentaje 0): entonces
    nadie entra y ninguna oferta se retiene."""
    pct = config.OFFERS_CONTROL_PCT if pct is None else pct
    if pct <= 0:
        return None
    return assign(conn, user_id, OFFERS_CONTROL, CONTROL if bucket(user_id, OFFERS_CONTROL) < pct else TREATMENT)


def assign_mode(conn: Connection, user_id: str, mode: str | None) -> None:
    """`modo_app`: el modo de la primera sesión que la app contó. Las siguientes no lo cambian."""
    if mode in ("propuesta", "actual"):
        assign(conn, user_id, MODE, mode)


def variants(conn: Connection, user_id: str) -> dict[str, str]:
    """Las variantes de la persona, por experimento."""
    rows = conn.execute(
        "SELECT experiment_id, variant FROM experiment_assignments WHERE user_id = %s ORDER BY experiment_id",
        (user_id,),
    )
    return dict(rows.fetchall())
