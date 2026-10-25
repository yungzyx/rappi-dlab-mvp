"""Cálculos de precio compartidos por parsers, base de datos y CSV."""


def discount_pct(price: float | None, real_price: float | None) -> float:
    """Descuento en % respecto al precio normal (0 si no hay descuento o faltan datos)."""
    if not price or not real_price or real_price <= price:
        return 0.0
    return round((1 - price / real_price) * 100, 1)
