"""Progreso de una corrida larga: `[i/N]` con tiempo transcurrido y estimación de lo que falta."""

import time
from collections.abc import Callable


def _format_duration(seconds: float) -> str:
    minutes, _ = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m" if hours else f"{minutes}m"


class Progress:
    def __init__(self, total: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.total = total
        self._clock = clock
        self._start = clock()

    def label(self, done_before: int) -> str:
        """Etiqueta para el job número `done_before + 1`, estimando con el promedio de los ya hechos."""
        current = done_before + 1
        elapsed = self._clock() - self._start
        if done_before == 0:
            return f"[{current}/{self.total}]"
        remaining = elapsed / done_before * (self.total - done_before)
        return f"[{current}/{self.total} · {_format_duration(elapsed)} · faltan ~{_format_duration(remaining)}]"
