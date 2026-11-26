"""scripts/qa_motor.py de punta a punta sobre `rappi_ia_test` (el catálogo de prueba), con su conexión de solo lectura:
lo que la API escribe al responder (el contador de las guardias, migración 062) no lo tumba."""

import importlib.util
import os
import sys

import psycopg

from rappi_ia.api import agent as api_agent
from rappi_ia.api import app as api
from rappi_ia.config import PROJECT_ROOT
from rappi_ia.demo.seed import seed_demo
from rappi_ia.events import store as events
from rappi_ia.offers import blocked


def _script():
    spec = importlib.util.spec_from_file_location("qa_motor", PROJECT_ROOT / "scripts" / "qa_motor.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_qa_motor_runs_although_a_guard_takes_something_out(db, test_url, monkeypatch, capsys):
    seed_demo(db)
    line = {"entity_type": "catalog_item", "entity_id": "91004", "concept_id": "cafe", "unit_price": 3990}
    events.record_order(db, "u-qa", "s1", "c1", "supermercado", [{**line, "store_id": 9101}], source="synthetic")
    db.commit()
    real_connect = psycopg.connect
    monkeypatch.setattr(psycopg, "connect", lambda _base, **kwargs: real_connect(test_url, **kwargs))
    monkeypatch.setattr(api_agent, "make_offer", lambda *_a, **_k: blocked.count("alcohol"))  # cada oferta saca algo
    monkeypatch.setattr(blocked, "save", blocked.save)  # el script lo reemplaza: vuelve a ser el de siempre
    monkeypatch.setattr(os, "environ", os.environ.copy())  # el script fija API_SECRET y otras: no quedan
    monkeypatch.setattr(sys, "argv", ["qa_motor.py", "--base", "rappi_ia_test", "--muestra", "5", "--sin-modelo"])

    try:
        _script().main()
    finally:
        api.app.dependency_overrides.clear()

    assert "Personas: 1 simuladas, 0 del prototipo" in capsys.readouterr().out
    assert db.execute("SELECT count(*) FROM guard_blocks").fetchone()[0] == 0  # solo lectura: no anotó nada
