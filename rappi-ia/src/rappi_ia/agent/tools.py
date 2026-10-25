"""Herramientas del agente: buscar en un vertical (con precios vigentes por SQL) y sugerir un complemento.

Todo producto que el agente muestra pasa por aquí: sale de la base, con su precio vigente, nunca inventado.
"""

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field

from psycopg import Connection
from rappi_scraper.storage.search import MIN_PRICE

from .. import config
from ..concepts.taxonomy import load_taxonomy
from ..embeddings.base import TextEmbedder
from ..motor.combos import SERVICES
from ..motor.predict import step_signal, target_step
from ..motor.recommend import RECENT_DAYS, CrossPick, cross_picks, latest_lambda
from ..offers.guards import (
    alcohol_in_description,
    alcohol_in_name,
    alcohol_section,
    baby_in_name,
    is_offerable,
    offerable_vertical,
    unofferable_subverticals,
)
from ..retrieval.hybrid import Filters, RetrievalResult, named_occasion, retrieve
from ..retrieval.spelling import correct_query
from ..text import FILLER_WORDS, LEAFLET_WARNINGS, normalize, tokens
from .verticals import ranked_verticals


def _sensitive() -> set[str]:
    return {c.id for c in load_taxonomy().concepts.values() if c.sensitive}


VERTICAL_LABELS = {
    "supermercado": "el súper",
    "conveniencia": "Express",
    "turbo": "Turbo",
    "mall": "Rappi Mall",
    "farmacia": "farmacia",
    "licores": "Licores",
    "chocolateria": "chocolaterías",
    "restaurantes": "restaurantes",
}


@dataclass
class Product:
    id: str
    entity_type: str
    entity_id: str
    name: str
    vertical: str
    concept: str | None
    price_value: float | None
    before_value: float | None
    store: str | None
    img: str | None
    age_restricted: bool = False
    store_id: int | None = None
    presentation: str | None = None

    def to_dict(self) -> dict:
        discount = None
        if self.price_value and self.before_value and self.before_value > self.price_value:
            discount = f"-{round(100 * (1 - self.price_value / self.before_value))}%"
        return {
            "id": self.id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "name": self.name,
            "vertical": self.vertical,
            "concept": self.concept,
            "price": clp(self.price_value),
            "price_value": self.price_value,
            "before": clp(self.before_value) if discount else None,
            "discount": discount,
            "store": self.store,
            "img": self.img,
            "age_restricted": self.age_restricted,
            "store_id": self.store_id,
            "presentation": self.presentation,
        }


@dataclass
class SearchOutcome:
    result: RetrievalResult
    products: list[Product]
    cheapest_without_filter: Product | None = None
    corrected_query: str | None = None  # con `correct`, la consulta corregida que se buscó (retrieval/spelling.py)


@dataclass
class Suggestion:
    concept: str
    source_concept: str
    vertical: str
    reason: str
    products: list[Product] = field(default_factory=list)
    brand: str | None = None  # brand_key del primer producto, si es una marca que la persona compra
    basis: list[dict] = field(default_factory=list)  # `combinacion` y `compra_cruzada`, si la eligió el motor


def clp(value: float | None) -> str | None:
    return None if value is None else "$" + f"{round(value):,}".replace(",", ".")


def search_products(
    conn: Connection,
    vertical: str,
    query: str,
    concepts: list[str] | None,
    embedder: TextEmbedder | None,
    price_max: float | None = None,
    k: int = 6,
    mode: str = "hibrido",
    symptom: bool = False,
    offer: bool = False,
    adult_ok: bool = False,
    words: bool | None = None,
    correct: bool = False,
) -> SearchOutcome:
    """Con `concepts=None`, los conceptos los detecta la búsqueda en la consulta (endpoint /search). Con `symptom` (o
    en farmacia) no se muestra lo que no tiene concepto: podría ser un medicamento sin categoría mapeada. Con `offer`,
    la búsqueda es de una oferta del agente y solo trae lo que puede proponer por su cuenta: nada +18 ni de tiendas
    Farmacia, Sex shop o Smoking shop (offers/guards.py); el concepto y la vertical los elige quien llama. `adult_ok`
    deja pasar lo +18 en una oferta: solo para el kit de una ocasión que la persona eligió (alcohol con su marca).
    `words`: si a la consulta le queda alguna palabra (`retrieval.hybrid.has_words`), si quien llama ya lo sabe.
    Con `correct` (/search), si nada calza todas las palabras, corrige los errores de tipeo (`retrieval.spelling`) y
    vuelve a buscar: si así algo calza todas las palabras y hay productos, devuelve eso con `corrected_query`; si no, lo
    de la consulta tal cual."""
    found = _search_products(
        conn, vertical, query, concepts, embedder, price_max, k, mode, symptom, offer, adult_ok, words
    )
    if not correct or found.result.strict_lexical_matches:
        return found
    fixed = correct_query(conn, query, vertical)
    if fixed is None:
        return found
    again = _search_products(
        conn, vertical, fixed, concepts, embedder, price_max, k, mode, symptom, offer, adult_ok, None
    )
    if not again.result.strict_lexical_matches or not again.products:
        return found
    again.corrected_query = fixed
    return again


