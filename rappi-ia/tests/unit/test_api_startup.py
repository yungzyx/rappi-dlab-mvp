import logging
import subprocess
import sys
import threading

import anyio
import pytest
from fastapi.testclient import TestClient

from rappi_ia import config
from rappi_ia.api import app as api
from rappi_ia.api import deps, prewarm, services
from rappi_ia.db import database_url


def test_startup_loads_services_before_first_request(monkeypatch, caplog):
    """uvicorn solo anuncia «startup complete» con los modelos cargados: la primera petición no paga la carga."""
    monkeypatch.setenv("RAPPI_IA_LIGHT", "1")
    services._load_services.cache_clear()
    try:
        with caplog.at_level(logging.INFO, logger="uvicorn.error"), TestClient(api.app):
            assert services._load_services.cache_info().currsize == 1
        assert "Servicios cargados en" in caplog.text  # en la salida de uvicorn, no en un logger sin handler
    finally:
        services._load_services.cache_clear()


def test_startup_launches_the_prewarm_without_waiting_for_it(monkeypatch):
    """La precarga de los índices de la búsqueda corre en su propio hilo, después de cargar los modelos: la API termina
    de arrancar y responde mientras la precarga sigue."""
    monkeypatch.setenv("RAPPI_IA_LIGHT", "1")
    monkeypatch.setattr(config, "API_PREWARM", True)
    started, release = threading.Event(), threading.Event()
    threads = []

    def slow_prewarm():
        threads.append(threading.current_thread())
        started.set()
        release.wait(10)

    monkeypatch.setattr(prewarm, "prewarm_search_indexes", slow_prewarm)
    services._load_services.cache_clear()
    try:
        with TestClient(api.app) as client:
            assert started.wait(5)
            assert services._load_services.cache_info().currsize == 1  # después de los modelos
            assert client.get("/live").status_code == 200  # arrancó con la precarga todavía corriendo
    finally:
        release.set()
        services._load_services.cache_clear()

    assert len(threads) == 1
    assert threads[0] is not threading.main_thread() and threads[0].daemon  # no retiene el cierre de la API


def test_api_prewarm_0_skips_the_prewarm(monkeypatch):
    monkeypatch.setenv("RAPPI_IA_LIGHT", "1")
    monkeypatch.setattr(config, "API_PREWARM", False)
    calls = []
    monkeypatch.setattr(prewarm, "prewarm_search_indexes", lambda: calls.append(1))
    services._load_services.cache_clear()
    try:
        with TestClient(api.app):
            pass
    finally:
        services._load_services.cache_clear()

    assert calls == []


def test_prewarm_with_the_database_down_only_warns(caplog):
    """Sin Postgres, la precarga anota un aviso y termina: nunca tumba la API."""
    with caplog.at_level(logging.WARNING, logger="rappi_ia.api.prewarm"):
        assert prewarm.prewarm_search_indexes("postgresql://127.0.0.1:1/rappi_ia_test") == []

    assert "No se pudo precargar" in caplog.text


@pytest.mark.parametrize("module", ["rappi_ia.api.deps", "rappi_ia.api.catalog", "rappi_ia.api.app"])
def test_each_api_module_imports_on_its_own(module):
    """El router del catálogo y la app se importan en cualquier orden: `api.catalog` se importaba solo después de
    `api.app` (una importación circular), y el próximo router habría repetido el truco."""
    result = subprocess.run([sys.executable, "-c", f"import {module}"], capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr


def test_api_connections_fail_fast(monkeypatch):
    """Postgres caído o una consulta atascada no dejan a la API (ni al presentador) esperando minutos. Las conexiones
    salen del pool con su nombre y cortan una transacción olvidada abierta."""
    try:
        url = database_url("DATABASE_URL_TEST")
    except RuntimeError:
        pytest.skip("DATABASE_URL_TEST no configurada")
    monkeypatch.setattr(config, "API_POOL_MIN", 1)
    monkeypatch.setattr(config, "API_POOL_MAX", 1)
    pool = deps.make_pool(url)
    pool.open(wait=True)
    monkeypatch.setattr(deps, "_pool", pool)

    async def check():
        connections = api.get_conn()
        conn = await anext(connections)
        try:
            assert conn.execute("SHOW statement_timeout").fetchone()[0] == "5s"  # lo que espera una pantalla
            assert "connect_timeout=3" in conn.info.dsn
            assert conn.execute("SHOW application_name").fetchone()[0] == "rappi-ia-api"
            assert conn.execute("SHOW idle_in_transaction_session_timeout").fetchone()[0] == "10s"
            conn.rollback()  # un endpoint que deshace a mitad no pierde el tope
            assert conn.execute("SHOW statement_timeout").fetchone()[0] == "5s"
            assert api.get_analytics_conn(conn).execute("SHOW statement_timeout").fetchone()[0] == "30s"  # el panel
        finally:
            await connections.aclose()
        connections = api.get_conn()  # la misma conexión del pool vuelve con el tope de una pantalla
        assert (await anext(connections)).execute("SHOW statement_timeout").fetchone()[0] == "5s"
        await connections.aclose()

    try:
        anyio.run(check)
    finally:
        pool.close(timeout=1)


class _FakeModel:
    model_name = "falso"


def _not_cached():
    # Lo que lanza huggingface_hub (LocalEntryNotFoundError, un FileNotFoundError) con HF_HUB_OFFLINE=1
    raise FileNotFoundError("Cannot find an appropriate cached snapshot folder: outgoing traffic has been disabled")


def test_a_text_model_missing_from_the_cache_does_not_stop_the_api(monkeypatch):
    """`make serve` pone HF_HUB_OFFLINE=1 mirando el modelo por defecto: con otro TEXT_EMBEDDING_MODEL en .env que
    no está en caché, la API arranca sin búsqueda semántica y /health lo informa."""
    monkeypatch.delenv("RAPPI_IA_LIGHT", raising=False)
    monkeypatch.setattr("rappi_ia.embeddings.models.text_embedder", _not_cached)
    services._load_services.cache_clear()
    try:
        loaded = services._load_services()
    finally:
        services._load_services.cache_clear()

    assert "outgoing traffic has been disabled" in loaded.missing["busqueda_semantica"]
    assert loaded.embedder is None


def test_services_load_without_image_or_audio_models(monkeypatch):
    """Solo se carga el modelo de texto: sin CLIP, sin Whisper y sin Pillow la API arranca completa."""
    monkeypatch.delenv("RAPPI_IA_LIGHT", raising=False)
    monkeypatch.setattr("rappi_ia.embeddings.models.text_embedder", _FakeModel)
    for module in ("faster_whisper", "PIL", "av"):
        monkeypatch.setitem(sys.modules, module, None)  # importarlos fallaría
    services._load_services.cache_clear()
    try:
        loaded = services._load_services()
    finally:
        services._load_services.cache_clear()

    assert loaded.missing == {}
    assert loaded.embedder is not None
    assert set(loaded.capabilities) == {"busqueda_semantica", "redaccion", "faltantes"}
    assert not hasattr(loaded, "transcriber") and not hasattr(loaded, "photo_reader")
