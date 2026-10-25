"""Cliente de Jev: sin red. `requests.post` se reemplaza por un guion de respuestas."""

import json
import threading

import pytest
import requests

from rappi_ia import config, jev
from rappi_ia.jev import Choice, JevClient, Noul, Score


class FakeResponse:
    def __init__(self, status: int = 200, body: dict | None = None, headers: dict | None = None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.headers = headers or {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


class Script:
    """Reemplaza `requests.post`: entrega las respuestas en orden (una excepción se lanza) y anota cada llamada."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.lock = threading.Lock()

    def __call__(self, url, headers=None, json=None, timeout=None):
        with self.lock:
            self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
            nxt = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def ok(answers: dict) -> FakeResponse:
    return FakeResponse(
        200, {"model": "jev-1.13.0", "usage": {"input_tokens": 7, "output_tokens": 2}, "answers": answers}
    )


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    waits: list[float] = []
    monkeypatch.setattr(jev, "_sleep", waits.append)
    return waits


def make_client(monkeypatch, script, **kwargs) -> JevClient:
    monkeypatch.setattr(jev.requests, "post", script)
    return JevClient("sk-test", **{"model": "jev-1.13.0", "max_requests": 100, "parallel": 4, **kwargs})


QUESTIONS = {"q": Noul("¿Es una bebida?")}
NOUL_ANSWER = {"q": {"noul": 0.9}}


def test_no_key_means_no_client(monkeypatch):
    monkeypatch.setattr(config, "TYPESAFE_API_KEY", None)
    assert jev.client_or_none() is None
    monkeypatch.setattr(config, "TYPESAFE_API_KEY", "sk-x")
    assert isinstance(jev.client_or_none(), JevClient)


def test_request_shape_and_auth_header(monkeypatch):
    script = Script(ok(NOUL_ANSWER))
    client = make_client(monkeypatch, script, timeout=12)
    questions = {
        "n": Noul("¿Es vegano?", criteria={"true": "sin origen animal", "false": "con origen animal"}),
        "c": Choice("¿Qué tipo es?", {"a": "algo", "b": {"description": "otro"}}),
        "s": Score("¿Qué tan saludable?", ["nada", "poco", "mucho"]),
    }
    script.responses = [
        ok(
            {
                "n": {"noul": 0.1},
                "c": {"choice": "a", "probabilities": {"a": 1.0}, "confidence": 1.0},
                "s": {"score": 1.0, "probabilities": {"0": 0, "1": 1, "2": 0}, "confidence": 1.0},
            }
        )
    ]
    client.ask({"name": "Leche"}, questions)

    (call,) = script.calls
    assert call["url"] == "https://api.typesafe.ai/v1/systemone"
    assert call["headers"]["Authorization"] == "Bearer sk-test"
    assert call["headers"]["Content-Type"] == "application/json"
    assert call["timeout"] == 12
    body = call["json"]
    assert body["model"] == "jev-1.13.0"
    assert body["state"] == {"name": "Leche"}
    assert body["questions"]["n"] == {
        "type": "noul",
        "instructions": "¿Es vegano?",
        "criteria": {"true": "sin origen animal", "false": "con origen animal"},
    }
    assert body["questions"]["c"]["type"] == "choice"
    assert body["questions"]["c"]["criteria"] == {"a": "algo", "b": {"description": "otro"}}
    assert body["questions"]["s"] == {
        "type": "score",
        "instructions": "¿Qué tan saludable?",
        "criteria": ["nada", "poco", "mucho"],
    }
    assert "criteria" not in Noul("x")


def test_retries_429_then_succeeds(monkeypatch, no_sleep):
    script = Script(FakeResponse(429, headers={"Retry-After": "2"}), requests.ConnectionError("boom"), ok(NOUL_ANSWER))
    client = make_client(monkeypatch, script)
    answers = client.ask("x", QUESTIONS)
    assert answers is not None and answers["q"].noul == 0.9
    assert len(script.calls) == 3
    assert no_sleep[0] == 2  # respeta Retry-After
    assert client.stats.requests == 3 and client.stats.failures == 0


def test_gives_up_after_two_retries(monkeypatch):
    script = Script(FakeResponse(529))
    client = make_client(monkeypatch, script)
    assert client.ask("x", QUESTIONS) is None
    assert len(script.calls) == 3
    assert client.stats.failures == 1


@pytest.mark.parametrize("status", [401, 403, 422])
def test_client_errors_are_not_retried_and_return_none(monkeypatch, status):
    script = Script(FakeResponse(status, {"error": "no"}))
    client = make_client(monkeypatch, script)
    assert client.ask("x", QUESTIONS) is None
    assert len(script.calls) == 1
    assert client.stats.failures == 1


def test_cap_stops_and_reports(monkeypatch):
    script = Script(ok(NOUL_ANSWER))
    client = make_client(monkeypatch, script, max_requests=2)
    assert client.ask("a", QUESTIONS) is not None
    assert client.ask("b", QUESTIONS) is not None
    assert client.stats.stopped_by_cap is False
    assert client.ask("c", QUESTIONS) is None
    assert client.stats.stopped_by_cap is True
    assert len(script.calls) == 2 and client.stats.requests == 2


def test_cap_counts_retries(monkeypatch):
    script = Script(FakeResponse(500), FakeResponse(500), ok(NOUL_ANSWER))
    client = make_client(monkeypatch, script, max_requests=2)
    assert client.ask("a", QUESTIONS) is None
    assert client.stats.stopped_by_cap is True
    assert len(script.calls) == 2


def test_ask_many_isolates_failures(monkeypatch):
    def post(url, headers=None, json=None, timeout=None):
        if json["state"] == "malo":
            return FakeResponse(422)
        return ok({"q": {"noul": 0.25}})

    monkeypatch.setattr(jev.requests, "post", post)
    client = JevClient("sk-test", "jev-1.13.0", 100, 4)
    results = client.ask_many([("a", QUESTIONS), ("malo", QUESTIONS), ("b", QUESTIONS)])
    assert [r is None for r in results] == [False, True, False]
    assert results[0]["q"].noul == 0.25
    assert client.stats.failures == 1 and client.stats.requests == 3


def test_ask_many_survives_a_malformed_body(monkeypatch):
    script = Script(ok({}))  # falta la respuesta de «q»
    client = make_client(monkeypatch, script)
    assert client.ask_many([("a", QUESTIONS)]) == [None]
    assert client.stats.failures == 1


def test_parses_noul_choice_score_answers(monkeypatch):
    script = Script(
        ok(
            {
                "n": {"noul": 0.8},
                "c": {"choice": "lacteo", "probabilities": {"lacteo": 0.7, "otro": 0.3}, "confidence": 0.7},
                "s": {
                    "score": 1.4,
                    "legend": "poco",
                    "probabilities": {"0": 0.1, "1": 0.5, "2": 0.4},
                    "confidence": 0.5,
                },
            }
        )
    )
    client = make_client(monkeypatch, script)
    out = client.ask(
        "x", {"n": Noul("a"), "c": Choice("b", {"lacteo": "l", "otro": "o"}), "s": Score("c", ["a", "b", "c"])}
    )
    assert out["n"].noul == 0.8 and out["n"].choice is None and out["n"].score is None
    assert out["n"].confidence == pytest.approx(0.6)  # |2p - 1|: la API no la devuelve para noul
    assert out["c"].choice == "lacteo" and out["c"].confidence == 0.7
    assert out["c"].probabilities == {"lacteo": 0.7, "otro": 0.3}
    assert out["s"].score == 1.4 and out["s"].probabilities["1"] == 0.5 and out["s"].noul is None
    assert client.stats.input_tokens == 7


def test_key_never_logged(monkeypatch, caplog):
    script = Script(FakeResponse(401))
    client = make_client(monkeypatch, script)
    with caplog.at_level("DEBUG"):
        client.ask("x", QUESTIONS)
    assert "sk-test" not in caplog.text


def test_key_never_logged_on_connection_error(monkeypatch, caplog):
    script = Script(requests.ConnectionError("fallo con Bearer sk-test"))
    client = make_client(monkeypatch, script)
    with caplog.at_level("DEBUG"):
        assert client.ask("x", QUESTIONS) is None
    assert "sk-test" not in caplog.text


@pytest.mark.parametrize("value", ["nan", "-5", "abc", "inf"])
def test_bad_retry_after_falls_back_to_backoff(monkeypatch, no_sleep, value):
    script = Script(FakeResponse(429, headers={"Retry-After": value}), ok(NOUL_ANSWER))
    client = make_client(monkeypatch, script)
    assert client.ask("x", QUESTIONS) is not None
    assert no_sleep == [0.5]


def test_huge_retry_after_is_clamped(monkeypatch, no_sleep):
    script = Script(FakeResponse(429, headers={"Retry-After": "9999"}), ok(NOUL_ANSWER))
    make_client(monkeypatch, script).ask("x", QUESTIONS)
    assert no_sleep == [jev._MAX_WAIT]


def test_ask_never_raises(monkeypatch):
    script = Script(ok(NOUL_ANSWER))
    client = make_client(monkeypatch, script)

    def unserializable(url, headers=None, json=None, timeout=None):
        raise TypeError("Object of type object is not JSON serializable")

    monkeypatch.setattr(jev.requests, "post", unserializable)
    assert client.ask(object(), QUESTIONS) is None
    assert client.stats.failures == 1


def test_weird_usage_value_does_not_raise(monkeypatch):
    weird = FakeResponse(200, {"usage": "mucho", "answers": NOUL_ANSWER})
    client = make_client(monkeypatch, Script(weird))
    assert client.ask("x", QUESTIONS) is None
    assert client.stats.failures == 1


def test_failure_logs_class_only(monkeypatch, caplog):
    def boom(url, headers=None, json=None, timeout=None):
        raise TypeError("detalle con Bearer sk-test")

    monkeypatch.setattr(jev.requests, "post", boom)
    client = JevClient("sk-test", "jev-1.13.0", 100, 4)
    with caplog.at_level("DEBUG"):
        client.ask("x", QUESTIONS)
    assert "TypeError" in caplog.text and "sk-test" not in caplog.text


def test_cap_blocking_a_retry_counts_as_failure(monkeypatch):
    client = make_client(monkeypatch, Script(FakeResponse(500)), max_requests=1)
    assert client.ask("a", QUESTIONS) is None
    assert client.stats.failures == 1 and client.stats.stopped_by_cap is True


def test_cap_holds_under_concurrency(monkeypatch):
    script = Script(ok(NOUL_ANSWER))
    client = make_client(monkeypatch, script, max_requests=5, parallel=8)
    results = client.ask_many([(f"s{i}", QUESTIONS) for i in range(20)])
    assert len(script.calls) == 5 and client.stats.requests == 5
    assert sum(r is not None for r in results) == 5
    assert client.stats.stopped_by_cap is True


# --- adopción (eval/jev-adopcion.json) ---------------------------------------------------------------------------


def test_without_adoption_file_nothing_is_adopted(tmp_path):
    adoption = jev.load_adoption(tmp_path / "no-hay.json")
    assert adoption == jev.Adoption(
        categorias=False, juez=False, t_auto=jev.DEFAULT_T_AUTO, model_version=None, variante="es"
    )
    assert jev.DEFAULT_T_AUTO == 0.85


def test_adoption_file_is_read(tmp_path):
    path = tmp_path / "jev-adopcion.json"
    path.write_text(
        json.dumps({"categorias": True, "juez": False, "t_auto": 0.9, "model_version": "jev-1.13.0", "fecha": "x"}),
        encoding="utf-8",
    )
    assert jev.load_adoption(path) == jev.Adoption(True, False, 0.9, "jev-1.13.0", "es")


def test_adoption_keeps_the_instruction_variant_the_pilot_chose(tmp_path):
    path = tmp_path / "jev-adopcion.json"
    path.write_text(json.dumps({"categorias": True, "t_auto": 0.8, "variante": "en"}), encoding="utf-8")
    assert jev.load_adoption(path).variante == "en"


@pytest.mark.parametrize(
    "content",
    [
        "no es json",
        "[]",
        '{"categorias": "sí"}',
        '{"categorias": true, "t_auto": 2}',
        '{"categorias": true, "variante": "fr"}',
    ],
)
def test_a_broken_adoption_file_adopts_nothing(tmp_path, content, caplog):
    path = tmp_path / "jev-adopcion.json"
    path.write_text(content, encoding="utf-8")
    adoption = jev.load_adoption(path)
    assert not adoption.categorias and not adoption.juez
    assert "jev-adopcion.json" in caplog.text


def test_default_adoption_file_lives_in_eval():
    assert jev.ADOPTION_FILE.name == "jev-adopcion.json" and jev.ADOPTION_FILE.parent.name == "eval"
