"""Condiciones de compra de cada tienda para el carro y el checkout: costo de envío, compra mínima y tarifa de servicio,
solo las que trae el catálogo (solo lectura). Lo que falta va en `None`: la app pone su supuesto rotulado por vertical
(prototipo-app/src/screens/checkout/pricing.js) y nunca lo presenta como dato de Rappi.

De dónde sale cada dato:
- Restaurantes: `restaurant_details.delivery_cost` (> 0; un $0 es un dato que falta, como en la tarjeta).
- Tiendas: el `raw` que la descarga guarda de Rappi (`storeContext`). `mov_value` es la compra mínima (0 = «sin mínimo»,
  que también es un dato); el envío es `charges.delivery.delivery_fee_charge` si es positivo y, si no,
  `delivery_price`; `percentage_service_fee` es el porcentaje de la tarifa de servicio. La descarga va sin dirección
  (`zone_id` 0): el envío y la tarifa suelen venir en 0, y `delivery_price` trae valores como 30 que no son un envío en
  pesos. Por eso un envío bajo `MIN_DELIVERY_FEE` y un porcentaje que no es positivo cuentan como desconocidos.
"""

import math

from psycopg import Connection

MAX_STORES = 20  # un carro de la demo no tiene más tiendas
MIN_DELIVERY_FEE = 100  # bajo esto no es un envío en pesos chilenos (ver arriba)
MAX_SERVICE_PCT = 50  # un porcentaje mayor no es una tarifa de servicio

_TERMS = """
SELECT s.store_id, d.delivery_cost,
       s.raw ->> 'mov_value',
       s.raw -> 'charges' -> 'delivery' ->> 'delivery_fee_charge',
       s.raw ->> 'delivery_price',
       s.raw ->> 'percentage_service_fee'
FROM stores s
LEFT JOIN restaurant_details d ON d.store_id = s.store_id
WHERE s.store_id = ANY(%(ids)s)
ORDER BY s.store_id"""


def _number(value) -> float | None:
    """Un número del `raw` (texto o número); lo que no es un número finito, `None`."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def store_terms(conn: Connection, store_ids: list[int]) -> list[dict]:
    """Las condiciones de las tiendas pedidas que están en el catálogo, por id: `delivery_fee` y `min_order` en pesos
    (`int`), `service_pct` en porcentaje; `None` si el catálogo no lo sabe. Las que no existen no salen."""
    ids = sorted(set(store_ids))[:MAX_STORES]
    if not ids:
        return []
    out = []
    for store_id, delivery_cost, mov, fee_charge, delivery_price, service in conn.execute(_TERMS, {"ids": ids}):
        delivery = None
        for candidate in (_number(delivery_cost), _number(fee_charge), _number(delivery_price)):
            if candidate is not None and candidate >= MIN_DELIVERY_FEE:
                delivery = round(candidate)
                break
        minimum = _number(mov)
        pct = _number(service)
        out.append(
            {
                "store_id": store_id,
                "delivery_fee": delivery,
                "min_order": round(minimum) if minimum is not None and minimum >= 0 else None,
                "service_pct": pct if pct is not None and 0 < pct <= MAX_SERVICE_PCT else None,
            }
        )
    return out
