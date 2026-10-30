""" "Pedir por mí" (offers/autonomy.py): verlo, encenderlo o cambiarlo, y apagarlo en un toque. Por defecto, "Revisar
antes de pedir". Solo las personas del prototipo lo cambian desde la app.

`app.py` incluye este router; las dependencias viven en `deps.py`, así este módulo no importa `app`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from psycopg import Connection
from pydantic import Field

from ..events.store import ensure_user
from ..offers import autonomy
from .deps import Clean, get_conn
from .identity import owner_in_path
from .logs import rejected

router = APIRouter(prefix="/profile", tags=["autonomia"])

ShortPath = Annotated[str, Path(max_length=64)]


class AutonomyIn(Clean):
    tiendas: list[Annotated[int, Field(ge=0, le=2**63 - 1)]] = Field(min_length=1, max_length=autonomy.MAX_STORES)
    tope: int = Field(ge=autonomy.MIN_TOTAL, le=autonomy.MAX_TOTAL)


@router.get("/{user_id}/autonomia", dependencies=[Depends(owner_in_path)])
def get_autonomy(user_id: ShortPath, conn: Connection = Depends(get_conn)) -> dict:
    """`{ modo: 'revisar' | 'pedir', tiendas: [id], tope, opciones: { tiendas: [{ id, name, vertical }], tope_min,
    tope_max, tope_sugerido } }`: el permiso y las tiendas de las que ya pidió que puede elegir."""
    return autonomy.describe(conn, user_id)


@router.put("/{user_id}/autonomia", dependencies=[Depends(owner_in_path)])
def put_autonomy(user_id: ShortPath, body: AutonomyIn, conn: Connection = Depends(get_conn)) -> dict:
    """Enciende o cambia "Pedir por mí" con las tiendas (de las que ya pidió) y el tope por pedido. Responde como el
    GET; una tienda que no puede elegir es un 422."""
    try:
        ensure_user(conn, user_id)
    except ValueError as exc:  # una persona simulada: su permiso no se toca desde la app
        raise rejected(exc, user_id) from exc
    try:
        autonomy.save(conn, user_id, body.tiendas, body.tope)
    except autonomy.AutonomyError as exc:
        raise HTTPException(422, str(exc)) from exc
    conn.commit()
    return autonomy.describe(conn, user_id)


@router.delete("/{user_id}/autonomia", dependencies=[Depends(owner_in_path)])
def delete_autonomy(user_id: ShortPath, conn: Connection = Depends(get_conn)) -> dict:
    """Apaga "Pedir por mí": vuelve a "Revisar antes de pedir". Responde como el GET."""
    autonomy.turn_off(conn, user_id)
    conn.commit()
    return autonomy.describe(conn, user_id)
