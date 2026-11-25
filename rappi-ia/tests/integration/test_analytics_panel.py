"""Las rutas del panel que juntan lo que estaba repartido: la ficha por vertical, las audiencias para campañas (con
su lista de ids y su cambio de tamaño) y el ritmo del piloto (asignaciones y respuestas a la pregunta de la H3)."""

from datetime import UTC, date, datetime, timedelta
from hashlib import md5

from owner_client import OwnerClient
from rappi_ia.analytics import queries
from rappi_ia.api import app as api
from rappi_ia.concepts.store import seed_taxonomy
from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.events import experiments as exp
from rappi_ia.events import store as events

T0 = datetime(2026, 9, 1, 12, tzinfo=UTC)  # martes
LINE = {"entity_type": "catalog_item", "entity_id": "1", "concept_id": "snacks-salados", "unit_price": 1000}


def _order(db, user, day, vertical, cart=None, concept=None):
    cart = cart or f"c-{user}-{day}-{vertical}"
    line = LINE if concept is None else {**LINE, "concept_id": concept}
    events.record_order(db, user, f"s-{day}", cart, vertical, [line], ts=T0 + timedelta(days=day))
    return cart


def _event(user, day, kind, **fields):
    return events.Event(user, f"s-{day}", kind, ts=T0 + timedelta(days=day), **fields)


def _cut(db, day):
    """La fecha de corte de la fuente es su último evento."""
    events.record(db, [_event("z", day, "app_open")])


def test_verticals_side_by_side_with_exact_numbers(db, monkeypatch):
    seed_taxonomy(db, load_taxonomy())
    paid = _order(db, "u1", 65, "restaurantes")
    _order(db, "u1", 68, "restaurantes")
    _order(db, "u1", 66, "turbo")
    _order(db, "u2", 20, "restaurantes")
    _order(db, "u2", 60, "restaurantes")
    _order(db, "u3", 15, "restaurantes")
    _order(db, "u9", 5, "restaurantes")  # hace más de 60 días: no cuenta
    events.record(
        db,
        [
            # Tres carros con algo de Restaurantes: uno pagado, uno dejado hace días y uno de recién (no abandonado).
            _event("u1", 65, "cart_add", vertical="restaurantes", cart_id=paid),
            _event("u2", 62, "cart_add", vertical="restaurantes", cart_id="c-dejado"),
            _event("u3", 69.9, "cart_add", vertical="restaurantes", cart_id="c-recien"),
            # Cuatro búsquedas en Restaurantes, una sin resultado; la de un concepto sensible no entra.
            _event("u1", 64, "search", vertical="restaurantes", concept_id="pizza", query="a", unmet=True),
            *[_event("u2", 64, "search", vertical="restaurantes", concept_id="pizza", query="a", unmet=False)] * 3,
            _event("u3", 64, "search", vertical="restaurantes", concept_id="medicamentos", query="a", unmet=True),
        ],
    )
    _cut(db, 70)
    db.commit()

    hidden = queries.verticals(db, "prototype")
    assert (hidden["verticales"], hidden["bajo_el_minimo"]) == ([], 2)  # 3 y 1 personas: bajo el mínimo de 20

    monkeypatch.setattr(queries, "MIN_GROUP_USERS", 1)
    monkeypatch.setattr(queries, "MIN_RATE_CASES", 3)
    ficha = queries.verticals(db, "prototype")
    assert ficha["verticales"] == [
        {
            "vertical": "restaurantes",
            "personas_30d": 2,  # u1 y u2
            "pedidos_30d": 3,
            "cambio_personas_pct": 0,  # antes, u2 y u3
            "cambio_pedidos_pct": 50,  # 3 frente a 2
            "abandono_carrito_pct": 33.3,  # 1 de 3 carros
            "sin_resultado_pct": 25.0,  # 1 de 4 búsquedas
            "combinan_pct": 33.3,  # de u1, u2 y u3, solo u1 pidió además en Turbo
        },
        {
            "vertical": "turbo",
            "personas_30d": 1,
            "pedidos_30d": 1,
            "cambio_personas_pct": None,  # antes no hubo pedidos
            "cambio_pedidos_pct": None,
            "abandono_carrito_pct": None,  # sin carros con algo de Turbo
            "sin_resultado_pct": None,
            "combinan_pct": None,  # una persona: bajo el mínimo de casos
        },
    ]
    assert (ficha["bajo_el_minimo"], ficha["dias"], ficha["dias_combinacion"]) == (0, 30, 60)
    assert queries.verticals(db, "synthetic")["verticales"] == []  # nunca mezcla fuentes


