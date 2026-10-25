"""Cada persona simulada queda con su marca Rappi Pro (app_users.pro, migración 046)."""

from datetime import date

from rappi_ia.demo.seed import seed_demo
from rappi_ia.events.synth import generate


def test_every_synthetic_person_is_pro_or_not(db):
    seed_demo(db)
    generate(db, users=80, weeks=6, seed=5, until=date(2026, 10, 4))
    counts = dict(db.execute("SELECT pro, count(*) FROM app_users WHERE source = 'synthetic' GROUP BY 1").fetchall())
    assert None not in counts
    assert counts.get(True, 0) > 0 and counts.get(False, 0) > 0