def _search_products(
    conn, vertical, query, concepts, embedder, price_max, k, mode, symptom, offer, adult_ok, words
) -> SearchOutcome:
    result = retrieve(
        conn, vertical, query, embedder, k=k * 2, filters=Filters(price_max), mode=mode, concepts=concepts, words=words
    )
    concepts = result.query_concepts
    capped = price_max is not None
    strict = symptom or vertical == "farmacia"
    hits = _focus([h for h in result.hits if _allowed(h.concept_id, concepts, strict)], result, capped)
    products = _dedupe(_within_budget(_with_prices(conn, vertical, hits, offer, adult_ok), price_max))[:k]
    cheapest = None
    if not products and capped:
        unfiltered = retrieve(conn, vertical, query, embedder, k=k * 2, mode=mode, concepts=concepts, words=words)
        allowed = [h for h in unfiltered.hits if _allowed(h.concept_id, concepts, strict)]
        # «El más barato» es de lo pedido: el mismo foco que con tope.
        candidates = _with_prices(conn, vertical, _focus(allowed, unfiltered, capped), offer, adult_ok)
        priced = [p for p in candidates if p.price_value is not None]
        cheapest = min(priced, key=lambda p: p.price_value) if priced else None
    return SearchOutcome(result, products, cheapest)


CANDIDATE_REMEDIES = 30  # se filtran después: muchos calzan solo por las advertencias del prospecto
MIN_REMEDIES = 2  # con menos, lo que calza el síntoma suele ser casualidad (un laxante para «me siento mal»)


# La familia de remedios que trata cada síntoma: el paracetamol no dice «fiebre» en su ficha. Normalizado.
SYMPTOM_REMEDIES = {
    **dict.fromkeys(("fiebre", "cabeza", "dolor", "duele", "migrana"), "analgésico paracetamol ibuprofeno"),
    **dict.fromkeys(("resfrio", "resfriado", "gripe"), "antigripal resfrío"),
    **dict.fromkeys(("tos", "garganta"), "antitusivo jarabe expectorante"),
    **dict.fromkeys(("acidez", "guata"), "antiácido"),
    **dict.fromkeys(("diarrea",), "antidiarreico"),
    **dict.fromkeys(("estrenido", "estrenida", "estrenimiento"), "laxante"),
    **dict.fromkeys(("alergia",), "antialérgico antihistamínico"),
    **dict.fromkeys(("nauseas",), "antináuseas"),
}


def _treats(content: str, words: set[str]) -> bool:
    """El nombre, la categoría o la indicación (lo que va antes de las advertencias) dice alguna de esas palabras."""
    said = normalize(content)
    head = said[: m.start()] if (m := LEAFLET_WARNINGS.search(said)) else said
    return any(token[:7] in words for token in head.split())


def search_remedies(
    conn: Connection, query: str, embedder: TextEmbedder | None, price_max: float | None = None, k: int = 6
) -> SearchOutcome:
    """Remedios de farmacia para un síntoma: medicamentos sin receta cuya ficha (sin las advertencias) nombra el
    síntoma o la familia que lo trata (búsqueda por palabras, no solo cercanía vectorial). Con menos de MIN_REMEDIES
    no devuelve ninguno."""
    families = " ".join(dict.fromkeys(SYMPTOM_REMEDIES[w] for w in tokens(query) if w in SYMPTOM_REMEDIES))
    query = f"{query} {families}".strip()
    skip = FILLER_WORDS | {"tengo", "para", "algo"}
    words = {w[:7] for w in tokens(query) if len(w) >= 3 and w not in skip}
    result = retrieve(
        conn, "farmacia", query, embedder, k=CANDIDATE_REMEDIES, filters=Filters(price_max), concepts=["medicamentos"]
    )
    hits = [
        h
        for h in result.hits
        if h.concept_id == "medicamentos"
        and not h.metadata.get("receta")
        and "lexico" in h.ranks
        and _treats(h.content, words)
    ]
    products = _dedupe(_within_budget(_with_prices(conn, "farmacia", hits), price_max))[:k]
    return SearchOutcome(result, products if len(products) >= MIN_REMEDIES else [])


