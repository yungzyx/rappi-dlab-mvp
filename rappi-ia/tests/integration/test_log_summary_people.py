"""Las personas nuevas del resumen diario de la API: solo las del prototipo creadas ese día, en hora de Chile."""

from datetime import date, datetime

from rappi_ia.api import log_summary
from rappi_ia.catalog.hours import TZ


def test_new_people_are_the_prototype_ones_created_that_chilean_day(db):
    rows = [
        ("proto-a", "prototype", datetime(2026, 11, 3, 0, 5, tzinfo=TZ)),
        ("proto-b", "prototype", datetime(2026, 11, 3, 23, 55, tzinfo=TZ)),
        ("proto-c", "prototype", datetime(2026, 11, 4, 0, 1, tzinfo=TZ)),  # del día siguiente
        ("syn-x", "synthetic", datetime(2026, 11, 3, 12, 0, tzinfo=TZ)),  # simulada: no cuenta
    ]
    for row in rows:
        db.execute("INSERT INTO app_users (user_id, source, created_at) VALUES (%s, %s, %s)", row)

    assert log_summary.new_people(db, date(2026, 11, 3)) == 2
