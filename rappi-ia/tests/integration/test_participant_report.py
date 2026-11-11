"""`rappi-ia resumen-prueba` contra `rappi_ia_test`: el resumen de una prueba con usuarios (docs/prueba-usuarios.md).

Solo personas del prototipo y solo lectura: una simulada sembrada junto a ellas nunca aparece, ni pidiendo su id.
"""

from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from rappi_ia import cli
from rappi_ia.analytics import participant_report as report
from rappi_ia.concepts.store import seed_taxonomy
from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.events import store as events

NOW = datetime(2026, 11, 3, 18, 0, tzinfo=UTC)  # 15:00 en Santiago
ONCE = events.SessionInfo(app_version="1.0.0", platform="web", mode="propuesta", entry="directa")


def _at(minutes: float) -> datetime:
    return NOW + timedelta(minutes=minutes)


def _participant(db, user="proto-aaaa"):
    """Una sesión de 12 minutos con las 6 tareas del guion: un error de tipeo corregido, una búsqueda sin resultado,
    "algo para la once" a Mochi, tres ofertas (aceptada, "Después" y sin respuesta; la aceptada con la fuente de su
    "¿Por qué?", que la persona abrió), ocultar y traer a Mochi, y dos pedidos (uno cancelado)."""
    e = events.Event
    events.record(
        db,
        [
            e(user, "s1", "app_open", ts=_at(0)),
            e(
                user,
                "s1",
                "search",
                ts=_at(1),
                query="cervesa",
                results=5,
                unmet=False,
                payload={"alcance": "global", "fuente": "tipeada", "corregida": "cerveza"},
            ),
            e(user, "s1", "search", ts=_at(2), query="zzzqqq", results=0, unmet=True, payload={"fuente": "tipeada"}),
            e(
                user,
                "s1",
                "ask",
                ts=_at(3),
                query="algo para la once",
                results=4,
                unmet=False,
                concept_id="te",
                surface="agent",
            ),
            e(
                user,
                "s1",
                "suggestion_shown",
                ts=_at(4),
                concept_id="cerveza",
                vertical="licores",
                origin="agent-recompra",
                surface="home",
                payload={"basis": ["recompra"]},
            ),
            e(
                user,
                "s1",
                "offer_why_open",
                ts=_at(4.5),
                concept_id="cerveza",
                origin="agent-recompra",
                surface="home",
                payload={"basis": ["recompra"]},
            ),
            e(
                user,
                "s1",
                "suggestion_accepted",
                ts=_at(5),
                concept_id="cerveza",
                vertical="licores",
                origin="agent-recompra",
                surface="home",
            ),
            e(
                user,
                "s1",
                "suggestion_shown",
                ts=_at(6),
                concept_id="vino",
                vertical="licores",
                origin="agent-volver",
                payload={"kind": "volver"},
            ),
            e(
                user,
                "s1",
                "suggestion_dismissed",
                ts=_at(6.5),
                concept_id="vino",
                vertical="licores",
                origin="agent-volver",
                payload={"kind": "volver"},
            ),
            e(
                user,
                "s1",
                "suggestion_shown",
                ts=_at(7),
                concept_id="sushi",
                vertical="restaurantes",
                origin="agent-vertical_por_probar",
            ),
            # Un "Para ti" de una tienda no es de Mochi si no viene de su tarjeta: este, de la lista de la tienda, no.
            e(
                user,
                "s1",
                "cart_add",
                ts=_at(7.5),
                concept_id="pizza",
                vertical="restaurantes",
                origin="para-ti",
                surface="store",
            ),
            e(user, "s1", "vertical_open", ts=_at(8), vertical="licores", origin="accesos", surface="home"),
            e(user, "s1", "vertical_open", ts=_at(8.5), vertical="restaurantes", origin="accesos", surface="home"),
            e(
                user,
                "s1",
                "agent_visibility",
                ts=_at(9),
                origin="menu-mochi",
                surface="agent",
                payload={"visible": False},
            ),
            e(user, "s1", "agent_visibility", ts=_at(10), origin="cuenta", payload={"visible": True}),
        ],
        session=ONCE,
    )
    beer = {
        "entity_type": "catalog_item",
        "entity_id": "1",
        "concept_id": "cerveza",
        "unit_price": 2190,
        "qty": 2,
        "from_suggestion": True,
    }
    events.record_order(db, user, "s1", "c1", "licores", [beer], ts=_at(11))
    dish = {"entity_type": "menu_item", "entity_id": "9", "concept_id": "sushi", "unit_price": 8990}
    events.record_order(db, user, "s1", "c2", "restaurantes", [dish], ts=_at(11.5))
    events.record(
        db,
        [
            e(
                user,
                "s1",
                "order_cancelled",
                ts=_at(12),
                cart_id="c2",
                vertical="restaurantes",
                payload={"reason": "ya_no", "stage": "antes_de_tienda"},
            )
        ],
    )