SIMILAR_MARGIN = 0.1  # dos complementos cuyo peso difiere en menos que esto son parecidos: decide la combinación
CROSS_LIFT_SPAN = 3  # peso de una compra cruzada: min(1, (lift − 1) / 3); con lift 4 o más pesa 1, lo máximo
COMPLEMENT_REPEAT_DAYS = 7  # un complemento ofrecido en estos días y antes del último pedido cede su lugar
ROTATION_MARGIN = 0.2  # con el segundo complemento a esto o menos del primero, a la mitad de las personas les toca él
# De dónde viene un complemento ofrecido (`payload.origen` de su `suggestion_shown`): los momentos `carrito`,
# `checkout` y `proximo_pedido` y lo que sugiere al preguntarle (`ask`). `mochi-<momento>` es el nombre histórico de
# `agent-<momento>`.
COMPLEMENT_ORIGINS = [
    f"{prefix}-{moment}" for prefix in ("agent", "mochi") for moment in ("carrito", "checkout", "proximo_pedido", "ask")
]


@dataclass
class _Candidate:
    concept: str
    source: str  # el concepto de origen (la arista o la regla)
    weight: float
    pick: CrossPick | None = None  # la compra cruzada de la persona que lo trajo, si su peso es el mayor


def suggest_complement(
    conn: Connection,
    source_concepts: list[str],
    current_vertical: str | None,
    embedder: TextEmbedder | None,
    exclude: set[str] = frozenset(),
    prefer_brands: dict[str, int] | None = None,
    user_id: str | None = None,
) -> Suggestion | None:
    """Mejor complemento que el agente pueda proponer (offers/guards.py: ni alcohol, farmacia, bebé, salud ni
    sensibles), preferentemente de OTRO vertical, con productos reales.

    Candidatos: las aristas curadas y las aprendidas de datos que no son simulados (`concept_edges`, con su peso) y,
    con `user_id`, sus compras cruzadas (`motor.recommend.cross_picks`, si el λ de la corrida es > 0 y la persona pidió
    hace poco alguno de los `source_concepts`) que salen de uno de ellos que el agente puede nombrar, con peso
    min(1, (lift − 1) / CROSS_LIFT_SPAN), y que se buscan solo en la vertical de la regla; de un mismo concepto vale el
    mayor peso. Van de mayor a menor peso (a igual peso, por id), salvo que, con `user_id` y un paso del motor
    (`target_step`), entre los que pesan menos de `SIMILAR_MARGIN` por debajo del primero haya uno que se vende en la
    vertical del paso (si no es la actual) y el primero no: ese va primero y busca antes ahí. La marca de la persona
    gana a ese desempate: si el primero trae un producto de una marca que compra (`prefer_brands`), queda el orden de
    siempre. La `basis` de la sugerencia dice `combinacion` si el desempate
    la eligió y `compra_cruzada` («<A>→<B>@<vertical>» de la regla) si la trajo una compra cruzada. Una compra cruzada
    se busca solo en la vertical de su regla; si ahí no hay productos, el mismo concepto se prueba por su arista curada
    (o aprendida) en las verticales de siempre, y la sugerencia sale sin esa `basis`.

    Con `prefer_brands` (brand_key → pedidos de la persona), se miran más candidatos del concepto y el de la marca
    comprada con más pedidos va primero. Si ninguno es de sus marcas, el resultado es el de siempre.

    Con `user_id`, un concepto que Mochi ya le ofreció como complemento en los últimos `COMPLEMENT_REPEAT_DAYS` días
    y antes de su último pedido (`_recently_offered`) pasa al final: sale el siguiente mejor. Lo ofrecido desde ese
    pedido (la compra en curso) no cuenta: el complemento no cambia mientras se arma el mismo pedido. Si todos los
    candidatos con productos se ofrecieron hace poco, sale el mejor de siempre. La razón y la `basis` no cambian: dicen
    por qué sale este complemento.

    Con `user_id`, antes de todo eso, si los dos primeros pesan parecido (`_takes_second`), a la mitad de las personas
    les toca primero el segundo: las gaseosas eran el primer complemento de toda la comida preparada. Lo personal le
    gana a esa alternancia: si el primero trae un producto de una marca que compra, o si completa su combinación, va
    primero (el desempate se mide desde el primero de siempre)."""
    taxonomy = load_taxonomy()
    sources = [c for c in source_concepts if c in taxonomy.concepts and not taxonomy.concepts[c].sensitive]
    if not sources:
        return None
    edges = conn.execute(
        """SELECT from_concept, to_concept, max(weight) AS weight
           FROM concept_edges
           WHERE from_concept = ANY(%s) AND (method = 'curado' OR data_source <> 'synthetic')
           GROUP BY 1, 2
           ORDER BY weight DESC, to_concept""",
        (sources,),
    ).fetchall()
    found: dict[str, _Candidate] = {}
    for source, target, weight in edges:
        found.setdefault(target, _Candidate(target, source, float(weight)))
    population = config.MOTOR_POBLACION
    edges_found = dict(found)  # sin las compras cruzadas: si la regla no encuentra nada, la arista se prueba igual
    lam = None
    if user_id is not None and _ordered_lately(conn, user_id, sources):
        lam = latest_lambda(conn, population)
    if lam is not None and lam > 0:
        for pick in cross_picks(conn, user_id, population=population, k=None, lam=lam):
            origin = taxonomy.concepts.get(pick.from_concept) if pick.from_concept else None
            if origin is None or origin.id not in sources or not is_offerable(origin) or not pick.lift > 1:
                continue
            weight = min(1.0, (pick.lift - 1) / CROSS_LIFT_SPAN)
            if pick.concept_id not in found or weight > found[pick.concept_id].weight:
                found[pick.concept_id] = _Candidate(pick.concept_id, origin.id, weight, pick)

    candidates = sorted(
        (
            c
            for c in found.values()
            if c.concept in taxonomy.concepts
            and is_offerable(taxonomy.concepts[c.concept])
            and c.concept not in exclude
            and c.concept not in sources
        ),
        key=lambda c: (-c.weight, c.concept),
    )
    if not candidates:
        return None

    def verticals_of(candidate: _Candidate) -> list[str]:
        if candidate.pick:  # la compra cruzada es de la vertical de la regla: solo ahí
            return [candidate.pick.vertical]
        return _verticals_for(conn, candidate.concept, current_vertical)

    def search(candidate: _Candidate, verticals: list[str]) -> tuple[str, list[Product], str | None] | None:
        """(vertical, productos, marca) de la primera vertical donde el candidato tiene productos."""
        concept = taxonomy.concepts[candidate.concept]
        for vertical in verticals:
            if not offerable_vertical(vertical):
                continue
            brand = None
            if prefer_brands:
                pool = search_products(
                    conn, vertical, concept.name, [concept.id], embedder, k=BRAND_CANDIDATES, offer=True
                )
                products, brand = _brand_first(
                    conn, [p for p in pool.products if p.concept == concept.id], prefer_brands
                )
            if brand is None:
                outcome = search_products(conn, vertical, concept.name, [concept.id], embedder, k=4, offer=True)
                products = [p for p in outcome.products if p.concept == concept.id]
            if products := _dedupe(products):
                return vertical, products[:3], brand
        return None

    def suggestion(candidate: _Candidate, result: tuple[str, list[Product], str | None], basis: list[dict]):
        vertical, products, brand = result
        origin = taxonomy.concepts[candidate.source]
        reason = f"Porque llevas {origin.emoji} {origin.name.lower()}"
        if candidate.pick:
            rule = f"{origin.id}→{candidate.concept}@{candidate.pick.vertical}"
            basis = [*basis, {"kind": "compra_cruzada", "id": rule, "source": f"poblacion:{population}"}]
        return Suggestion(candidate.concept, candidate.source, vertical, reason, products, brand, basis)

    def choose(candidates: list[_Candidate]) -> Suggestion | None:
        """El primer candidato con productos, con el desempate de la combinación. El desempate se mide desde el primero
        de siempre (`first`), no desde el que la alternancia (`_takes_second`) puso primero, y le gana a ella: si el de
        siempre ya completa la combinación, va primero."""
        first = min(candidates, key=lambda c: (-c.weight, c.concept))  # el orden de `candidates` sin la alternancia
        searched: dict[str, tuple[str, list[Product], str | None] | None] = {}  # lo ya buscado de un candidato
        # Los pesos son `real`: redondeados, 0,4 − 0,3 no queda bajo el margen por el error de coma flotante.
        similar = [c for c in candidates if c is not first and round(first.weight - c.weight, 6) < SIMILAR_MARGIN]
        step = target_step(conn, user_id, population) if user_id is not None and similar else None
        if step is not None:
            # Un servicio no tiene productos.
            group = {step.vertical} if step.vertical not in SERVICES and offerable_vertical(step.vertical) else set()
            for candidate in (first, *similar):
                if completing := [v for v in verticals_of(candidate) if v in group and v != current_vertical]:
                    break
            # Si el primero ya completa la combinación, va primero; si ninguno la completa, el orden de siempre.
            if completing and candidate is first:
                candidates = [first, *(c for c in candidates if c is not first)]
            elif completing:
                # Su marca gana al desempate: el primero con un producto de una marca que compra va igual primero.
                if prefer_brands:
                    usual = searched[first.concept] = search(first, verticals_of(first))
                    if usual is not None and usual[2] is not None:
                        return suggestion(first, usual, [])
                # Primero en la vertical del paso; si ahí no hay productos, vuelve a su lugar de siempre.
                if result := search(candidate, completing):
                    return suggestion(candidate, result, [step_signal(conn, step, population)])

        for candidate in candidates:
            if candidate.concept in searched:
                result = searched[candidate.concept]
            else:
                result = search(candidate, verticals_of(candidate))
            if result:
                return suggestion(candidate, result, [])
            # La regla no encontró nada en su vertical: el mismo concepto por su arista, en sus verticales de siempre.
            edge = edges_found.get(candidate.concept)
            if (
                candidate.pick
                and edge is not None
                and (result := search(edge, _verticals_for(conn, edge.concept, current_vertical)))
            ):
                return suggestion(edge, result, [])
        return None

    if user_id is not None and _takes_second(candidates, user_id):
        best = candidates[0]
        usual = search(best, verticals_of(best)) if prefer_brands else None
        if usual is None or usual[2] is None:  # sin un producto de sus marcas en el primero
            candidates = [candidates[1], best, *candidates[2:]]

    recent = _recently_offered(conn, user_id) if user_id is not None else set()
    fresh = [c for c in candidates if c.concept not in recent]
    # Primero sin lo ofrecido hace poco; si no queda nada o nada de eso tiene productos, el mejor de siempre.
    for pool in [fresh, candidates] if 0 < len(fresh) < len(candidates) else [candidates]:
        if (chosen := choose(pool)) is not None:
            return chosen
    return None


