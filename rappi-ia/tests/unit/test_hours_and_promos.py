"""El horario publicado (catalog/hours.py), las promos de la tienda (catalog/promos.py) y la guardia de "Lo que sea"."""

from datetime import datetime

import pytest

from rappi_ia.catalog.hours import DAYS, TZ, closed_last, normalize_schedule, restaurant_hours, store_hours
from rappi_ia.catalog.promos import promo_threshold, store_promos
from rappi_ia.offers.guards import whim_allowed

THURSDAY = datetime(2026, 10, 22, 13, 0, tzinfo=TZ)  # 22-10-2026 es jueves


def at(hour: int, minute: int = 0, day: int = 22) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)


def schedule(*spans):
    return normalize_schedule([{"open_time": o, "close_time": c, "day": d} for o, c, d in spans])


EVERY_DAY = [("11:00:00", "23:00:00", day) for day in DAYS]


def test_open_inside_todays_span_says_when_it_closes():
    hours = restaurant_hours(schedule(*EVERY_DAY), THURSDAY)
    assert hours == {
        "source": "horario",
        "open": True,
        "closes_at": "23:00",
        "opens_at": None,
        "opens_tomorrow": False,
        "today": "11:00–23:00",
    }


def test_closed_before_opening_says_when_it_opens_today():
    hours = restaurant_hours(schedule(*EVERY_DAY), at(9, 30))
    assert (hours["open"], hours["opens_at"], hours["opens_tomorrow"]) == (False, "11:00", False)


def test_closed_after_closing_opens_tomorrow():
    hours = restaurant_hours(schedule(*EVERY_DAY), at(23, 15))
    assert (hours["open"], hours["opens_at"], hours["opens_tomorrow"]) == (False, "11:00", True)


def test_a_span_past_midnight_counts_both_parts():
    late = schedule(*[("19:00:00", "02:00:00", d) for d in ("wed", "thu")])
    assert restaurant_hours(late, at(22))["open"] is True
    assert restaurant_hours(late, at(1, 30))["open"] is True  # jueves 1:30, lo que queda del miércoles
    assert restaurant_hours(late, at(2, 30))["open"] is False


def test_a_single_published_day_holds_for_every_day():
    only_thursday = schedule(("09:00:00", "20:00:00", "thu"))
    monday = at(12, day=26)
    assert restaurant_hours(only_thursday, monday)["open"] is True


def test_several_days_without_today_is_closed_today():
    weekend = schedule(("12:00:00", "22:00:00", "sat"), ("12:00:00", "22:00:00", "sun"))
    hours = restaurant_hours(weekend, THURSDAY)
    assert (hours["open"], hours["opens_at"], hours["today"]) == (False, None, None)


def test_no_schedule_is_unknown_and_stays_with_the_open_ones():
    assert restaurant_hours([], THURSDAY)["open"] is None
    cards = [{"id": n, "hours": {"open": state}} for n, state in ((1, False), (2, None), (3, True))]
    assert [c["id"] for c in closed_last(cards)] == [2, 3, 1]


def test_unreadable_entries_are_dropped():
    assert normalize_schedule([{"day": "jue", "open_time": "9:00"}, "x", {"day": "fri", "open_time": "25:00"}]) == []
    assert normalize_schedule(None) == []


def test_store_hours_repeat_the_download_state():
    assert store_hours({"is_open": True}) == {
        "source": "descarga",
        "open": True,
        "closes_at": None,
        "opens_at": None,
        "opens_tomorrow": False,
        "today": None,
    }
    closed = store_hours({"is_open": False, "next_schedule": {"open_time": "10:00:00"}})
    assert (closed["open"], closed["opens_at"]) == (False, "10:00")
    assert store_hours({"is_open": False, "next_schedule": "mañana"})["opens_at"] is None
    assert store_hours({}) is None and store_hours(None) is None


def test_store_promos_keep_what_rappi_published():
    offers = [
        {"type": "free_shipping", "title": " Envío  gratis sobre $15.000 ", "value": 0},
        {"type": "percentage", "title": "10% OFF en todo", "value": 10},
        {"type": "percentage", "title": "10% OFF en todo", "value": 10},
        {"type": "value", "title": ""},
        "texto suelto",
    ]
    assert store_promos(offers) == [
        {"type": "free_shipping", "title": "Envío gratis sobre $15.000", "value": 0.0, "threshold": 15000},
        {"type": "percentage", "title": "10% OFF en todo", "value": 10.0, "threshold": None},
    ]
    assert store_promos(None) == [] and store_promos({"type": "x"}) == []


@pytest.mark.parametrize(
    ("text", "threshold"),
    [
        ("Envío gratis sobre $15.000", 15000),
        ("Desde $9990 en compras", 9990),
        ("Envío gratis en compras de $20.000", 20000),
        ("$3.000 de descuento", None),  # el monto del descuento no es un mínimo
        ("10% OFF", None),
    ],
)
def test_promo_threshold_is_only_a_stated_minimum(text, threshold):
    assert promo_threshold(text) == threshold


@pytest.mark.parametrize(
    ("text", "allowed"),
    [
        ("zapatillas talla 42", True),
        ("un regalo para mi mamá", True),
        ("droga", False),
        ("cigarros", False),
        ("cerveza artesanal", False),
        ("paracetamol", False),
        ("pañales", False),
        ("   ", False),
    ],
)
def test_whim_allowed_follows_blocked_words_and_guards(text, allowed):
    assert whim_allowed(text) is allowed
