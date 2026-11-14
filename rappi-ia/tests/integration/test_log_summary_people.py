"""Las personas nuevas del resumen diario de la API: solo las del prototipo creadas ese día, en hora de Chile."""

from datetime import date, datetime

from rappi_ia.api import log_summary
from rappi_ia.catalog.hours import TZ
from rappi_ia.events import store as events


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


def test_agent_changes_count_silences_apart_from_hides_that_chilean_day(db):
    day = datetime(2026, 11, 3, 12, 0, tzinfo=TZ)

    def change(user, payload, ts=day):
        return events.Event(user, "s1", "agent_visibility", ts=ts, origin="menu-mochi", payload=payload)

    events.record(
        db,
        [
            change("proto-a", {"visible": True, "quiet": True}),
            change("proto-a", {"visible": True, "quiet": False}),  # despertarlo no cuenta
            change("proto-b", {"visible": True, "quiet": True}),
            change("proto-b", {"visible": False}),
            change("proto-c", {"visible": True}),  # traerlo de vuelta no cuenta
            change("proto-c", {"visible": False}, ts=datetime(2026, 11, 4, 0, 1, tzinfo=TZ)),  # otro día
        ],
    )
    events.record(db, [change("syn-x", {"visible": True, "quiet": True})], source="synthetic")

    assert log_summary.agent_changes(db, date(2026, 11, 3)) == (2, 1)


def test_survey_counts_are_the_prototype_ones_of_that_chilean_day(db):
    day = datetime(2026, 11, 3, 12, 0, tzinfo=TZ)

    def survey(user, kind, question, ts=day, **extra):
        payload = {"question": question, "trigger": "carro", **extra}
        return events.Event(user, "s1", kind, ts=ts, payload=payload)

    events.record(
        db,
        [
            survey("proto-a", "survey_shown", "p1"),
            survey("proto-a", "survey_answer", "p1", answer="si"),
            survey("proto-a", "survey_shown", "p3"),
            survey("proto-a", "survey_answer", "p3", answer=5),
            survey("proto-b", "survey_shown", "p1"),
            survey("proto-b", "survey_answer", "p1", answer="en_parte"),
            survey("proto-c", "survey_shown", "p1"),
            survey("proto-c", "survey_dismissed", "p1"),
            survey("proto-d", "survey_shown", "p1", ts=datetime(2026, 11, 4, 0, 1, tzinfo=TZ)),  # otro día
        ],
    )
    events.record(db, [survey("syn-x", "survey_answer", "p1", answer="no")], source="synthetic")

    assert log_summary.survey_counts(db, date(2026, 11, 3)) == {
        "mostrada": 3,
        "si": 1,
        "en_parte": 1,
        "no": 0,
        "cerrada": 1,
        "p3": 1,
    }
