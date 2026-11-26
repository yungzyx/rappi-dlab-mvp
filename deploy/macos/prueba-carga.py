"""Prueba de carga de la API con personas simuladas (solo biblioteca estándar).

Cada persona tiene su propia IP (X-Forwarded-For, que la API acepta del proxy de 127.0.0.1) y su sesión, y recorre la
app como alguien de verdad: abre la Home, busca en todas las verticales, le pregunta algo a Mochi y busca en una
vertical, con pausas de 1 a 3 s. Mide la latencia por ruta y los errores. No escribe pedidos; sí deja eventos de
búsqueda y preguntas de personas `prototype` nuevas en la base de la API a la que apunta. Por eso la API no tiene valor
por defecto (mejor una sobre una copia, `rappi_staging`, que la de la demo), y al final imprime los `user_id` creados y
cómo borrarlos (`rappi-ia olvidar`, lo mismo que "Borrar mis datos"); si no, la purga los borra a los 180 días sin uso.

Uso: python3 deploy/macos/prueba-carga.py <api> [personas=25] [segundos=60]
"""

import json
import random
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict

if len(sys.argv) < 2:
    sys.exit(
        "Uso: python3 deploy/macos/prueba-carga.py <api> [personas=25] [segundos=60]\n"
        "Cada persona simulada queda como una persona del prototipo en la base de esa API: mejor una API sobre una copia."
    )
API = sys.argv[1].rstrip("/")
PERSONAS = int(sys.argv[2]) if len(sys.argv) > 2 else 25
SEGUNDOS = int(sys.argv[3]) if len(sys.argv) > 3 else 60

BUSQUEDAS = ["leche descremada", "cerveza", "pañales", "algo para el asado", "sushi", "pizza", "chocolate",
             "detergente", "audífonos bluetooth", "nutela", "pan de molde", "vino tinto", "helado", "paracetamol"]
PREGUNTAS = ["¿qué llevo para un asado de 6?", "algo dulce y barato", "qué puedo cenar con 8 mil pesos",
             "algo para una once para 4", "quiero algo saludable para el almuerzo", "qué me recomiendas"]
VERTICALES = ["supermercado", "turbo", "restaurantes", "conveniencia", "mall"]

tiempos: dict[str, list[float]] = defaultdict(list)
codigos: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
creadas: list[str] = []  # los user_id que dio POST /session, para borrarlos al final
candado = threading.Lock()


def pedir(ruta: str, ip: str, token: str | None = None, cuerpo: dict | None = None) -> dict | None:
    nombre = ruta.split("?")[0]
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(API + ruta, data=datos, method="POST" if datos else "GET")
    req.add_header("X-Forwarded-For", ip)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("X-User-Token", token)
    inicio = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            codigo, cuerpo_resp = resp.status, resp.read()
    except urllib.error.HTTPError as e:
        codigo, cuerpo_resp = e.code, b""
    except Exception:
        codigo, cuerpo_resp = 0, b""
    with candado:
        tiempos[nombre].append(time.perf_counter() - inicio)
        codigos[nombre][codigo] += 1
    try:
        return json.loads(cuerpo_resp) if cuerpo_resp else None
    except ValueError:
        return None


def persona(n: int, fin: float) -> None:
    ip = f"10.{n // 250}.{n % 250}.{random.randint(1, 250)}"
    sesion = pedir("/session", ip, cuerpo={}) or {}
    token = sesion.get("token") or sesion.get("user_token")
    user_id = sesion.get("user_id")
    if user_id:
        with candado:
            creadas.append(user_id)
    while time.time() < fin:
        pedir("/catalog/home", ip, token)
        time.sleep(random.uniform(1, 3))
        q = urllib.request.quote(random.choice(BUSQUEDAS))
        pedir(f"/search?q={q}", ip, token)
        time.sleep(random.uniform(1, 3))
        pedir("/agent/ask", ip, token, {"message": random.choice(PREGUNTAS), "user_id": user_id})
        time.sleep(random.uniform(1, 3))
        pedir(f"/search?q={q}&vertical={random.choice(VERTICALES)}", ip, token)
        time.sleep(random.uniform(1, 3))


def main() -> None:
    fin = time.time() + SEGUNDOS
    hilos = [threading.Thread(target=persona, args=(n, fin)) for n in range(PERSONAS)]
    for h in hilos:
        h.start()
        time.sleep(0.05)
    for h in hilos:
        h.join()
    total = sum(len(v) for v in tiempos.values())
    print(f"{PERSONAS} personas, {SEGUNDOS} s: {total} requests ({total / SEGUNDOS:.1f}/s)")
    for ruta in sorted(tiempos):
        t = sorted(tiempos[ruta])
        p95 = t[int(len(t) * 0.95) - 1] if len(t) >= 20 else max(t)
        cods = " ".join(f"{c}×{k}" for c, k in sorted(codigos[ruta].items()))
        print(f"  {ruta:15} n={len(t):4}  p50={statistics.median(t) * 1000:6.0f} ms  p95={p95 * 1000:6.0f} ms  {cods}")
    if creadas:
        print(f"{len(creadas)} personas del prototipo creadas en la base de {API}. Para borrarlas (con DATABASE_URL de esa")
        print("base), en rappi-ia/:")
        print("  .venv/bin/rappi-ia olvidar " + " ".join(sorted(creadas)))


if __name__ == "__main__":
    main()