def test_a_repeated_offer_is_accepted_once_and_a_withheld_one_is_marked(db, tmp_path, test_url, monkeypatch):
    """La misma oferta mostrada dos veces y aceptada una sola vez sale una aceptada y una sin respuesta (lo que pasó
    después de cada mostrada llega hasta la siguiente), y una retenida al grupo de control sale como tal."""
    seed_taxonomy(db, load_taxonomy())
    e = events.Event
    user = "proto-dddd"
    shown = dict(concept_id="cerveza", vertical="licores", origin="agent-recompra")
    events.record(
        db,
        [
            e(user, "s1", "suggestion_shown", ts=_at(1), **shown),
            e(user, "s1", "suggestion_shown", ts=_at(2), **shown),
            e(user, "s1", "suggestion_accepted", ts=_at(3), **shown),
            e(
                user,
                "s1",
                "offer_withheld",
                ts=_at(4),
                concept_id="sushi",
                vertical="restaurantes",
                origin="agent-volver",
            ),
        ],
        session=ONCE,
    )
    db.commit()
    monkeypatch.setenv("DATABASE_URL", test_url)

    _run(tmp_path, user)

    text = (tmp_path / f"{user}.md").read_text(encoding="utf-8")
    assert "3 oferta(s): 1 sin respuesta registrada, 1 aceptada, 1 retenida (grupo de control)." in text
    assert text.count("| Cerveza | Licores | aceptada |") == 1
    assert text.count("| Cerveza | Licores | sin respuesta registrada |") == 1
    assert "| Sushi | Restaurantes | retenida (grupo de control) |" in text


def test_the_journey_says_how_each_vertical_was_reached_without_vertical_open(db, tmp_path, test_url, monkeypatch):
    """Sin ningún `vertical_open` (lo de casi todas las personas): vio un producto de Express desde el buscador y, desde
    el "Para ti" de Mochi, vio y agregó al carro un plato de Restaurantes. El recorrido dice las dos y sus caminos,
    aunque "Abiertas" diga ninguna."""
    seed_taxonomy(db, load_taxonomy())
    e = events.Event
    user = "proto-eeee"
    from_search = dict(vertical="conveniencia", origin="resultados", surface="search")
    from_mochi = dict(concept_id="sushi", vertical="restaurantes", origin="para-ti", surface="agent")
    events.record(
        db,
        [
            e(user, "s1", "search", ts=_at(0), query="doritoz", results=8),
            e(user, "s1", "view_item", ts=_at(1), entity_type="catalog_item", entity_id="1", **from_search),
            e(user, "s1", "view_item", ts=_at(2), entity_type="menu_item", entity_id="9", **from_mochi),
            e(user, "s1", "cart_add", ts=_at(3), entity_type="menu_item", entity_id="9", **from_mochi),
            e(user, "s1", "view_store", ts=_at(4), vertical="conveniencia", origin="agent-carrito", surface="home"),
        ],
        session=ONCE,
    )
    db.commit()
    monkeypatch.setenv("DATABASE_URL", test_url)

    _run(tmp_path, user)

    text = (tmp_path / f"{user}.md").read_text(encoding="utf-8")
    assert "Tocó 2 vertical(es); empezó por Express. Llegó a otra vertical: sí." in text
    assert "| 03-11 15:01 | Express (la primera) | vio un producto | buscador |" in text
    assert "| 03-11 15:02 | Restaurantes | vio un producto | Mochi (para-ti) |" in text
    assert text.count("| Express") == 1  # volver a Express (por Mochi) no es una vertical nueva
    assert "- Abiertas (un acceso de la Home o un botón de Mochi): ninguna." in text


