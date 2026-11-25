"""Las rutas del panel que juntan lo que estaba repartido: la ficha por vertical, las audiencias para campañas y el
ritmo de asignación del piloto."""

from datetime import UTC, date, datetime, timedelta

from rappi_ia.analytics import queries
from rappi_ia.concepts.store import seed_taxonomy
from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.events import experiments as exp
from rappi_ia.events import store as events

T0 = datetime(2026, 9, 1, 12, tzinfo=UTC)  # martes
LINE = {"entity_type": "catalog_item", "entity_id": "1", "concept_id": "snacks-salados", "unit_price": 1000}


def _order(db, user, day, vertical, cart=None):
    cart = cart or f"c-{user}-{day}-{vertical}"
    events.record_order(db, user, f"s-{day}", cart, vertical, [LINE], ts=T0 + timedelta(days=day))
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
        ("en-riesgo-con-concepto", 1, 1),
        ("probo-turbo-una-vez", 2, 0),  # "probo" y "combina": los dos con un solo pedido en Turbo
        ("pro-una-vertical", 1, 0),
        ("combina-3-o-mas", 1, 0),
    ]
    assert shown["bajo_el_minimo"] == 0
    assert all(a["nombre"] and a["regla"] and a["ofrecer"] for a in shown["audiencias"])
    assert queries.audiences(db, "synthetic")["audiencias"] == []  # nunca mezcla fuentes


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