def test_a_cancelled_order_is_not_in_the_verticals(db, monkeypatch):
    seed_taxonomy(db, load_taxonomy())
    monkeypatch.setattr(queries, "MIN_GROUP_USERS", 1)
    _order(db, "u1", 65, "restaurantes")
    _order(db, "u1", 66, "turbo")
    db.execute("UPDATE app_orders SET status = 'cancelado', cancelled_at = ts WHERE vertical = 'turbo'")
    _cut(db, 70)
    db.commit()

    assert [row["vertical"] for row in queries.verticals(db, "prototype")["verticales"]] == ["restaurantes"]


def test_audiences_follow_their_rules_and_count_who_accepts_notifications(db, monkeypatch):
    seed_taxonomy(db, load_taxonomy())
    for day in (80, 90):
        _order(db, "habito", day, "restaurantes")  # solo Restaurantes, 2 compras en 30 días
    _order(db, "una-vez", 50, "restaurantes")  # solo Restaurantes, pero sin hábito
    _order(db, "probo", 60, "restaurantes")
    _order(db, "probo", 85, "turbo")  # un pedido en Turbo
    _order(db, "pro", 90, "supermercado")  # Pro, una vertical
    _order(db, "pro-licores", 90, "licores")  # Pro, pero su única vertical es Licores: fuera
    for day, vertical in ((88, "restaurantes"), (89, "turbo"), (90, "supermercado")):
        _order(db, "combina", day, vertical)
    for day in (50, 60, 70):
        _order(db, "riesgo", day, "supermercado")  # ritmo de 10 días y 30 sin pedir: en riesgo
        # En riesgo también, pero con nada que Mochi pueda volver a ofrecer: cerveza (+18), en Licores o en el súper,
        # y algo ofrecible pero pedido en Farmacia.
        _order(db, "riesgo-licores", day, "licores", concept="cerveza")
        _order(db, "riesgo-cerveza", day, "supermercado", concept="cerveza")
        _order(db, "riesgo-farmacia", day, "farmacia")
    _cut(db, 100)
    db.execute("UPDATE app_users SET pro = true WHERE user_id IN ('pro', 'pro-licores')")
    db.execute("UPDATE app_users SET consent_notifications = true WHERE user_id IN ('habito', 'riesgo')")
    db.commit()

    hidden = queries.audiences(db, "prototype")
    assert (hidden["audiencias"], hidden["bajo_el_minimo"], hidden["minimo_personas"]) == ([], 5, 20)

    monkeypatch.setattr(queries, "MIN_GROUP_USERS", 1)
    shown = queries.audiences(db, "prototype")
    assert [(a["id"], a["personas"], a["aceptan_avisos"]) for a in shown["audiencias"]] == [
        ("solo-restaurantes-con-habito", 1, 1),
        ("en-riesgo-con-concepto", 1, 1),  # solo "riesgo": los otros tres no tienen qué ofrecerles
        ("probo-turbo-una-vez", 2, 0),  # "probo" y "combina": los dos con un solo pedido en Turbo
        ("pro-una-vertical", 1, 0),
        ("combina-3-o-mas", 1, 0),
    ]
    assert shown["bajo_el_minimo"] == 0
    assert shown["dias_cambio"] == 28
    assert all(a["nombre"] and a["regla"] and a["ofrecer"] for a in shown["audiencias"])
    assert queries.audiences(db, "synthetic")["audiencias"] == []  # nunca mezcla fuentes