def test_the_journey_names_the_mochi_offer_seen_before_reaching_a_vertical_by_another_path(
    db, tmp_path, test_url, monkeypatch
):
    """Antes, el botón "Ver Súper" de una oferta de Mochi llevaba a la vertical sin dejar `vertical_open`: lo primero
    que toca allí sale de la pantalla de la vertical ("otro"). El recorrido nombra la oferta de Súper que vio justo
    antes, pero no una de hace más de 30 minutos (Licores)."""
    seed_taxonomy(db, load_taxonomy())
    e = events.Event
    user = "proto-ffff"
    events.record(
        db,
        [
            e(user, "s1", "suggestion_shown", ts=_at(0), concept_id="vino", vertical="licores", origin="agent-volver"),
            e(
                user,
                "s1",
                "suggestion_shown",
                ts=_at(40),
                concept_id="leche",
                vertical="supermercado",
                origin="agent-vertical_por_probar",
            ),
            e(user, "s1", "view_store", ts=_at(41), vertical="supermercado", origin="tiendas", surface="vertical"),
            e(user, "s1", "view_store", ts=_at(42), vertical="licores", origin="tiendas", surface="vertical"),
        ],
        session=ONCE,
    )
    db.commit()
    monkeypatch.setenv("DATABASE_URL", test_url)

    _run(tmp_path, user)

    text = (tmp_path / f"{user}.md").read_text(encoding="utf-8")
    assert (
        "| 03-11 15:41 | Súper (la primera) | vio una tienda | otro (vertical, tiendas); antes, oferta de Mochi"
        " (vertical_por_probar) de esa vertical a las 15:40 |"
    ) in text
    assert "| 03-11 15:42 | Licores | vio una tienda | otro (vertical, tiendas) |" in text


def test_the_journey_says_mochi_when_the_offer_button_opened_the_vertical(db, tmp_path, test_url, monkeypatch):
    """ "Ver …" de una oferta de Mochi deja `vertical_open` con el origen de la oferta: el recorrido dice "Mochi
    (carrito)", sin la pista de los 30 minutos."""
    seed_taxonomy(db, load_taxonomy())
    e = events.Event
    user = "proto-gggg"
    events.record(
        db,
        [
            e(
                user,
                "s1",
                "suggestion_shown",
                ts=_at(0),
                concept_id="snacks-salados",
                vertical="conveniencia",
                origin="agent-carrito",
                surface="home",
            ),
            e(user, "s1", "vertical_open", ts=_at(1), vertical="conveniencia", origin="agent-carrito", surface="home"),
            e(user, "s1", "view_store", ts=_at(2), vertical="conveniencia", origin="tiendas", surface="vertical"),
        ],
        session=ONCE,
    )
    db.commit()
    monkeypatch.setenv("DATABASE_URL", test_url)

    _run(tmp_path, user)

    text = (tmp_path / f"{user}.md").read_text(encoding="utf-8")
    assert "| abrió la vertical | Mochi (carrito) |" in text
    assert "Mochi (carrito); antes" not in text


def test_the_journey_paths():
    """El camino sale del origen: una oferta de Mochi con su momento, el "Para ti" de su tarjeta (no el de una tienda),
    el buscador, un acceso de la Home, un botón del panel de Mochi, y lo demás tal cual."""
    path = report._path
    assert path({"type": "cart_add", "origin": "agent-vertical_por_probar", "surface": "home"}) == (
        "Mochi (vertical_por_probar)"
    )
    assert path({"type": "order", "origin": "agent-autopedido"}) == "Mochi (autopedido)"
    assert path({"type": "view_item", "origin": "para-ti", "surface": "agent"}) == "Mochi (para-ti)"
    assert path({"type": "view_item", "origin": "para-ti", "surface": "store"}) == "otro (store, para-ti)"
    assert path({"type": "view_store", "origin": "resultados-tiendas", "surface": "search"}) == "buscador"
    assert path({"type": "vertical_open", "origin": "accesos-grandes", "surface": "home"}) == "acceso de la Home"
    assert path({"type": "vertical_open", "origin": "tambien-en", "surface": "agent"}) == "Mochi (tambien-en)"
    assert path({"type": "view_store", "origin": "cerca-de-ti", "surface": "home"}) == "otro (home, cerca-de-ti)"
    assert path({"type": "order", "origin": None}) == "sin dato"


