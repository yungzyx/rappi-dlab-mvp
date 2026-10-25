"""Redacción de datos personales antes de guardar una consulta (docs/diseno-ia.md §2)."""

import pytest

from rappi_ia.events.store import redact

REDACTED = [
    ("+569 1234 5678", "[teléfono]"),
    ("+56912345678", "[teléfono]"),
    ("9-1234-5678", "[teléfono]"),
    ("+56 9 1234-5678", "[teléfono]"),
    ("+56 2 2123 4567", "[teléfono]"),
    ("12.345.678-5", "[rut]"),
    ("12.345.678 - 5", "[rut]"),
    ("12 345 678-5", "[rut]"),
    ("12.345.678‐5", "[rut]"),  # guion Unicode
    ("Avda. Apoquindo 3000", "[dirección]"),
    ("Av Kennedy #5413", "[dirección]"),
    ("Av. Kennedy N° 5413", "[dirección]"),
    ("Camino El Alba 9000", "[dirección]"),
    ("vivo en Los Leones 123 depto 45", "vivo en [dirección]"),
    ("juan @ gmail.com", "[correo]"),
    ("x@sub.mi-dominio.cl", "[correo]"),
    ("4111 1111 1111 1111", "[tarjeta]"),
    ("me llamo Juan Pérez Soto", "me llamo [nombre]"),
    ("mi nombre es María José", "mi nombre es [nombre]"),
    ("manda a Los Leones 123", "manda a [dirección]"),
    ("estoy en Apoquindo 3000", "estoy en [dirección]"),
]
UNCHANGED = [
    "comida de calle para 4",
    "pack de 12 cervezas",
    "cerveza bajo 3 mil",
    "pañales talla g 40 unidades",
    "vino 750 cc $12.990",
    "promo 2x1 hasta las 22 hrs",
    "12.345.678-9",  # dígito verificador inválido: no es un RUT
    "me llamo la atención este vino",  # sin mayúscula no es un nombre
]


@pytest.mark.parametrize(("text", "expected"), REDACTED)
def test_personal_data_is_redacted(text, expected):
    assert redact(text) == expected


@pytest.mark.parametrize("text", UNCHANGED)
def test_ordinary_queries_are_not_touched(text):
    assert redact(text) == text
