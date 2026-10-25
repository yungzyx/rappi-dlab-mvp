"""QA de las ofertas del agente sobre una base real, sin escribir en ella.

Para una muestra fija (semilla) de personas simuladas y todas las del prototipo, llama a la API en este mismo proceso
(TestClient, con una sola conexión compartida en solo lectura: `default_transaction_read_only = on`) y mide, por
momento: cuántas respuestas traen oferta, qué verticales ofrece, las guardias (deben dar 0), la latencia p50/p95 y
textos de muestra. Momentos: `vertical_por_probar`, `recompra`, `carrito` (con el último producto que pidió),
`proximo_pedido` (con su último pedido), `/recommendations` y `/profile/{id}/verticales`. No llama a nada que
escribe (`/agent/ask` registra la pregunta, `/session` y `/orders` escriben).

Uso (desde rappi-ia/):
    .venv/bin/python scripts/qa_motor.py                      # base rappi, 200 personas, semilla 16
    .venv/bin/python scripts/qa_motor.py --base rappi_staging --muestra 50 --json qa.json --sin-modelo

Sin el extra `ml` (o con --sin-modelo) la API busca sin vectores, como `make serve` sin modelo. No se importa desde
el paquete.
"""

import argparse
import json
import os
import random
import re
import secrets
import statistics
import sys
import time
from collections import Counter, defaultdict