def test_a_dismissed_offer_says_the_button_of_its_moment():
    """Un rechazo (`suggestion_dismissed`) sale con el botón de su momento: "Ahora no" en el carrito, "Después" en la
    recompra, y "rechazada" a secas en un momento sin botón conocido."""

    def dismissed(origin):
        shown = {"origin": origin, "concept_id": "cerveza", "vertical": "licores", "payload": {}}
        return report._offers([{**shown, "type": "suggestion_shown"}, {**shown, "type": "suggestion_dismissed"}])[0]

    assert dismissed("agent-carrito")["status"] == 'rechazada ("Ahora no")'
    assert dismissed("agent-recompra")["status"] == 'rechazada ("Después")'
    assert dismissed("agent-plan")["status"] == "rechazada"


def test_the_idea_under_a_mochi_answer_is_not_presented_as_the_answer():
    """De una respuesta de Mochi solo queda como mostrada la idea de otra vertical que va debajo (sugerencia cruzada):
    el resumen no la presenta como la respuesta y nombra la vertical de lo que respondió (el `ask` con su mismo
    `request_id`). Sin ese `ask`, el motivo solo dice que es la idea de abajo."""
    asked = {"at": _at(3), "type": "ask", "vertical": "supermercado", "concept_id": "te", "request_id": "r1"}
    idea = {
        "at": _at(3.1),
        "type": "suggestion_shown",
        "vertical": "conveniencia",
        "concept_id": "galletas",
        "payload": {},
        "origin": "agent-ask",
        "request_id": "r1",
    }

    def offer_table(searches):
        p = report.Participant(
            user_id="proto-aaaa",
            created_at=NOW,
            variants={},
            sessions=[],
            searches=searches,
            offers=report._offers([idea]),
            accepted_products=0,
            why_opened=[],
            opened=[],
            touches=[],
            services=[],
            visibility=[],
            orders=[],
        )
        return "\n".join(report._offer_lines(p))

    motive = "idea de otra vertical bajo su respuesta (no la respuesta)"
    assert f"| ask | {motive}; la respuesta fue de Súper | — | Galletas | Express |" in offer_table([asked])
    assert f"| ask | {motive} | — | Galletas | Express |" in offer_table([{**asked, "request_id": "otra"}])


def test_an_offer_that_went_away_by_itself_is_not_a_rejection_nor_no_answer():
    """El globo que se fue solo (`suggestion_dismissed` con `payload.kind` "expirada") sale "se fue sola"; si después
    la rechazó o la aceptó (la misma oferta volvió), vale eso."""
    shown = {"origin": "agent-carrito", "concept_id": "cerveza", "vertical": "licores", "payload": {}}
    expired = {**shown, "type": "suggestion_dismissed", "payload": {"kind": events.EXPIRED_KIND}}

    def status(*after):
        return report._offers([{**shown, "type": "suggestion_shown"}, *after])[0]["status"]

    assert status(expired) == "se fue sola"
    assert status(expired, {**shown, "type": "suggestion_dismissed"}) == 'rechazada ("Ahora no")'
    assert status(expired, {**shown, "type": "suggestion_accepted"}) == "aceptada"
    assert status() == "sin respuesta registrada"


def _synthetic(db, user="syn-0001"):
    """Una persona simulada con su propia búsqueda y pedido, creada hoy como las del prototipo."""
    events.ensure_user(db, user, "synthetic")
    events.record(
        db,
        [
            events.Event(user, "x1", "search", ts=_at(1), query="consulta simulada", results=3),
            events.Event(user, "x1", "suggestion_shown", ts=_at(2), concept_id="vino", origin="agent-recompra"),
        ],
        source="synthetic",
    )
    line = {"entity_type": "catalog_item", "entity_id": "2", "concept_id": "vino", "unit_price": 5000}
    events.record_order(db, user, "x1", "x1", "licores", [line], source="synthetic", ts=_at(3))


