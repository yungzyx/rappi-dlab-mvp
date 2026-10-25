"""`MOTOR_POBLACION` (config): solo «synthetic» o «prototype»; otra cosa falla al cargar la configuración."""

import importlib

import pytest

from rappi_ia import config


@pytest.fixture(autouse=True)
def _restore_config(monkeypatch):
    yield
    monkeypatch.undo()
    importlib.reload(config)


@pytest.mark.parametrize("value", ["synthetic", "prototype"])
def test_valid_populations_load(monkeypatch, value):
    monkeypatch.setenv("MOTOR_POBLACION", value)
    reloaded = importlib.reload(config)
    assert value == reloaded.MOTOR_POBLACION


def test_an_unknown_population_is_refused(monkeypatch):
    monkeypatch.setenv("MOTOR_POBLACION", "simulada")
    with pytest.raises(RuntimeError, match="MOTOR_POBLACION debe ser 'synthetic' o 'prototype'"):
        importlib.reload(config)