def _takes_second(candidates: list[_Candidate], user_id: str) -> bool:
    """Si a la persona le toca primero el segundo complemento: cuando pesa `ROTATION_MARGIN` o menos que el primero, a
    la mitad de las personas, siempre la misma para un mismo origen (md5 de la persona y el concepto de origen; `hash`
    de Python cambia entre procesos). Las gaseosas (0,6 o 0,7) iban primero con toda la comida preparada, y con la
    pizza, la hamburguesa o los sándwiches casi todos veían las mismas. Una compra cruzada de la persona no rota."""
    if len(candidates) < 2:
        return False
    best, second = candidates[:2]
    # Los pesos son `real`: redondeados, como en `choose`.
    if best.pick or second.pick or round(best.weight - second.weight, 6) > ROTATION_MARGIN:
        return False
    return hashlib.md5(f"{user_id}|{best.source}".encode()).digest()[0] % 2 == 1


def _recently_offered(conn: Connection, user_id: str) -> set[str]:
    """Los conceptos que Mochi le ofreció a la persona como complemento en los últimos `COMPLEMENT_REPEAT_DAYS` días
    y antes de su último pedido en «Propuesta»: sus `suggestion_shown` de `COMPLEMENT_ORIGINS`. Lo mostrado después de
    ese pedido es la sesión de compra en curso: no cuenta, así el complemento no cambia mientras se arma el mismo
    pedido. «Rappi hoy» (`payload.mode = 'actual'`) no cuenta; sin pedidos, no se salta nada."""
    rows = conn.execute(
        """SELECT DISTINCT e.concept_id
           FROM app_events e
           JOIN (SELECT max(ts) AS ts FROM app_orders WHERE user_id = %(user)s AND mode = 'propuesta') o
             ON e.ts < o.ts
           WHERE e.user_id = %(user)s AND e.type = 'suggestion_shown' AND e.concept_id IS NOT NULL
             AND e.payload ->> 'origen' = ANY(%(origins)s) AND e.payload ->> 'mode' IS DISTINCT FROM 'actual'
             AND e.ts > now() - make_interval(days => %(days)s)""",
        {"user": user_id, "origins": COMPLEMENT_ORIGINS, "days": COMPLEMENT_REPEAT_DAYS},
    )
    return {concept for (concept,) in rows}