@pytest.fixture
def seeded(db, test_url, monkeypatch):
    seed_taxonomy(db, load_taxonomy())
    _participant(db)
    _synthetic(db)
    db.commit()
    monkeypatch.setenv("DATABASE_URL", test_url)  # el comando abre su conexión: a la base de los tests
    return db


def _run(tmp_path, *args) -> None:
    cli.main(["resumen-prueba", *args, "--salida", str(tmp_path)])


def test_summary_of_a_participant(seeded, tmp_path, capsys):
    _run(tmp_path, "proto-aaaa")

    text = (tmp_path / "proto-aaaa.md").read_text(encoding="utf-8")
    assert "Resumen en" in capsys.readouterr().out
    assert "Experimentos: modo_app = propuesta." in text
    # Sesión: 12 minutos, del app_open a la cancelación, en modo propuesta.
    assert "1 sesión(es), 12 min 00 s en total" in text
    assert "| 03-11-2026 15:00 | 12 min 00 s | propuesta | 18 |" in text
    # Búsquedas: la corregida y la sin resultado, marcadas; la de Mochi también cuenta.
    assert "3 búsqueda(s): 1 sin resultado y 1 corregida(s)" in text
    assert '| 03-11 15:01 | buscador | "cervesa" | 5 | corregida a "cerveza" |' in text
    assert '| 03-11 15:02 | buscador | "zzzqqq" | 0 | sin resultado |' in text
    assert '| 03-11 15:03 | Mochi | "algo para la once" | 4 |  |' in text
    # Ofertas: cada mostrada con lo que pasó, su motivo según el momento y de qué sale su "¿Por qué?" (si lo trae).
    assert '3 oferta(s): 1 aceptada, 1 rechazada ("Después"), 1 sin respuesta registrada.' in text
    assert "Productos agregados al carro desde una oferta: 1." in text
    repeat = '| recompra | lo que suele repetir ("¿Repetimos?") | su ritmo de recompra | Cerveza | Licores | aceptada |'
    assert repeat in text
    assert '| volver (volver) | algo que dejó ("¿Volvemos a…?") | — | Vino | Licores | rechazada ("Después") |' in text
    assert "| vertical_por_probar | una vertical que todavía no prueba | — | Sushi | Restaurantes | sin resp" in text
    # El "¿Por qué?" abierto: cuándo, de qué oferta y de qué sale (nunca su texto).
    assert 'Abrió el "¿Por qué?" 1 vez.' in text
    assert "| 03-11 15:04 | recompra | su ritmo de recompra | Cerveza |" in text
    assert "Pizza" not in text  # el "Para ti" de una tienda (cart_add) no es una oferta de Mochi
    # Recorrido: Restaurantes primero (el carro desde el "Para ti" de una tienda, no de Mochi) y Licores por su acceso.
    assert "Tocó 2 vertical(es); empezó por Restaurantes. Llegó a otra vertical: sí." in text
    # Antes vio la oferta "vertical por probar" de Restaurantes: se nombra, sin afirmar que llegó por ella.
    assert (
        "| 03-11 15:07 | Restaurantes (la primera) | agregó al carro | otro (store, para-ti); antes, oferta de Mochi"
        " (vertical_por_probar) de esa vertical a las 15:07 |"
    ) in text
    assert "| 03-11 15:08 | Licores | abrió la vertical | acceso de la Home |" in text
    # Verticales: las dos abiertas; con pedido solo Licores (el de Restaurantes se canceló).
    assert "- Abiertas (un acceso de la Home o un botón de Mochi): Licores, Restaurantes." in text
    assert "- Con pedido (sin los cancelados): Licores." in text
    # Ocultó a Mochi y lo trajo de vuelta.
    assert "Ocultó a Mochi: sí." in text
    assert "- 03-11 15:09: lo ocultó (desde menu-mochi)" in text
    assert "- 03-11 15:10: lo trajo de vuelta (desde cuenta)" in text
    # Pedidos, con el cancelado marcado.
    assert "| 03-11 15:11 | Licores | $4.380 | 1 (1) | propuesta | confirmado | la persona |" in text
    assert "| 03-11 15:11 | Restaurantes | $8.990 | 1 (0) | propuesta | cancelado | la persona |" in text