ALCOHOL_GROUP = "alcohol"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="QA de las ofertas del agente sobre una base, en solo lectura.")
    parser.add_argument("--base", default="rappi", help="base de Postgres (por defecto, rappi)")
    parser.add_argument("--muestra", type=int, default=200, help="personas simuladas de la muestra")
    parser.add_argument("--semilla", type=int, default=16, help="semilla de la muestra y de los textos")
    parser.add_argument("--textos", type=int, default=10, help="textos de muestra que se imprimen")
    parser.add_argument("--json", help="escribe aquí cada respuesta y el resumen")
    parser.add_argument("--sin-modelo", action="store_true", help="sin el modelo de texto (RAPPI_IA_LIGHT=1)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    # Antes de importar la API: un secreto solo de este proceso (no se crea el archivo local) y sin precarga.
    os.environ["API_SECRET"] = secrets.token_hex(32)
    os.environ["API_PREWARM"] = "0"
    if args.sin_modelo:
        os.environ["RAPPI_IA_LIGHT"] = "1"

    import psycopg
    from fastapi.testclient import TestClient

    from rappi_ia.api import deps, identity
    from rappi_ia.api.app import app
    from rappi_ia.api.services import services

    conn = psycopg.connect(f"dbname={args.base}", options="-c default_transaction_read_only=on")
    if conn.execute("SHOW default_transaction_read_only").fetchone()[0] != "on":
        sys.exit("La conexión no quedó en solo lectura: no sigo.")
    conn.rollback()
    conn.read_only = True  # también en psycopg: cada transacción empieza READ ONLY

    def read_only_conn():
        try:
            yield conn
        finally:
            conn.rollback()  # nada que confirmar: es solo lectura

    app.dependency_overrides[deps.get_conn] = read_only_conn
    client = TestClient(app, client=("127.0.0.1", 50000))  # sin `with`: sin lifespan, sin pool ni precarga

    svc = services()
    model = svc.embedder.model_name if svc.embedder else None
    people = sample(conn, args.muestra, args.semilla)
    print(f"Base {args.base} (solo lectura) · modelo de texto: {model or 'ninguno (búsqueda sin vectores)'}")
    print(
        f"Personas: {sum(1 for _, s in people if s == 'synthetic')} simuladas, "
        f"{sum(1 for _, s in people if s == 'prototype')} del prototipo"
    )

    client.post("/agent/offer", json={"moment": "vertical_por_probar", "context": {}})  # calienta (modelo, cachés)
    calls = run(client, conn, people, identity.sign)
    report = summarize(conn, calls)
    print_report(report, calls, args.textos, args.semilla)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as file:
            json.dump({"modelo": model, "resumen": report, "llamadas": calls}, file, ensure_ascii=False, indent=1)
    conn.close()


def sample(conn, size: int, seed: int) -> list[tuple[str, str]]:
    """`size` personas simuladas en un orden fijo por la semilla, y todas las del prototipo."""
    rows = conn.execute(
        """SELECT user_id, source FROM app_users WHERE source = 'synthetic'
           ORDER BY md5(user_id || %s::text) LIMIT %s""",
        (seed, size),
    ).fetchall()
    rows += conn.execute("SELECT user_id, source FROM app_users WHERE source = 'prototype' ORDER BY user_id").fetchall()
    conn.rollback()
    return rows


def last_order(conn, user_id: str) -> list[dict]:
    """Las líneas del último pedido `propuesta` de la persona, la última primero."""
    rows = conn.execute(
        """SELECT l.entity_type, l.entity_id FROM app_order_lines l JOIN app_orders o USING (order_id)
           WHERE o.order_id = (SELECT order_id FROM app_orders WHERE user_id = %s AND mode = 'propuesta'
                               ORDER BY ts DESC, order_id DESC LIMIT 1)
           ORDER BY l.line_no DESC""",
        (user_id,),
    ).fetchall()
    conn.rollback()
    return [{"entity_type": t, "entity_id": i} for t, i in rows]


def tried(conn, user_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT vertical FROM app_orders WHERE user_id = %s AND mode = 'propuesta'", (user_id,)
    ).fetchall()
    conn.rollback()
    return sorted(v for (v,) in rows)


def run(client, conn, people, sign) -> list[dict]:
    """Los momentos de cada persona, con su token: una entrada por llamada (con `tried` o `cart` si hacen falta)."""
    from rappi_ia.api.identity import TOKEN_HEADER

    calls = []

    def call(moment: str, user_id: str, source: str, url: str, context: dict | None = None, **extra) -> None:
        headers = {TOKEN_HEADER: sign(user_id)}
        body = None if context is None else {"moment": moment, "context": context, "user_id": user_id}
        start = time.perf_counter()
        response = client.request("GET" if body is None else "POST", url, json=body, headers=headers)
        ms = (time.perf_counter() - start) * 1000
        status = response.status_code
        calls.append(
            {
                "moment": moment,
                "user_id": user_id,
                "source": source,
                "status": status,
                "ms": round(ms, 1),
                "body": response.json() if status == 200 else None,
                "error": None if status in (200, 204) else response.text[:300],
                **extra,
            }
        )

    offer = "/agent/offer"
    for user_id, source in people:
        verticals = tried(conn, user_id)
        lines = last_order(conn, user_id)
        call("vertical_por_probar", user_id, source, offer, {}, tried=verticals)
        call("recompra", user_id, source, offer, {})
        if lines:
            call("carrito", user_id, source, offer, {"product": lines[0]}, cart=lines[:1])
            call("proximo_pedido", user_id, source, offer, {"items": lines[:100]}, cart=lines[:100])
        call("recommendations", user_id, source, f"/recommendations?user_id={user_id}")
        call("verticales", user_id, source, f"/profile/{user_id}/verticales", tried=verticals)
    return calls


# ── Guardias ─────────────────────────────────────────────────────────────────
def offered_products(call: dict) -> list[tuple[str | None, dict]]:
    """(vertical de la oferta o fila, producto) de todo lo que muestra una respuesta."""
    body = call["body"]
    if not body:
        return []
    if call["moment"] == "recommendations":
        return [(row["vertical"], p) for row in body["rows"] for p in row["products"]]
    if call["moment"] == "verticales":
        return []
    return [(body.get("vertical"), p) for p in body.get("products", [])]


def texts_of(call: dict) -> list[str]:
    body = call["body"]
    if not body:
        return []
    if call["moment"] == "recommendations":
        return [row["reason"] for row in body["rows"]]
    if call["moment"] == "verticales":
        return [o["reason"]["text"] for o in body["order"] if o.get("reason")]
    return [body["text"], body["reason"]["text"]]


def bases_of(call: dict) -> list[dict]:
    body = call["body"]
    if not body:
        return []
    if call["moment"] == "recommendations":
        return [b for row in body["rows"] for b in row.get("basis", [])]
    if call["moment"] == "verticales":
        return []
    return body["reason"].get("basis", [])


def concept_ids_in_basis(signal: dict) -> list[str]:
    """Los conceptos que nombra una señal: `concepto`, `carrito`, `pedido`, `recompra` o una compra cruzada
    («A→B@vertical» o «B@vertical»)."""
    kind, signal_id = signal.get("kind"), str(signal.get("id", ""))
    if kind in ("concepto", "carrito", "pedido", "recompra"):
        return [signal_id]
    if kind == "compra_cruzada":
        return signal_id.split("@")[0].split("→")
    return []


def summarize(conn, calls: list[dict]) -> dict:
    from rappi_ia.concepts.taxonomy import load_taxonomy
    from rappi_ia.offers.guards import (
        OFFER_BLOCKED_GROUPS,
        OFFER_BLOCKED_VERTICALS,
        alcohol_in_name,
        alcohol_section,
        baby_in_name,
        is_offerable,
        unofferable_subverticals,
    )

    concepts = load_taxonomy().concepts
    products = [(c, v, p) for c in calls for v, p in offered_products(c)]
    catalog_ids = sorted({int(p["entity_id"]) for _, _, p in products if p.get("entity_type") == "catalog_item"})
    menu_ids = sorted({int(p["entity_id"]) for _, _, p in products if p.get("entity_type") == "menu_item"})
    store_ids = sorted({p["store_id"] for _, _, p in products if p.get("store_id")})
    flags = {
        str(i): (alc, adult)
        for i, alc, adult in conn.execute(
            """SELECT master_product_id, is_alcoholic, age_restricted FROM catalog_items
               WHERE master_product_id = ANY(%s)""",
            (catalog_ids,),
        )
    }
    sections = {
        str(i): s
        for i, s in conn.execute(
            """SELECT mi.item_id, ms.name FROM menu_items mi
               LEFT JOIN menu_sections ms ON ms.store_id = mi.store_id AND ms.section_id = mi.section_id
               WHERE mi.item_id = ANY(%s)""",
            (menu_ids,),
        )
    }
    subverticals = defaultdict(set)
    for store_id, sub in conn.execute(
        "SELECT store_id, subvertical FROM store_verticals WHERE store_id = ANY(%s)", (store_ids,)
    ):
        subverticals[store_id].add(sub)
    conn.rollback()
    blocked_subs = set(unofferable_subverticals())

    guards = Counter()
    hits: dict[str, list[str]] = defaultdict(list)

    def hit(name: str, call: dict, detail: str) -> None:
        guards[name] += 1
        hits[name].append(f"{call['moment']} {call['user_id']}: {detail}")

    for call, vertical, p in products:
        name = p["name"]
        concept = concepts.get(p.get("concept") or "")
        group = (concept.parent or concept.id) if concept else None
        if vertical in OFFER_BLOCKED_VERTICALS or p.get("vertical") in OFFER_BLOCKED_VERTICALS:
            hit("vertical_farmacia_licores", call, f"{vertical}/{p.get('vertical')} {name}")
        if concept and group in OFFER_BLOCKED_GROUPS:
            hit("concepto_bebe_salud", call, f"{concept.id} {name}")
        if concept and concept.sensitive:
            hit("concepto_sensible", call, f"{concept.id} {name}")
        alcohol = (
            p.get("age_restricted")
            or (concept is not None and (concept.age_restricted or group == ALCOHOL_GROUP))
            or any(flags.get(p["entity_id"], (False, False)))
            or alcohol_in_name(p.get("entity_type", "catalog_item"), name, p.get("concept"))
            or (p.get("entity_type") == "menu_item" and alcohol_section(sections.get(p["entity_id"])))
        )
        if alcohol:
            hit("alcohol", call, f"{p.get('concept')} {name}")
        if baby_in_name(p.get("entity_type", "catalog_item"), name):
            hit("bebe_en_nombre", call, name)
        if subverticals.get(p.get("store_id"), set()) & blocked_subs:
            hit("tienda_farmacia_sexshop_smoking", call, f"{p.get('store')} {name}")
        if concept and not is_offerable(concept):
            hit("concepto_no_ofrecible", call, f"{concept.id} {name}")
    non_offerable_names = {c.id: c.name.lower() for c in concepts.values() if not is_offerable(c)}
    for call in calls:
        for signal in bases_of(call):
            for concept_id in concept_ids_in_basis(signal):
                if concept_id in concepts and not is_offerable(concepts[concept_id]):
                    hit("base_nombra_no_ofrecible", call, f"{signal['kind']} {signal['id']}")
        for text in texts_of(call):
            low = text.lower()
            for concept_id, label in non_offerable_names.items():
                if re.search(rf"(?<!\w){re.escape(label)}(?!\w)", low):
                    hit("texto_nombra_no_ofrecible", call, f"{concept_id}: {text}")
            if "  " in text or re.search(r"\b(de|a) el\b", low):
                hit("texto_mal_formado", call, text)

    # Coherencia: «Aún no pides en X» para una vertical donde la persona sí pidió.
    coherence = Counter()
    for call in calls:
        body = call["body"]
        if call["moment"] == "vertical_por_probar" and body:
            said_new = body["text"].startswith("Aún no pides") or body["reason"]["text"].startswith(
                "Porque aún no pides"
            )
            if said_new and body["vertical"] in call.get("tried", []):
                coherence["aun_no_pides_pero_pidio"] += 1
                hits["aun_no_pides_pero_pidio"].append(f"{call['user_id']}: {body['vertical']} en {call['tried']}")
        if call["moment"] == "verticales" and body and body["personalized"]:
            first = body["order"][0]
            if first["reason"]["text"].startswith("Porque pides") and first["id"] not in call.get("tried", []):
                coherence["home_pides_sin_pedidos"] += 1
                hits["home_pides_sin_pedidos"].append(f"{call['user_id']}: {first['id']} en {call['tried']}")
        if call["moment"] in ("carrito", "proximo_pedido") and body:
            cart = {(e["entity_type"], e["entity_id"]) for e in call.get("cart", [])}
            if any((p["entity_type"], p["entity_id"]) in cart for p in body["products"]):
                coherence["ofrece_lo_que_lleva"] += 1
                hits["ofrece_lo_que_lleva"].append(f"{call['moment']} {call['user_id']}")
        if body and call["moment"] not in ("verticales", "recommendations"):
            ids = [(p["entity_type"], p["entity_id"]) for p in body.get("products", [])]
            if len(ids) != len(set(ids)):
                coherence["producto_repetido"] += 1
                hits["producto_repetido"].append(f"{call['moment']} {call['user_id']}")
            if not body.get("products"):
                coherence["oferta_sin_productos"] += 1
                hits["oferta_sin_productos"].append(f"{call['moment']} {call['user_id']}")
            if any(p.get("price_value") is None for p in body.get("products", [])):
                coherence["producto_sin_precio"] += 1
                hits["producto_sin_precio"].append(f"{call['moment']} {call['user_id']}")

    moments = {}
    for moment in ("vertical_por_probar", "recompra", "carrito", "proximo_pedido", "recommendations", "verticales"):
        group = [c for c in calls if c["moment"] == moment]
        if not group:
            continue
        times = sorted(c["ms"] for c in group)
        with_offer = [c for c in group if has_offer(c)]
        by_source = {
            source: (
                sum(1 for c in with_offer if c["source"] == source),
                sum(1 for c in group if c["source"] == source),
            )
            for source in ("synthetic", "prototype")
        }
        moments[moment] = {
            "llamadas": len(group),
            "con_oferta": len(with_offer),
            "por_fuente": by_source,
            "errores": Counter(c["status"] for c in group if c["status"] not in (200, 204)),
            "verticales": Counter(v for c in with_offer for v in offered_verticals(c)),
            "tipo": Counter(kind_of(c) for c in with_offer),
            "p50_ms": round(statistics.median(times), 1),
            "p95_ms": round(times[min(len(times) - 1, int(0.95 * len(times)))], 1),
        }
    return {
        "momentos": moments,
        "guardias": {k: guards.get(k, 0) for k in GUARD_NAMES},
        "coherencia": {k: coherence.get(k, 0) for k in COHERENCE_NAMES},
        "detalle": {k: v[:20] for k, v in hits.items()},
    }


GUARD_NAMES = (
    "vertical_farmacia_licores",
    "concepto_bebe_salud",
    "concepto_sensible",
    "alcohol",
    "bebe_en_nombre",
    "tienda_farmacia_sexshop_smoking",
    "concepto_no_ofrecible",
    "base_nombra_no_ofrecible",
    "texto_nombra_no_ofrecible",
    "texto_mal_formado",
)
COHERENCE_NAMES = (
    "aun_no_pides_pero_pidio",
    "home_pides_sin_pedidos",
    "ofrece_lo_que_lleva",
    "producto_repetido",
    "oferta_sin_productos",
    "producto_sin_precio",
)


def has_offer(call: dict) -> bool:
    if call["status"] != 200 or not call["body"]:
        return False
    if call["moment"] == "recommendations":
        return bool(call["body"]["rows"])
    if call["moment"] == "verticales":
        return call["body"]["personalized"]
    return True


def offered_verticals(call: dict) -> list[str]:
    body = call["body"]
    if call["moment"] == "recommendations":
        return [row["vertical"] for row in body["rows"]]
    if call["moment"] == "verticales":
        return [body["order"][0]["id"]]
    return [body["vertical"]]


def kind_of(call: dict) -> str:
    """El tipo de oferta, por su `basis` y su texto."""
    body = call["body"]
    if call["moment"] == "recommendations":
        return "+".join(sorted({row.get("kind", "complemento") for row in body["rows"]}))
    if call["moment"] == "verticales":
        return "personalizado"
    kinds = [b["kind"] for b in body["reason"].get("basis", [])]
    if call["moment"] != "vertical_por_probar":
        return "+".join(sorted(set(k for k in kinds if k in ("combinacion", "compra_cruzada", "marca")))) or "simple"
    text = body["text"]
    if "combinacion" not in kinds:
        return "de_siempre"
    if text.startswith("Vuelve a"):
        return "paso:vuelta"
    if text.startswith("Para tu pedido de"):
        return "paso:compra_cruzada"
    if text.startswith("También hay"):
        return "paso:mismo_concepto"
    if text.startswith("Para sumar en"):
        return "paso:regla_sin_nombrar"
    if text.startswith("Lo más pedido"):
        return "paso:lo_mas_pedido"
    return "paso:de_siempre"


def print_report(report: dict, calls: list[dict], n_texts: int, seed: int) -> None:
    print("\n## Por momento")
    print("| Momento | Llamadas | Con oferta | Simuladas | Prototipo | p50 ms | p95 ms | Errores |")
    print("|---|---:|---:|---:|---:|---:|---:|---|")
    for moment, m in report["momentos"].items():
        share = 100 * m["con_oferta"] / m["llamadas"]
        sources = [f"{a}/{b}" for a, b in (m["por_fuente"]["synthetic"], m["por_fuente"]["prototype"])]
        errors = dict(m["errores"]) or "—"
        print(
            f"| {moment} | {m['llamadas']} | {m['con_oferta']} ({share:.0f} %) | {sources[0]} | {sources[1]} | "
            f"{m['p50_ms']} | {m['p95_ms']} | {errors} |"
        )
    print("\n## Verticales y tipos")
    for moment, m in report["momentos"].items():
        print(f"- {moment}: verticales {dict(m['verticales'].most_common())}; tipos {dict(m['tipo'].most_common())}")
    print("\n## Guardias (deben ser 0)")
    for name, value in report["guardias"].items():
        print(f"- {name}: {value}")
    print("\n## Coherencia")
    for name, value in report["coherencia"].items():
        print(f"- {name}: {value}")
    for name, lines in report["detalle"].items():
        print(f"\n### {name}")
        for line in lines:
            print(f"  - {line}")
    print("\n## Textos de muestra")
    shown = [c for c in calls if has_offer(c) and c["moment"] != "verticales"]
    rng = random.Random(seed)
    by_moment = defaultdict(list)
    for c in shown:
        by_moment[c["moment"]].append(c)
    picks = []
    while len(picks) < n_texts and any(by_moment.values()):
        for moment in list(by_moment):
            if by_moment[moment] and len(picks) < n_texts:
                picks.append(by_moment[moment].pop(rng.randrange(len(by_moment[moment]))))
    for c in picks:
        body = c["body"]
        if c["moment"] == "recommendations":
            row = body["rows"][0]
            names = "; ".join(p["name"] for p in row["products"][:3])
            print(f"- [{c['moment']}] {c['user_id']} | {row['reason']} → {row['vertical']} | {names}")
        else:
            names = "; ".join(f"{p['name']} ({p['price']})" for p in body["products"][:3])
            print(f"- [{c['moment']}] {c['user_id']} | {body['text']} | {body['reason']['text']} | {names}")


if __name__ == "__main__":
    main()