def _ordered_lately(conn: Connection, user_id: str, concepts: list[str]) -> bool:
    """Si la persona pidió alguno de esos conceptos en «Propuesta» en los últimos `RECENT_DAYS` días: solo entonces sus
    reglas de compra cruzada (`cross_picks`) pueden salir de ellos."""
    return conn.execute(
        """SELECT EXISTS (SELECT 1 FROM app_orders o JOIN app_order_lines l USING (order_id)
                          WHERE o.user_id = %s AND o.mode = 'propuesta' AND l.concept_id = ANY(%s)
                            AND o.ts > now() - make_interval(days => %s) AND o.ts <= now())""",
        (user_id, concepts, RECENT_DAYS),
    ).fetchone()[0]


BRAND_CANDIDATES = 12  # productos del concepto que se miran para encontrar una marca que la persona compra


def _brand_first(conn: Connection, products: list[Product], brands: dict[str, int]) -> tuple[list[Product], str | None]:
    """El producto de la marca comprada con más pedidos, primero (con empate, el mejor de la búsqueda); el resto en
    su orden. Sin ninguno de sus marcas: (products, None)."""
    rows = conn.execute(
        """SELECT entity_type, entity_id, brand_key FROM item_brands
           WHERE (entity_type, entity_id) IN (SELECT * FROM unnest(%s::text[], %s::text[]))""",
        ([p.entity_type for p in products], [p.entity_id for p in products]),
    )
    found = {(kind, entity): brand for kind, entity, brand in rows}
    owned = [(i, brand) for i, p in enumerate(products) if (brand := found.get((p.entity_type, p.entity_id))) in brands]
    if not owned:
        return products, None
    best, brand = min(owned, key=lambda pair: (-brands[pair[1]], pair[0]))
    return [products[best], *products[:best], *products[best + 1 :]], brand


