import logging

from rappi_ia.cli import configure_logging


def test_model_downloads_do_not_flood_the_weekly_log():
    """Cada carga de modelo hacía ~20 peticiones a huggingface.co, cada una una línea INFO: tapaban los errores al
    final de launchd.err.log (lo que muestra `make schedule-status`)."""
    configure_logging(verbose=False)
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    configure_logging(verbose=True)  # con -v sí se ven
    assert logging.getLogger("httpx").getEffectiveLevel() <= logging.DEBUG
