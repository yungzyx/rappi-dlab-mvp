"""Evita que el equipo se duerma durante una corrida larga (`caffeinate`, solo macOS)."""

import logging
import os
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager

log = logging.getLogger(__name__)


@contextmanager
def keep_awake() -> Iterator[None]:
    """Mientras dure el bloque, `caffeinate` impide el reposo; se detiene solo cuando termina este proceso."""
    caffeinate = shutil.which("caffeinate")
    if not caffeinate:
        yield
        return
    process = subprocess.Popen([caffeinate, "-i", "-w", str(os.getpid())])
    log.info("Equipo despierto mientras dure la corrida (caffeinate)")
    try:
        yield
    finally:
        process.terminate()
        process.wait(timeout=5)  # sin esto, caffeinate queda como proceso zombi hasta que termina el comando