def test_an_audience_size_is_compared_with_four_weeks_before(db, monkeypatch):
    """Cuatro semanas antes, con la misma regla y solo lo pedido hasta entonces: "combina" sumó su tercera vertical
    después, y "riesgo" todavía estaba en su ritmo."""
    seed_taxonomy(db, load_taxonomy())
    for user in ("a", "b"):
        for day in (55, 60, 85, 90):
            _order(db, user, day, "restaurantes")  # con hábito antes y ahora
    _order(db, "c", 85, "restaurantes")
    _order(db, "c", 90, "restaurantes")  # con hábito solo ahora
    for day, vertical in ((60, "restaurantes"), (65, "turbo"), (90, "supermercado")):
        _order(db, "combina", day, vertical)  # 2 verticales al corte de antes, 3 hoy
    for day in (50, 60, 70):
        _order(db, "riesgo", day, "supermercado")  # en riesgo hoy (día 100), al día (72) no
    _cut(db, 100)
    db.commit()

    monkeypatch.setattr(queries, "MIN_GROUP_USERS", 1)
    by_id = {a["id"]: a for a in queries.audiences(db, "prototype")["audiencias"]}
    habit = by_id["solo-restaurantes-con-habito"]
    assert (habit["personas"], habit["personas_antes"], habit["cambio_personas_pct"]) == (3, 2, 50)
    # Antes no había nadie: sin tamaño antes, sin cambio.
    assert (by_id["combina-3-o-mas"]["personas_antes"], by_id["combina-3-o-mas"]["cambio_personas_pct"]) == (None, None)
    assert by_id["en-riesgo-con-concepto"]["personas_antes"] is None

    # Bajo el mínimo entonces, su tamaño de antes no sale: diría demasiado de pocas personas.
    monkeypatch.setattr(queries, "MIN_GROUP_USERS", 3)
    [habit] = queries.audiences(db, "prototype")["audiencias"]
    assert (habit["personas"], habit["personas_antes"], habit["cambio_personas_pct"]) == (3, None, None)


def test_an_audience_list_has_pseudonymous_ids_and_only_above_the_minimum(db, monkeypatch):
    for user in ("a", "b", "c"):
        for day in (85, 90):
            _order(db, user, day, "restaurantes")
    _cut(db, 100)
    db.execute("UPDATE app_users SET consent_notifications = true WHERE user_id = 'b'")
    db.commit()

    def conn_override():
        yield db

    api.app.dependency_overrides[api.get_conn] = conn_override
    try:
        client = OwnerClient(api.app)
        path = "/analytics/audiencias/solo-restaurantes-con-habito"
        assert client.get(path, params={"source": "prototype"}).status_code == 404  # 3 personas: bajo el mínimo
        monkeypatch.setattr(queries, "MIN_GROUP_USERS", 3)
        reply = client.get(path, params={"source": "prototype"})
        unknown = client.get("/analytics/audiencias/nadie", params={"source": "prototype"})
        other_source = client.get(path, params={"source": "synthetic"})
    finally:
        api.app.dependency_overrides.clear()

    assert reply.status_code == 200
    body = reply.json()
    assert body["source"] == "prototype"
    data = body["data"]
    assert (data["id"], data["nombre"]) == ("solo-restaurantes-con-habito", "Solo Restaurantes, con hábito")
    expected = [{"usuario": f"u-{md5(user.encode()).hexdigest()[:8]}", "acepta_avisos": user == "b"} for user in "abc"]
    assert data["personas"] == sorted(expected, key=lambda row: row["usuario"])  # el id de `at-risk`, nunca el real
    assert unknown.status_code == 404
    assert other_source.status_code == 404  # nunca mezcla fuentes


def test_the_at_risk_audience_only_uses_what_mochi_may_offer():
    """Las guardias de ofertas mandan: ni alcohol, ni +18, ni bebé, ni salud entran como "algo que pedía"."""
    taxonomy = load_taxonomy().concepts
    assert not queries.is_offerable(taxonomy["cerveza"])
    assert queries.is_offerable(taxonomy["snacks-salados"])


def test_no_audience_offers_a_blocked_vertical():
    """Lo que se ofrece a una audiencia es fijo: nunca Farmacia ni Licores (offers/guards.py)."""
    for audience in queries.AUDIENCES:
        assert not any(word in audience["ofrecer"].lower() for word in ("farmacia", "licores", "alcohol"))


def _assign(db, user, day, variant):
    events.record(db, [_event(user, day, "app_open")])
    db.execute(
        """INSERT INTO experiment_assignments (user_id, experiment_id, variant, assigned_at, source)
           VALUES (%s, %s, %s, %s, 'prototype')""",
        (user, exp.OFFERS_CONTROL, variant, T0 + timedelta(days=day)),
    )


