"""Falso de Jev para los tests: misma interfaz que `JevClient`, sin red y con respuestas deterministas."""

import threading

from rappi_ia.jev import _TYPE_KEY, JevAnswer, JevStats


class FakeJev:
    """`answers`: respuesta fija por nombre de pregunta; `responder(state, questions)`: función que decide todo
    (puede devolver None para simular un fallo); `fail_when(state)`: fallar para esos estados.
    Sin configuración, responde lo más neutro: noul 0.5, la primera opción, el nivel 0."""

    def __init__(self, answers=None, responder=None, fail_when=None, model="jev-falso"):
        self.model = model
        self.answers = answers or {}
        self.responder = responder
        self.fail_when = fail_when
        self.calls: list[tuple] = []
        self.stats = JevStats()
        self._lock = threading.Lock()

    def ask(self, state, questions):
        with self._lock:
            self.calls.append((state, questions))
            self.stats.requests += 1
        if (self.fail_when and self.fail_when(state)) or (
            self.responder and (out := self.responder(state, questions)) is None
        ):
            with self._lock:
                self.stats.failures += 1
            return None
        if self.responder:
            return out
        return {name: self.answers.get(name) or _neutral(q) for name, q in questions.items()}

    def ask_many(self, items):
        return [self.ask(state, questions) for state, questions in items]


def _neutral(question: dict) -> JevAnswer:
    kind = question[_TYPE_KEY]
    if kind == "noul":
        return JevAnswer(noul=0.5, probabilities={"true": 0.5, "false": 0.5}, confidence=0.0)
    if kind == "choice":
        return JevAnswer(choice=next(iter(question["criteria"])), confidence=1.0)
    return JevAnswer(score=0.0, confidence=1.0)
