"""Las preferencias explícitas de la persona con el agente, para el panel del asistente (offers/preferences.py): verlas
y cambiarlas (una lista vacía las borra). Por chat se fijan en /agent/ask («soy vegetariano», «olvida mis
preferencias»).

`app.py` incluye este router; las dependencias viven en `deps.py`, así este módulo no importa `app`.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path
from psycopg import Connection
from pydantic import Field

from ..events.store import ensure_user
from ..offers import preferences
from .deps import Clean, get_conn
from .identity import owner_in_path
from .logs import rejected

router = APIRouter(prefix="/profile", tags=["preferencias"])

ShortPath = Annotated[str, Path(max_length=64)]


class PreferenceIn(Clean):
    tipo: Literal[preferences.KINDS]  # type: ignore[valid-type]
    valor: str = Field(min_length=1, max_length=preferences.MAX_VALUE)


class PreferencesIn(Clean):
    preferencias: list[PreferenceIn] = Field(default_factory=list, max_length=preferences.MAX_PREFERENCES)


def _reply(conn: Connection, user_id: str) -> dict:
    return {
        "preferencias": preferences.describe(preferences.saved(conn, user_id)),
        "opciones": preferences.options(),
    }


@router.get("/{user_id}/preferencias", dependencies=[Depends(owner_in_path)])
def get_preferences(user_id: ShortPath, conn: Connection = Depends(get_conn)) -> dict:
    """`{ preferencias: [{ tipo, valor, nombre }], opciones: [...] }`: las suyas (por tipo, en el orden en que las
    dijo) y lo que el panel ofrece marcar (dietas, alergias y cocinas; las tiendas se dicen por chat)."""
    return _reply(conn, user_id)


@router.put("/{user_id}/preferencias", dependencies=[Depends(owner_in_path)])
def put_preferences(user_id: ShortPath, body: PreferencesIn, conn: Connection = Depends(get_conn)) -> dict:
    """Reemplaza sus preferencias por las de `preferencias` (lo que dejó marcado en el panel). Lo que no es una opción
    se ignora; una tienda solo queda si ya la tenía o es una del catálogo. Responde como el GET."""
    mine = set(preferences.saved(conn, user_id))
    items = []
    for item in body.preferencias:
        if item.tipo == "tienda" and (item.tipo, item.valor) not in mine:
            store = preferences.find_store(conn, item.valor)
            if store is None:
                continue
            items.append(("tienda", store))
        else:
            items.append((item.tipo, item.valor))
    if items:
        try:
            ensure_user(conn, user_id)
        except ValueError as exc:  # una persona simulada: sus preferencias no se tocan desde la app
            raise rejected(exc, user_id) from exc
    preferences.replace_all(conn, user_id, items)
    conn.commit()
    return _reply(conn, user_id)