def _within_budget(products: list[Product], price_max: float | None) -> list[Product]:
    """El filtro de la búsqueda usa el precio del índice; aquí se revisa contra el precio vigente que se muestra."""
    if price_max is None:
        return products
    return [p for p in products if p.price_value is not None and p.price_value <= price_max]


def _dedupe(products: list[Product]) -> list[Product]:
    """Un solo producto por nombre (el catálogo repite nombres entre presentaciones y tiendas)."""
    seen: set[str] = set()
    unique = []
    for product in products:
        key = " ".join(product.name.lower().split())
        if key not in seen:
            seen.add(key)
            unique.append(product)
    return unique


# Bajo esta participación en el vertical (y bajo el mínimo de «sin resultado», retrieval.hybrid.MIN_CONCEPT_ITEMS), lo
# rotulado con el concepto pedido no se muestra. En la práctica es un interruptor: en la base real todo surtido
# testimonial queda bajo el 1 % (el vertical más chico tiene más de mil documentos), así que siempre se oculta; solo en
# un catálogo chico (los de prueba, de decenas de productos) dos productos pasan el 1 % y se siguen mostrando.
TESTIMONIAL_SHARE = 0.01


def _focus(hits, result: RetrievalResult, capped: bool = False):
    """Si la consulta nombra conceptos (`result.query_concepts`), solo esos: pedir cigarrillos no debe traer cerveza.

    - "Sin resultado" no muestra nada, nombre o no un concepto: mostrar una pizza a quien pidió kebab, o los vecinos
      de un coseno bajo τ (sin concepto ni ocasión, el de la búsqueda agrupada: «sofá de tres cuerpos» en Turbo traía
      pisco Tres Erres), sería inventar una respuesta (y la demanda no se anotaría). Tampoco los pocos productos de
      un concepto que el vertical casi no tiene (bajo TESTIMONIAL_SHARE), que suelen ser otra cosa con su etiqueta: un
      cable HDMI para «televisor 55 pulgadas» en Turbo, un pack de regalo para «cerveza en lata» en el Mall.
    - Con tope de precio (`capped`), si nada del concepto pedido cabe bajo el tope tampoco se muestra otra cosa:
      El agente dice cuánto cuesta lo más barato de lo pedido.
    - Si nada de lo encontrado es del concepto pedido, solo se muestra lo que lo dice en su nombre (`_names_query`):
      «sándwiches» en Express trae los sándwiches rotulados como empanadas, pero «pañales» en restaurantes no trae el
      postre con «panal» que el stemming juntaba. Rige también si el vertical vende el concepto: lo que calza solo un
      número o una palabra de la descripción puede dejar fuera de lo encontrado los productos del concepto, y
      «neumáticos aro 15» en Express traía jugos en polvo de 15 g. El buscador agrupado muestra las verticales donde
      sí hay del concepto; el agente, además, busca por el nombre del concepto y dice dónde más está («También en»).
      No rige si la consulta nombra una ocasión («algo para el asado» en Licores) o un concepto
      amplio (`broad` en taxonomy.toml: «picoteo»): ahí lo pedido son productos de varios tipos que su nombre no dice.
    - El foco no cede ante productos de otro concepto que calzan las palabras: esa coincidencia mira todo el texto y
      el stemming junta palabras («flores» calza con azúcar flor). Que el concepto de la consulta (keywords) y el de
      los productos (categoría) coincidan se asegura en la taxonomía.
    """
    concepts = result.query_concepts
    if not concepts:
        return [] if result.unmet else hits
    if result.unmet and (result.concept_share or 0.0) < TESTIMONIAL_SHARE:
        return []
    matching = [h for h in hits if h.concept_id in concepts]
    if matching:
        return matching
    if result.unmet or capped:
        return []
    if _broad_request(result.query, concepts):
        return hits
    return [h for h in hits if _names_query(h.content, result.query)]


