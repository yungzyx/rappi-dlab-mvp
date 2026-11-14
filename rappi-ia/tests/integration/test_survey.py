"""La pregunta in-app de la H3 (migración 057): `survey_shown`, `survey_answer` y `survey_dismissed`, con su pregunta,
su respuesta y su motivo validados; se van con la persona ("Borrar mis datos" y la purga) y `/analytics/encuesta` los
cuenta."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from owner_client import OwnerClient
from rappi_ia.analytics import queries
from rappi_ia.api import app as api
from rappi_ia.events import experiments
from rappi_ia.events import store as events

PERSON = "proto-00000000000e0c01"
NOW = datetime(2026, 11, 13, 12, tzinfo=UTC)


@pytest.fixture
def client(db):
    def conn_override():
        yield db

    api.app.dependency_overrides[api.get_conn] = conn_override
    yield OwnerClient(api.app)
    api.app.dependency_overrides.clear()


def survey(kind="survey_answer", question="p1", answer="si", trigger="busqueda", **payload):
    """Un evento de la pregunta como lo manda la app (FoundItCard.jsx), con la búsqueda que la originó."""
    body = {"question": question, "trigger": trigger, **payload}
    if kind == "survey_answer":
        body["answer"] = answer
    return {
        "type": kind,
        "session_id": "s-enc",
        "client_event_id": str(uuid.uuid4()),
        "surface": "home",
        "request_id": "req-busqueda",
        "payload": body,
    }


def post(client, user, *sent):
    return client.post("/events", json={"user_id": user, "events": list(sent)})


def test_the_three_events_are_saved_with_their_question_answer_and_search(client, db):
    response = post(
        client,
        PERSON,
        survey("survey_shown", mochi=True),
        survey(answer="en_parte", mochi=True),
        survey("survey_shown", question="p3", trigger="porque"),
        survey(question="p3", answer=4, trigger="porque"),
        survey("survey_dismissed", trigger="abandono"),
    )
    assert response.status_code == 200 and response.json() == {"guardados": 5}
    rows = db.execute(
        """SELECT type, payload ->> 'question', payload -> 'answer', payload ->> 'trigger', request_id, surface
           FROM app_events WHERE user_id = %s ORDER BY event_id""",
        (PERSON,),
    ).fetchall()
    assert rows == [
        ("survey_shown", "p1", None, "busqueda", "req-busqueda", "home"),
        ("survey_answer", "p1", "en_parte", "busqueda", "req-busqueda", "home"),
        ("survey_shown", "p3", None, "porque", "req-busqueda", "home"),
        ("survey_answer", "p3", 4, "porque", "req-busqueda", "home"),
        ("survey_dismissed", "p1", None, "abandono", "req-busqueda", "home"),
    ]


def test_the_p2_takes_yes_or_no_with_the_trigger_of_the_p1(client, db):
    response = post(
        client,
        PERSON,
        survey("survey_shown", question="p2", mochi=False),
        survey(question="p2", answer="si", mochi=False),
        survey("survey_shown", question="p2", trigger="abandono"),
        survey(question="p2", answer="no", trigger="abandono"),
        survey("survey_dismissed", question="p2", trigger="carro"),
    )
    assert response.status_code == 200 and response.json() == {"guardados": 5}
    rows = db.execute(
        """SELECT type, payload ->> 'answer', payload ->> 'trigger' FROM app_events
           WHERE user_id = %s AND payload ->> 'question' = 'p2' ORDER BY event_id""",
        (PERSON,),
    ).fetchall()
    assert rows == [
        ("survey_shown", None, "busqueda"),
        ("survey_answer", "si", "busqueda"),
        ("survey_shown", None, "abandono"),
        ("survey_answer", "no", "abandono"),
        ("survey_dismissed", None, "carro"),
    ]


@pytest.mark.parametrize(
    "event",
    [
        survey(answer="quizas"),  # la p1 solo acepta Sí, En parte o No
        survey(answer=3),  # un número no es una respuesta de la p1
        survey(answer=None),
        survey(question="p3", answer="si"),  # la p3 es de 1 a 5
        survey(question="p3", answer=6),
        survey(question="p3", answer=0),
        survey(question="p3", answer=True),  # True no es un 1
        survey(question="p3", answer=3.5),
        survey(question="p3", answer=[3]),
        survey(question="p2", answer="en_parte"),  # la p2 es Sí o No
        survey(question="p2", answer=1),
        survey(question="p2", answer=None),
        survey(question="p4"),
        survey("survey_shown", question=None),
        survey(trigger="checkout"),  # nunca sale en el pago
        survey("survey_dismissed", trigger=None),
    ],
)
def test_answers_questions_and_triggers_off_the_list_reject_the_batch(client, db, event):
    response = post(client, PERSON, {"type": "app_open", "session_id": "s-enc"}, event)
    assert response.status_code in (400, 422)
    assert db.execute("SELECT count(*) FROM app_events").fetchone()[0] == 0  # el lote entero queda fuera


def test_delete_my_data_takes_the_answers_with_the_person(client, db):
    post(client, PERSON, survey("survey_shown"), survey(), survey("survey_dismissed"))
    assert client.delete(f"/profile/{PERSON}").status_code == 200
    assert db.execute("SELECT count(*) FROM app_events WHERE type LIKE 'survey%'").fetchone()[0] == 0


def test_the_purge_of_inactive_people_takes_them_too(client, db):
    post(client, PERSON, survey("survey_shown"), survey())
    db.execute("UPDATE app_events SET ts = now() - interval '200 days'")
    db.execute("UPDATE app_users SET created_at = now() - interval '200 days'")
    assert events.purge_inactive_users(db, 180) == 1
    assert db.execute("SELECT count(*) FROM app_events").fetchone()[0] == 0


def _event(user, kind, question="p1", answer=None, trigger="busqueda", mochi=None, minutes=0, source="prototype"):
    payload = {"question": question, "trigger": trigger}
    if answer is not None:
        payload["answer"] = answer
    if mochi is not None:
        payload["mochi"] = mochi
    return events.Event(user, "s1", kind, ts=NOW + timedelta(minutes=minutes), payload=payload)


def _answered(user, answer, trigger="busqueda", mochi=True, minutes=0):
    return [
        _event(user, "survey_shown", trigger=trigger, mochi=mochi, minutes=minutes),
        _event(user, "survey_answer", answer=answer, trigger=trigger, mochi=mochi, minutes=minutes + 1),
    ]


EMPTY = {
    "mostradas": 0,
    "respondidas": 0,
    "cerradas": 0,
    "personas": 0,
    "respuesta_pct": None,
    "si": 0,
    "en_parte": 0,
    "no": 0,
    "si_pct": None,
    "en_parte_pct": None,
    "no_pct": None,
    "p2": {"mostradas": 0, "respondidas": 0, "cerradas": 0, "si": 0, "no": 0, "si_pct": None},
    "p3": {"mostradas": 0, "respondidas": 0, "promedio": None},
}


def test_the_survey_metric_counts_shown_answered_and_the_split_by_trigger_mochi_and_group(db):
    events.record(
        db,
        [
            *_answered("u1", "si"),
            _event("u1", "survey_shown", question="p2", mochi=True, minutes=1),
            _event("u1", "survey_answer", question="p2", answer="si", mochi=True, minutes=1),
            _event("u1", "survey_shown", question="p3", trigger="porque", mochi=True, minutes=2),
            _event("u1", "survey_answer", question="p3", answer=4, trigger="porque", mochi=True, minutes=3),
            *_answered("u2", "en_parte", trigger="carro"),
            _event("u2", "survey_shown", question="p2", trigger="carro", mochi=True, minutes=1),
            _event("u2", "survey_answer", question="p2", answer="no", trigger="carro", mochi=True, minutes=1),
            _event("u2", "survey_shown", question="p3", trigger="porque", mochi=True, minutes=2),
            _event("u2", "survey_answer", question="p3", answer=5, trigger="porque", mochi=True, minutes=3),
            *_answered("u3", "no", trigger="abandono", mochi=False),  # tras un No, sin p2
            _event("u4", "survey_shown", trigger="abandono", mochi=False),
            _event("u4", "survey_dismissed", trigger="abandono", mochi=False, minutes=1),
            *_answered("u6", "si", trigger="carro", mochi=False, minutes=5),
            _event("u6", "survey_shown", question="p2", trigger="carro", mochi=False, minutes=7),
            _event("u6", "survey_dismissed", question="p2", trigger="carro", mochi=False, minutes=8),
            _event("u5", "survey_shown"),  # sin responder ni cerrar, y sin decir si Mochi estaba
        ],
    )
    # Dos personas con variante de `ofertas_control` desde antes de la pregunta; la de u5 llegó después: no cuenta.
    for user, variant in (("u1", experiments.TREATMENT), ("u3", experiments.CONTROL), ("u5", experiments.CONTROL)):
        experiments.assign(db, user, experiments.OFFERS_CONTROL, variant)
    db.execute("UPDATE experiment_assignments SET assigned_at = %s", (NOW - timedelta(days=1),))
    db.execute("UPDATE experiment_assignments SET assigned_at = %s WHERE user_id = 'u5'", (NOW + timedelta(days=1),))
    events.record(db, [*_answered("x1", "si")], source="synthetic")  # otra fuente: no se mezcla

    result = queries.survey(db, "prototype")

    assert result["total"] == {
        **EMPTY,
        "mostradas": 6,
        "respondidas": 4,
        "cerradas": 1,
        "personas": 6,
        "respuesta_pct": 66.7,
        "si": 2,
        "en_parte": 1,
        "no": 1,
        "si_pct": 50.0,
        "en_parte_pct": 25.0,
        "no_pct": 25.0,
        # La p2 no cuenta como una p1: sus mostradas, respondidas y cerradas van aparte (la de u6 se cerró).
        "p2": {"mostradas": 3, "respondidas": 2, "cerradas": 1, "si": 1, "no": 1, "si_pct": 50.0},
        "p3": {"mostradas": 2, "respondidas": 2, "promedio": 4.5},
    }
    by_trigger = {row.pop("motivo"): row for row in result["por_motivo"]}
    assert set(by_trigger) == {"abandono", "busqueda", "carro", "porque"}
    assert by_trigger["abandono"] == {
        **EMPTY,
        "mostradas": 2,
        "respondidas": 1,
        "cerradas": 1,
        "personas": 2,
        "respuesta_pct": 50.0,
        "no": 1,
        "si_pct": 0.0,
        "en_parte_pct": 0.0,
        "no_pct": 100.0,
    }
    assert by_trigger["carro"]["p2"] == {
        "mostradas": 2,
        "respondidas": 1,
        "cerradas": 1,
        "si": 0,
        "no": 1,
        "si_pct": 0.0,
    }
    assert by_trigger["porque"]["p3"] == {"mostradas": 2, "respondidas": 2, "promedio": 4.5}
    assert by_trigger["porque"]["mostradas"] == 0  # la p3 no cuenta como una p1 mostrada
    assert [(row["mochi"], row["mostradas"], row["si"], row["no"]) for row in result["por_mochi"]] == [
        (False, 3, 1, 1),
        (True, 2, 1, 0),
    ]
    assert [(row["variante"], row["mostradas"], row["respondidas"]) for row in result["por_grupo"]] == [
        (experiments.CONTROL, 1, 1),
        (experiments.TREATMENT, 1, 1),
    ]
    assert queries.survey(db, "synthetic")["total"]["si"] == 1


def test_without_answers_the_survey_metric_is_all_zero_and_no_rates(db):
    assert queries.survey(db, "prototype") == {"total": EMPTY, "por_motivo": [], "por_mochi": [], "por_grupo": []}


def test_the_survey_metric_is_in_the_panel_api(db):
    def conn_override():
        yield db

    api.app.dependency_overrides[api.get_conn] = conn_override
    try:
        response = OwnerClient(api.app).get("/analytics/encuesta", params={"source": "prototype"})
    finally:
        api.app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {"source": "prototype", "data": queries.survey(db, "prototype")}