def test_the_pilot_pace_counts_assignments_by_complete_week(db):
    params = {"source": "prototype", "offers": exp.OFFERS_CONTROL}
    variants = [exp.TREATMENT, exp.CONTROL]
    for n in range(3):
        _assign(db, f"t{n}", 0, exp.TREATMENT)  # semana del lunes 31-08
    _assign(db, "c0", 2, exp.CONTROL)
    db.commit()
    _cut(db, 8)  # miércoles 09-09: solo una semana completa
    assert queries._assignment_pace(db, params, variants) == {
        "semanas": [{"semana": date(2026, 8, 31), "tratamiento": 3, "control": 1}],
        "por_semana": None,  # con una semana no hay ritmo que decir
        "semanas_promedio": 4,
    }

    for n in range(2):
        _assign(db, f"t1{n}", 14, exp.TREATMENT)  # semana del 14-09 (la del 07-09 queda sin nadie)
    for n in range(5):
        _assign(db, f"t2{n}", 21, exp.TREATMENT)  # semana del 21-09: en curso al corte, no cuenta
    _cut(db, 22)
    db.commit()
    pace = queries._assignment_pace(db, params, variants)
    assert pace["semanas"] == [
        {"semana": date(2026, 8, 31), "tratamiento": 3, "control": 1},
        {"semana": date(2026, 9, 7), "tratamiento": 0, "control": 0},
        {"semana": date(2026, 9, 14), "tratamiento": 2, "control": 0},
    ]
    assert pace["por_semana"] == {"tratamiento": 1.7, "control": 0.3}
    assert queries._assignment_pace(db, {**params, "source": "synthetic"}, variants)["semanas"] == []


def test_the_experiments_answer_carries_the_pace(db):
    [offers] = [e for e in queries.experiment_results(db, "prototype")["experimentos"] if e["id"] == exp.OFFERS_CONTROL]
    assert offers["ritmo"] == {"semanas": [], "por_semana": None, "semanas_promedio": 4}
    assert offers["ritmo_encuesta"] == {"semanas": [], "por_semana": None, "semanas_promedio": 4}


def _answer(db, user, day, answer="si", question="p1"):
    payload = {"question": question, "trigger": "busqueda", "answer": answer}
    events.record(db, [_event(user, day, "survey_answer", payload=payload)])


def test_the_h3_pace_counts_answers_by_complete_week_and_group(db):
    """La H3 avanza con respuestas a la p1, con la variante que la persona ya tenía al responder."""
    params = {"source": "prototype", "offers": exp.OFFERS_CONTROL}
    variants = [exp.TREATMENT, exp.CONTROL]
    _assign(db, "t", 0, exp.TREATMENT)
    _assign(db, "c", 0, exp.CONTROL)
    _answer(db, "t", 1)
    _answer(db, "t", 2, "no")
    _answer(db, "t", 2, question="p3", answer=4)  # otra pregunta: no cuenta
    _answer(db, "c", 3)
    _answer(db, "sin-grupo", 3)  # sin variante: no cuenta
    _answer(db, "t", 15)  # semana del 14-09 (la del 07-09 queda sin nada)
    _answer(db, "c", 22)  # semana del 21-09: en curso al corte
    _cut(db, 22)
    db.commit()
    assert queries._survey_pace(db, params, variants) == {
        "semanas": [
            {"semana": date(2026, 8, 31), "tratamiento": 2, "control": 1},
            {"semana": date(2026, 9, 7), "tratamiento": 0, "control": 0},
            {"semana": date(2026, 9, 14), "tratamiento": 1, "control": 0},
        ],
        "por_semana": {"tratamiento": 1.0, "control": 0.3},
        "semanas_promedio": 4,
    }
    [offers] = [e for e in queries.experiment_results(db, "prototype")["experimentos"] if e["id"] == exp.OFFERS_CONTROL]
    assert offers["ritmo_encuesta"] == queries._survey_pace(db, params, variants)
    assert queries._survey_pace(db, {**params, "source": "synthetic"}, variants)["semanas"] == []