def _broad_request(query: str, concepts: list[str]) -> bool:
    """¿Pide productos de varios tipos? Una ocasión («algo para el asado») o un concepto amplio («picoteo»)."""
    taxonomy = load_taxonomy()
    return named_occasion(query) is not None or any(
        c in taxonomy.concepts and taxonomy.concepts[c].broad for c in concepts
    )


# Palabras que el nombre de un producto no necesita repetir: de enlace («detergente para ropa») y de relleno («algo
# para…», «lo que…», «mi…»); además de las de saludo y pedido (text.FILLER_WORDS).
_NAME_SKIP = FILLER_WORDS | frozenset(
    {"a", "al", "algo", "con", "de", "del", "el", "en", "la", "las", "lo", "los", "mi", "para", "que", "sin", "y"}
)


def _name_words(text: str) -> list[str]:
    """Las palabras sin tildes, como `text.tokens`, pero con la ñ: «pañal» no es «panal»."""
    marked = unicodedata.normalize("NFC", text.lower()).replace("ñ", "\x00")
    return [w.replace("\x00", "ñ") for w in re.findall(r"[a-z0-9\x00]+", _without_marks(marked))]


def _without_marks(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn")


def _forms(word: str) -> set[str]:
    """La palabra y sus singulares posibles: «limones» → limones, limone, limon; «sándwiches» → … sandwich."""
    forms = {word}
    if word.endswith("s") and len(word) > 3:
        forms.add(word[:-1])
    if word.endswith("es") and len(word) > 4:
        forms.add(word[:-2])
    return forms


def _names_query(content: str, query: str) -> bool:
    """¿El nombre dice todas las palabras de la consulta? El nombre es lo que va antes del primer «. » del documento
    (search_documents lo arma así: nombre, marca, presentación, categoría…; un nombre con «. » adentro queda cortado
    ahí). Palabras enteras sin tildes y con la ñ, en singular o plural (s/es) de cualquiera de los dos lados:
    «limones» dice Limón y «sándwiches», Sándwich; «pañales» no dice Panal."""
    name = set().union(*(_forms(w) for w in _name_words(content.split(". ", 1)[0])))
    wanted = [w for w in _name_words(query) if normalize(w) not in _NAME_SKIP]
    return bool(wanted) and all(_forms(w) & name for w in wanted)


def _allowed(concept_id: str | None, requested: list[str], strict: bool = False) -> bool:
    """Los conceptos sensibles (medicamentos, salud sexual, tabaco, vapeo, adultos) solo aparecen si se piden
    por su nombre: nunca por un síntoma, una ocasión o la cercanía vectorial (regla 6, Ley 20.105). Con `strict`
    (síntomas o farmacia), lo que no tiene concepto tampoco: ahí suele ser un medicamento sin categoría mapeada
    (laxantes, analgésicos, antidiarreicos)."""
    if concept_id is None:
        return not strict
    return concept_id not in _sensitive() or concept_id in requested


def _verticals_for(conn: Connection, concept_id: str, current_vertical: str | None) -> list[str]:
    verticals = ranked_verticals(conn, [concept_id])
    # Primero otros verticales (el valor de la propuesta es cruzar), después el actual.
    return [v for v in verticals if v != current_vertical] + [v for v in verticals if v == current_vertical]


# Una oferta del agente no sale de una tienda que Rappi rotula Farmacia, Sex shop o Smoking shop, esté en la vertical
# que esté: entre las tiendas que quedan, vale la más barata.
_OFFER_STORES = """
                     AND NOT EXISTS (SELECT 1 FROM store_verticals own
                                     WHERE own.store_id = l.store_id AND own.subvertical = ANY(%(blocked)s))"""


def _with_prices(conn: Connection, vertical: str, hits, offer: bool = False, adult_ok: bool = False) -> list[Product]:
    catalog_ids = [h.entity_id for h in hits if h.entity_type == "catalog_item"]
    menu_ids = [h.entity_id for h in hits if h.entity_type == "menu_item"]
    prices: dict[tuple[str, str], tuple] = {}
    store_filter = _OFFER_STORES if offer else ""
    if catalog_ids:
        # Solo ofertas vigentes, con la misma regla que la búsqueda (v_latest_offers): una sucursal que la última
        # corrida de su formato ya no bajó no pone el precio, así el tope y el precio mostrado coinciden.
        # El precio, el precio anterior y la tienda (id y nombre) son los de una misma oferta: la más barata de las
        # tiendas que la app abre con este producto en un pasillo (como /catalog/stores). Una tienda sin pasillos,
        # importada de un CSV antiguo, no tiene página: sin ninguna que se abra vale la oferta más barata de todas y
        # el id es nulo. El pasillo va como LEFT JOIN (uno por llave) y la vertical como EXISTS: como subconsulta, el
        # pasillo recorría todos los pasillos raíz dos veces y la vertical se armaba entera (−2,5 ms por búsqueda).
        for pid, name, price, real, store, age, store_id, presentation in conn.execute(
            f"""WITH offers AS (
                   SELECT sp.master_product_id, ci.name, l.price, l.real_price, l.store_id,
                          btrim(coalesce(b.name, s.name)) AS store, ci.is_alcoholic OR ci.age_restricted AS adult,
                          ci.presentation, a.store_id IS NOT NULL AS openable
                   FROM store_products sp
                   JOIN v_latest_offers l ON l.store_id = sp.store_id AND l.sku = sp.sku
                   JOIN stores s ON s.store_id = sp.store_id
                   LEFT JOIN brands b ON b.brand_id = s.brand_id
                   JOIN catalog_items ci ON ci.master_product_id = sp.master_product_id
                   LEFT JOIN aisles a ON a.store_id = l.store_id AND a.aisle_id = sp.aisle_id
                                     AND a.parent_aisle_id IS NULL
                   WHERE sp.master_product_id = ANY(%(ids)s::bigint[]) AND l.current
                     AND l.in_stock IS NOT FALSE{store_filter}
                     AND EXISTS (SELECT 1 FROM v_store_verticals v
                                 WHERE v.store_id = s.store_id AND v.vertical = %(vertical)s)
               )
               SELECT DISTINCT ON (master_product_id) master_product_id::text, name, price, real_price, store, adult,
                      CASE WHEN openable THEN store_id END, presentation
               FROM offers
               ORDER BY master_product_id, openable DESC, price, store_id""",  # con igual precio, siempre la misma
            {"ids": catalog_ids, "vertical": vertical, "blocked": unofferable_subverticals() if offer else []},
        ):
            prices[("catalog_item", pid)] = (name, price, real, store, age, store_id, presentation)
    if menu_ids:
        dish_concepts = {h.entity_id: h.concept_id for h in hits if h.entity_type == "menu_item"}
        for iid, name, price, real, store, store_id, section, description in conn.execute(
            """SELECT mi.item_id::text, mi.name, mp.price, mp.real_price, s.name, mi.store_id, ms.name,
                      CASE WHEN %s THEN clean_html(mi.description) END
               FROM menu_items mi
               JOIN stores s USING (store_id)
               LEFT JOIN latest_menu_prices mp ON mp.item_id = mi.item_id
               LEFT JOIN menu_sections ms ON ms.store_id = mi.store_id AND ms.section_id = mi.section_id
               WHERE mi.item_id = ANY(%s::bigint[])""",
            (offer, menu_ids),  # la descripción solo hace falta en una oferta
        ):
            # En una oferta, un plato de una sección de tragos, o sin concepto o de bebida y con una descripción (o, sin
            # concepto, una sección de botellas o vinos) que nombra alcohol, cuenta como +18 (offers/guards.py).
            unknown = alcohol_in_description(description, dish_concepts[iid], section) if offer else False
            adult = offer and (alcohol_section(section) or unknown)
            prices[("menu_item", iid)] = (name, price, real, store, adult, store_id, None)
    taxonomy = load_taxonomy()
    products = []
    for hit in hits:
        found = prices.get((hit.entity_type, hit.entity_id))
        if found is None:  # sin precio vigente en el vertical (agotado o sin stock): no se ofrece
            continue
        name, price, real, store, age, store_id, presentation = found
        # En una oferta, un nombre que dice alcohol cuenta como +18 aunque la tienda no lo marque (offers/guards.py).
        age = age or (offer and alcohol_in_name(hit.entity_type, name, hit.concept_id))
        if offer and age and not adult_ok:  # +18 aunque su concepto sea corriente: el catálogo lo marca
            continue
        if offer and baby_in_name(hit.entity_type, name):  # de bebé aunque su concepto sea corriente: ni en un kit
            continue
        concept = taxonomy.concepts.get(hit.concept_id) if hit.concept_id else None
        prefix = "cat" if hit.entity_type == "catalog_item" else "menu"
        products.append(
            Product(
                id=f"{prefix}-{hit.entity_id}",
                entity_type=hit.entity_type,
                entity_id=hit.entity_id,
                name=name,
                vertical=hit.vertical,
                concept=hit.concept_id,
                # Un precio de relleno ($0, $1) cuenta como desconocido: el producto no se ofrece.
                price_value=float(price) if price is not None and price >= MIN_PRICE else None,
                before_value=float(real) if real is not None else None,
                store=store or hit.metadata.get("restaurante"),
                img=hit.metadata.get("imagen"),
                age_restricted=bool(age) or bool(concept and concept.age_restricted),
                store_id=store_id,
                presentation=presentation or None,
            )
        )
    return [p for p in products if p.price_value is not None]
