"""Los pasos de Jev dentro de `make post-refresh`: sin clave, sin adopción o con la API caída no rompen nada."""

import contextlib
import json

import pytest

from conftest import add_product, add_store
from fakes.jev import FakeJev
from rappi_ia import cli, config, jev
from rappi_ia.concepts.pipeline import build_concepts
from rappi_ia.demo.seed import seed_demo

STEPS = (
    ["map-categories", "--jev", "--solo-nuevas"],  # lo que corre `make jev-categorias`
    ["eval-search", "--solo-lexico", "--jev-auto"],  # lo que corre `make eval`
)


@pytest.fixture
def env(db, tmp_path, monkeypatch):
    """Catálogo de prueba, datos y adopción en tmp_path, y el comando conectado a la base de prueba."""
    seed_demo(db)
    add_store(db, 9001, "supermercado", "Súper nuevo")
    add_product(db, 9001, "Peluche oso 30 cm", 9001, "Peluches y muñecas")
    db.commit()
    build_concepts(db)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(jev, "ADOPTION_FILE", tmp_path / "jev-adopcion.json")
    monkeypatch.setattr(config, "TYPESAFE_API_KEY", None)
    monkeypatch.setattr(cli, "connect", lambda: contextlib.nullcontext(db))
    return db


def adopt(tmp_path, **values):
    document = {"categorias": True, "juez": True, "t_auto": 0.85, "model_version": config.JEV_MODEL} | values
    (tmp_path / "jev-adopcion.json").write_text(json.dumps(document), encoding="utf-8")


def no_network(monkeypatch) -> list:
    """Cualquier salida a la API de Jev rompe el test; devuelve la lista de intentos."""
    attempts: list = []

    def refuse(*args, **kwargs):
        attempts.append(args)
        raise AssertionError("no debía llamar a Jev")

    monkeypatch.setattr(jev.JevClient, "_post", refuse)
    return attempts


def jev_writes(db) -> int:
    judgments = db.execute("SELECT count(*) FROM eval_judgments").fetchone()[0]
    mapped = db.execute("SELECT count(*) FROM category_map WHERE method = 'jev'").fetchone()[0]
    return judgments + mapped


@pytest.mark.parametrize("step", STEPS, ids=["jev-categorias", "eval"])
def test_post_refresh_steps_without_key_exit_zero(env, step, tmp_path, capsys, monkeypatch):
    attempts = no_network(monkeypatch)
    adopt(tmp_path)  # aunque la adopción diga que sí, sin clave no hay Jev

    cli.main(step)  # termina sin excepción ni SystemExit: código 0

    assert "TYPESAFE_API_KEY" in capsys.readouterr().out
    assert jev_writes(env) == 0 and attempts == []


@pytest.mark.parametrize("step", STEPS, ids=["jev-categorias", "eval"])
def test_no_adoption_no_jev_even_with_key(env, step, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(config, "TYPESAFE_API_KEY", "sk-de-prueba")
    attempts = no_network(monkeypatch)

    cli.main(step)  # sin archivo de adopción
    adopt(tmp_path, categorias=False, juez=False)
    cli.main(step)  # con un archivo que dice que no

    assert "no está adoptado" in capsys.readouterr().out
    assert jev_writes(env) == 0 and attempts == []


def test_eval_with_jev_auto_and_no_adoption_still_writes_the_report(env, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(config, "TYPESAFE_API_KEY", "sk-de-prueba")
    no_network(monkeypatch)

    cli.main(STEPS[1])

    assert (tmp_path / "data" / "eval" / "busqueda.md").exists()
    assert "Jev" not in (tmp_path / "data" / "eval" / "busqueda.md").read_text(encoding="utf-8")


def test_eval_with_jev_auto_and_adoption_judges_with_jev(env, tmp_path, monkeypatch):
    adopt(tmp_path, categorias=False)
    fake = FakeJev(model=config.JEV_MODEL)
    monkeypatch.setattr(jev, "client_or_none", lambda: fake)

    cli.main(STEPS[1])

    assert fake.calls and env.execute("SELECT count(*) FROM eval_judgments").fetchone()[0] > 0
    assert "Jev" in (tmp_path / "data" / "eval" / "busqueda.md").read_text(encoding="utf-8")


def test_adoption_for_another_model_does_not_judge(env, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(config, "TYPESAFE_API_KEY", "sk-de-prueba")
    adopt(tmp_path, model_version="jev-0.1")
    attempts = no_network(monkeypatch)

    cli.main(STEPS[1])

    assert "jev-0.1" in capsys.readouterr().out and attempts == [] and jev_writes(env) == 0


@pytest.mark.parametrize("step", STEPS, ids=["jev-categorias", "eval"])
def test_api_down_still_exits_zero(env, step, tmp_path, monkeypatch):
    """Adoptado, con clave, pero la API responde 529 o no responde: el paso termina bien sin escribir."""
    monkeypatch.setattr(config, "TYPESAFE_API_KEY", "sk-de-prueba")
    adopt(tmp_path)
    monkeypatch.setattr(jev.JevClient, "_post", lambda self, body: None)

    cli.main(step)

    assert jev_writes(env) == 0
