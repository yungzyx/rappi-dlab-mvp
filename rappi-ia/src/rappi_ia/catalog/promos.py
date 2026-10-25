"""Las promos de cada tienda tal como Rappi las publicó el día de la descarga (`stores.raw.offers`: `type`, `title`,
`value`). No se inventan mecánicas (lleva 3 paga 2, 2.ª unidad): solo se repite lo publicado.

El umbral de una promo («Envío gratis sobre $15.000») sale de su propio texto, cuando lo dice; sin él, la promo no
tiene barra de «Agrega $X».
"""

import re

MAX_PROMOS = 3
# Un monto que el texto presenta como mínimo: «sobre $15.000», «desde $9.990», «compras de $20.000», «mínimo $5.000».
_THRESHOLD = re.compile(
    r"(?:sobre|desde|m[ií]nim[oa](?:\s+de)?|compras?\s+(?:de|sobre|desde)|pedidos?\s+(?:de|sobre|desde))"
    r"\s*\$\s*(\d{1,3}(?:\.\d{3})+|\d+)",
    re.IGNORECASE,
)


def _number(value) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def promo_threshold(text: str) -> int | None:
    """El monto mínimo que nombra el texto de una promo, en pesos; None si no nombra ninguno."""
    match = _THRESHOLD.search(text)
    return int(match[1].replace(".", "")) if match else None


def store_promos(offers) -> list[dict]:
    """Hasta MAX_PROMOS promos con título, `[{type, title, value, threshold}]`, sin repetir títulos. Lo que no es una
    lista de objetos con título (Rappi manda `null` cuando no hay) no trae promos."""
    promos: list[dict] = []
    for offer in offers if isinstance(offers, list) else []:
        title = offer.get("title") if isinstance(offer, dict) else None
        if not isinstance(title, str) or not title.strip():
            continue
        title = " ".join(title.split())
        if any(p["title"] == title for p in promos):
            continue
        description = offer.get("description") if isinstance(offer.get("description"), str) else ""
        kind = offer.get("type")
        promos.append(
            {
                "type": kind if isinstance(kind, str) and kind else None,
                "title": title,
                "value": _number(offer.get("value")),
                "threshold": promo_threshold(f"{title} {description}"),
            }
        )
    return promos[:MAX_PROMOS]