def test_a_synthetic_person_is_never_summarized(seeded, tmp_path, capsys):
    """Pedida por su id, la persona simulada se salta con un aviso: ni su archivo ni sus datos en el de otra."""
    _run(tmp_path, "proto-aaaa", "syn-0001", "nadie")

    out = capsys.readouterr().out
    assert "syn-0001: no es una persona del prototipo (o no existe); se salta" in out
    assert "nadie: no es una persona del prototipo (o no existe); se salta" in out
    assert sorted(p.name for p in tmp_path.iterdir()) == ["proto-aaaa.md"]
    text = (tmp_path / "proto-aaaa.md").read_text(encoding="utf-8")
    assert "consulta simulada" not in text
    assert "$5.000" not in text


def test_only_synthetic_ids_exit_without_writing(seeded, tmp_path):
    with pytest.raises(SystemExit, match="No hay personas del prototipo que resumir"):
        _run(tmp_path, "syn-0001")
    assert list(tmp_path.iterdir()) == []


def test_since_takes_the_prototype_people_created_since_then(seeded, tmp_path):
    """`--desde`: las del prototipo creadas desde esa fecha y con algún evento. Una anterior, una que solo abrió la
    sesión (sin eventos) y la simulada, creada hoy, quedan fuera."""
    _participant(seeded, "proto-bbbb")
    seeded.execute("UPDATE app_users SET created_at = '2026-01-15' WHERE user_id = 'proto-bbbb'")
    events.ensure_user(seeded, "proto-cccc")  # POST /session sin nada después
    seeded.commit()

    _run(tmp_path, "--desde", "2026-06-01")

    assert sorted(p.name for p in tmp_path.iterdir()) == ["proto-aaaa.md"]


def test_since_or_ids_but_not_both_nor_neither(seeded, tmp_path):
    with pytest.raises(SystemExit, match="no los dos"):
        _run(tmp_path, "proto-aaaa", "--desde", "2026-06-01")
    with pytest.raises(SystemExit, match="no los dos"):
        _run(tmp_path)
    with pytest.raises(SystemExit, match="Fecha inválida"):
        _run(tmp_path, "--desde", "ayer")


def test_the_command_cannot_write_to_the_database(seeded, tmp_path, monkeypatch):
    """La conexión del comando es de solo lectura: un cambio por error falla en Postgres en vez de escribir."""

    def try_to_write(conn, *args):
        conn.execute("UPDATE app_users SET city = 'Santiago'")

    monkeypatch.setattr(report, "select_users", try_to_write)
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        _run(tmp_path, "proto-aaaa")
    seeded.rollback()
    assert seeded.execute("SELECT count(*) FROM app_users WHERE city IS NOT NULL").fetchone()[0] == 0


def test_since_is_santiago_time_without_a_zone():
    assert report.parse_since("2026-11-03") == datetime(2026, 11, 3, 3, 0, tzinfo=UTC)
    assert report.parse_since("2026-11-03T15:30") == datetime(2026, 11, 3, 18, 30, tzinfo=UTC)
    assert report.parse_since("2026-11-03T15:30+00:00") == datetime(2026, 11, 3, 15, 30, tzinfo=UTC)


def test_overlapping_sessions_count_once():
    """Dos pestañas a la vez no duplican el tiempo: 10:00-10:20 y 10:10-10:30 son 30 minutos; 11:00-11:05, 5 más."""
    t = datetime(2026, 11, 3, 10, tzinfo=UTC)
    sessions = [
        {"started": t, "ended": t + timedelta(minutes=20)},
        {"started": t + timedelta(minutes=10), "ended": t + timedelta(minutes=30)},
        {"started": t + timedelta(minutes=12), "ended": t + timedelta(minutes=15)},
        {"started": t + timedelta(hours=1), "ended": t + timedelta(hours=1, minutes=5)},
    ]
    assert report.active_time(sessions) == timedelta(minutes=35)
