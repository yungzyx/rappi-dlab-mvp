"""El agente, un turno de conversación: entender → herramientas → componer → verificar → registrar.

Reglas de conducta (docs/diseno-ia.md §4) que se aplican aquí, en código:
1. Solo productos recuperados de la base, con precio vigente.        → tools.search_products
2. La respuesta sale del vertical actual; lo cruzado va aparte.       → `suggestion`
3. Máximo 1 sugerencia cruzada por respuesta y 1 por tema por sesión. → `shown_topics`
4. Si no encuentra, lo dice y lo marca como demanda no satisfecha.    → `unmet`
5. Si es ambiguo entre verticales, pregunta.                          → intent "aclarar"
6. Sensibles, alcohol, farmacia, bebé y salud: nunca por iniciativa propia ni como complemento
   (offers/guards.py); si se piden, +18 y farmacia con aviso.         → tools + avisos
   Tampoco da consejo médico («¿qué le doy?»): lo ve un médico o el químico farmacéutico. → intent "consejo"
7. En modo "Rappi hoy" no hay sugerencias cruzadas ni aprendizaje.
"""

import copy
import re
from dataclasses import dataclass, field, replace

from psycopg import Connection

from ..concepts.taxonomy import load_taxonomy
from ..embeddings.base import MemoizedQueryEmbedder, TextEmbedder
from ..offers.guards import is_offerable, offerable_vertical, unofferable_subverticals
from ..text import normalize, tokens
from .compose import Draft, TemplateComposer
from .compose import _mid_sentence as _mid
from .glossary import load_glossary
from .tools import (
    VERTICAL_LABELS,
    Suggestion,
    clp,
    search_products,
    search_remedies,
    suggest_complement,
)
from .understand import CHILD_WORDS, Intent, Understander
from .verticals import MIN_ITEMS_ELSEWHERE, available_elsewhere, ranked_verticals

PROTOTYPE_VERTICALS = {  # ids del prototipo (prototipo-app/src/screens/vertical/data.js)
    "supermercado": "grocery",
    "licores": "liquor",
    "farmacia": "pharmacy",
    "mall": "retail",
    "conveniencia": "express",
    "turbo": "express",
    "chocolateria": "chocolates",
    "restaurantes": "restaurants",
}


@dataclass
class Context:
    vertical: str | None = None  # vertical de la pantalla actual (código del backend)
    profile: dict[str, float] = field(default_factory=dict)  # interés por concepto
    shown_topics: list[str] = field(default_factory=list)  # conceptos ya sugeridos en la sesión
    mode: str = "propuesta"  # propuesta | actual ("Rappi hoy")
    previous: dict | None = None  # pedido anterior de la conversación: {query, concepts, vertical, product_ids}
    user_id: str | None = None  # en «Propuesta», sus compras cruzadas y su combinación ordenan el complemento


CHEAP_POOL = 24  # «barato»: reordenar solo los 6 más relevantes no daba lo más barato
MIN_SHOWN = 3  # menos productos se completan con la búsqueda por el nombre del concepto
MIN_ELSEWHERE = 2  # productos con el detalle pedido para cambiar de vertical: con uno solo suele ser casualidad
MIN_HOME_ITEMS = MIN_ITEMS_ELSEWHERE  # con menos productos del concepto, la pantalla actual no es donde buscarlo
RECOMMEND_INTERESTS = 3  # «qué me recomiendas» prueba hasta estos intereses antes de pasar a los ejemplos
# Sin un remedio que nombre el síntoma, Mochi no elige uno (antes, los analgésicos): lo dice y muestra lo de cuidarse.
NO_REMEDY = (
    "No encontré en Farmacia un remedio para eso, y no te puedo recomendar uno: pregúntale al químico farmacéutico."
)
ADVICE_TEXT = "No puedo decirte qué remedio tomar o dar, ni cuánto: eso lo ve un médico o un químico farmacéutico 💊."
ADVICE_CHILD = " Pregúntale a su pediatra."
ADVICE_URGENT = " Si es urgente, llama al SAMU (131)."
ADVICE_NAME = " Si ya sabes qué remedio buscas, escríbeme su nombre."
REMEDY_WORDS = {"remedio", "remedios", "medicamento", "medicamentos", "pastilla", "pastillas", "algo", "para"}
# Palabras de un pedido que no son un detalle que deba decir el nombre del producto («lúcuma» en «helado de lúcuma» sí).
NOT_DETAIL = {
    *("para", "algo", "unos", "unas", "como", "pero", "bien", "solo", "menos", "otra", "otro", "marca", "tipo"),
    *("sabor", "talla", "grande", "grandes", "chico", "chica", "mediano", "mediana", "familiar", "unidades"),
    *("litro", "litros", "kilo", "kilos", "helada", "heladas", "frias", "fria", "frio", "rico", "rica", "ricos"),
    *("buena", "bueno", "buenos", "quiero", "tienen", "venden", "preparado", "preparada", "barato", "barata"),
    *("baratos", "baratas", "caro", "cara", "caros", "caras", "premium", "mejor", "opcion", "segunda", "primera"),
    *("pastilla", "pastillas", "capsulas", "comprimidos", "tabletas", "remedio", "remedios", "producto", "productos"),
    # para quién y medidas: los nombres lo dicen de otras formas («Men», «Kids», «FPS 50»)
    *("hombre", "hombres", "mujer", "mujeres", "adulto", "adultos", "nino", "ninos", "nina", "ninas", "factor"),
    *("persona", "personas", "porcion", "porciones", "docena", "docenas"),
}
# Detalles que el nombre del producto dice de otra forma: «para celíacos» es «sin gluten».
DETAIL_ALIASES = {
    **dict.fromkeys(("celiaco", "celiaca", "celiacos", "celiacas"), ("gluten", "sin gluten", True)),
    **dict.fromkeys(("diabetico", "diabetica", "diabeticos", "diabeticas"), ("azucar", "sin azúcar", True)),
}


class RappiAgent:
    def __init__(self, embedder: TextEmbedder | None = None, composer=None):
        self.embedder = embedder
        self.composer = composer or TemplateComposer()
        self.understander = Understander()
        self.taxonomy = load_taxonomy()
        # Las palabras con que se nombra cada concepto: no son un detalle del producto («helado» en «helado de…»).
        self._concept_words = {
            c.id: {w for kw in (c.name, *c.keywords, *c.query_keywords) for w in tokens(kw)}
            for c in self.taxonomy.concepts.values()
        }
        # «sin carne» es una forma de nombrar lo vegano: ese «sin» no excluye nada
        self._concept_phrases = {
            c.id: {normalize(kw) for kw in (*c.keywords, *c.query_keywords)} for c in self.taxonomy.concepts.values()
        }

    def reply(self, conn: Connection, message: str, ctx: Context | None = None, offer: bool = False) -> dict:
        """Con `offer`, la respuesta es algo que el agente propone sin que se lo pidan (el «Por tu interés en…» de
        «qué me recomiendas»): sus productos pasan por las guardias de offers/guards.py
        (`search_products(..., offer=True)`).

        Un turno embebe cada texto una sola vez (con tope de precio, detalle o reintento la misma consulta se busca
        varias veces): corre en una copia del agente con su propia memoria, porque el mismo agente atiende varios
        requests a la vez."""
        turn = copy.copy(self)
        if self.embedder is not None:
            turn.embedder = MemoizedQueryEmbedder(self.embedder)
        return turn._reply(conn, message, ctx, offer)

    def _reply(self, conn: Connection, message: str, ctx: Context | None, offer: bool) -> dict:
        ctx = ctx or Context()
        intent = self.understander.understand(conn, message, ctx.vertical, previous=ctx.previous)
        if intent.kind == "recomendar":  # «qué me recomiendas»: lo que le gusta; sin perfil, ejemplos
            return self._recommend(conn, intent, ctx)
        if intent.kind in (
            "saludo",
            "gracias",
            "vacio",
            "ayuda",
            "envio",
            "ofertas",
            "fuera",
            "pedido",
            "receta",
            "memoria",
        ):
            return self._small_talk(intent, ctx)
        if intent.kind == "aclarar":
            return self._clarify(intent)
        if intent.kind == "servicio":
            return self._service(conn, intent, ctx)
        if intent.kind == "consejo":
            return self._advice(intent)
        if intent.kind == "que_es":
            return self._what_is(conn, intent, ctx, offer)
        if intent.kind == "acompanar":
            return self._goes_with(conn, intent, ctx, offer)
        vertical = intent.vertical or ctx.vertical or "supermercado"
        # Una ocasión dicha sin nombrar productos («una cena romántica», «algo para el carrete»): Mochi responde con lo
        # que puede proponer por su cuenta (offers/guards.py), sin el alcohol de la ocasión; si se nombra («cerveza para
        # el carrete»), se busca como en el buscador. Si nada de la ocasión se puede proponer (guagua, me siento mal),
        # el tema lo puso la persona y queda igual.
        if intent.kind == "ocasion" and not intent.explicit_concepts and not intent.symptom:
            proposable = [c for c in intent.concepts if is_offerable(self.taxonomy.concepts[c])]
            if proposable and len(proposable) < len(intent.concepts):
                intent = replace(intent, concepts=proposable)
                if not (intent.explicit_vertical or ctx.vertical or self.taxonomy.occasions[intent.occasion].vertical):
                    vertical = next(iter(_ranked_for(conn, proposable)), "supermercado")
        # Tampoco lleva a Licores por su cuenta («algo salado»: los snacks pesan más allá): sin alcohol nombrado, ni la
        # pantalla ni la mención de Licores, la vertical más típica entre las que propone.
        alcohol = any(c in self.taxonomy.concepts and self.taxonomy.concepts[c].age_restricted for c in intent.concepts)
        if vertical == "licores" and intent.concepts and not (alcohol or intent.explicit_vertical or ctx.vertical):
            vertical = next(iter(_ranked_for(conn, intent.concepts[:1])), "supermercado")
        # «vino» desde Farmacia: si la pantalla actual casi no tiene el concepto, se busca donde está y se dice.
        missing = None  # (vertical donde no está, qué, cuántos hay allí) para decirlo
        home = self._home_for(conn, intent, vertical, offer) if vertical == ctx.vertical else None
        if home:
            missing = (vertical, self.taxonomy.concepts[intent.concepts[0]].name.lower(), home[1])
            vertical = home[0]
        avoided = self._avoided(intent)
        outcome = None
        no_remedy = False
        # Un síntoma sin producto ni vertical nombrados: remedios de farmacia (sin receta) que nombran el síntoma. Si
        # ninguno lo nombra («me siento mal», «tengo tos»), Mochi no elige un remedio: lo dice y muestra lo de cuidarse
        # (sopas, jugos, té), que no es salud. «remedio para la tos» nombra medicamentos, pero lo que importa es el
        # síntoma.
        remedy_only = intent.concepts == ["medicamentos"]
        if intent.symptom and (not intent.explicit_concepts or remedy_only) and not intent.explicit_vertical:
            # Se busca el síntoma, no «remedio»: esa palabra traía remedios para el estómago («remedio para la tos»).
            said = " ".join(w for w in tokens(intent.query or intent.text) if w not in REMEDY_WORDS)
            remedies = search_remedies(conn, said or intent.query or intent.text, self.embedder, intent.price_max)
            if remedies.products:
                outcome, vertical = remedies, "farmacia"
                intent = replace(intent, vertical="farmacia", concepts=["medicamentos"], kind="buscar", occasion=None)
            else:
                no_remedy = True
                care = self.taxonomy.occasions["enfermo"]
                intent = replace(
                    intent, kind="ocasion", occasion=care.id, concepts=list(care.concepts), explicit_concepts=False
                )
                if vertical == "farmacia":  # lo de cuidarse no se vende en farmacia
                    vertical = next(iter(_ranked_for(conn, list(care.concepts))), "supermercado")
        if outcome is None:
            outcome = search_products(
                conn,
                vertical,
                self._search_query(intent),
                intent.concepts,
                self.embedder,
                intent.price_max,
                k=CHEAP_POOL if intent.cheapest or intent.priciest or intent.exclude_previous or avoided else 6,
                symptom=intent.symptom,
                offer=offer,
            )
        products = outcome.products
        # «algo más sano» se entiende como ensaladas, pero esas palabras no están en los productos: si nada de lo
        # encontrado es del concepto nombrado, se busca por el nombre del concepto.
        # Con menos de MIN_SHOWN («unos puchos» traía uno) se completa con esa búsqueda, salvo en un seguimiento
        # («talla xg») o si se nombró una cadena o vertical («tienen kfc»): lo demás no es lo pedido.
        on_topic = any(p.concept in intent.concepts for p in products)
        few = len(products) < MIN_SHOWN and not intent.follow_up and not intent.explicit_vertical
        if intent.explicit_concepts and not intent.symptom and (few or not on_topic):
            concept = self.taxonomy.concepts.get(intent.concepts[0])
            retry = (
                search_products(
                    conn, vertical, concept.name, intent.concepts, self.embedder, intent.price_max, k=6, offer=offer
                )
                if concept
                else None
            )
            extra = [p for p in retry.products if p.concept in intent.concepts] if retry else []
            if extra and not on_topic:
                outcome, products = retry, retry.products
            elif extra:
                ids = {p.id for p in products}
                products = (products + [p for p in extra if p.id not in ids])[:6]
        # «helado de lúcuma»: si nada de lo mostrado dice «lúcuma», se busca entre más candidatos y, si aquí no hay,
        # en la vertical que lo tenga (salvo que se haya nombrado una).
        # Con menos de MIN_SHOWN que lo digan se buscan más entre 24 candidatos; si aquí no hay ninguno, en la
        # vertical que los tenga. Lo que lo dice va primero y, con «sin», solo eso (un vino común no es «sin alcohol»).
        detail = self._detail(intent) if intent.explicit_concepts and not intent.symptom and products else None
        if detail:
            says = [p for p in products if _names(p.name, detail[0], detail[2])]
            found = self._with_detail(conn, intent, vertical, detail, offer) if len(says[:6]) < MIN_SHOWN else None
            if found and found[0] != vertical and not says:
                missing = missing or (vertical, detail[1], 0)
                vertical, outcome, says = found
                products = says
            elif found and found[0] == vertical and len(found[2]) > len(says):
                outcome, says = found[1], found[2]
            if says:
                products = says if detail[2] else says + [p for p in products if p not in says]
        if avoided:  # «sushi sin palta»: fuera lo que nombra la palta (salvo «sin palta»); nunca se muestra igual
            products = [
                p for p in products if not any(_names(p.name, w) and not _names(p.name, w, True) for w in avoided)
            ]
        if intent.exclude_previous and ctx.previous:  # «de otra marca»: sin lo que ya se mostró
            seen = set(ctx.previous.get("product_ids") or [])
            products = [p for p in products if p.entity_id not in seen]
        if intent.cheapest:  # «barato»: lo más barato de un grupo más amplio (sin precio, al final)
            products = sorted(products, key=lambda p: (p.price_value is None, p.price_value or 0))
        elif intent.priciest:  # «uno más caro»: lo más caro primero
            products = sorted(products, key=lambda p: (p.price_value is None, -(p.price_value or 0)))
        products = products[:6]

        suggestion = None
        # «Porque llevas X»: X está en la respuesta (en una ocasión, no cualquiera de sus conceptos). Con síntomas no
        # hay venta cruzada, como tampoco «También en».
        if ctx.mode == "propuesta" and products and not intent.symptom:
            if intent.concepts:
                sources = [c for c in dict.fromkeys(p.concept for p in products) if c in intent.concepts]
            else:
                sources = [p.concept for p in products[:1] if p.concept]
            exclude = set(ctx.shown_topics) | set(intent.concepts)
            suggestion = suggest_complement(conn, sources, vertical, self.embedder, exclude, user_id=ctx.user_id)

        # Con tope de precio también es demanda no satisfecha si no existe a ningún precio. Por síntomas no: lo que
        # se muestra para cuidarse no es lo que se pidió.
        unmet = not intent.symptom and not products and outcome.result.unmet and outcome.cheapest_without_filter is None
        draft = self._draft(intent, vertical, products, outcome, suggestion, unmet)
        also_in = None if intent.symptom else self._also_in(conn, ctx, intent, products, vertical, offer)
        if self.composer.remote:  # Claude tarda segundos: la conexión no queda «idle in transaction» mientras redacta
            conn.commit()
        text = self.composer.compose(draft)
        if missing and products:
            text = _moved(missing[0], vertical, missing[1], missing[2]) + text
        if no_remedy:  # nada nombra el síntoma: no aparentar que lo de cuidarse es un remedio
            care = f" Mientras, algo para cuidarte en {VERTICAL_LABELS.get(vertical, vertical)}." if products else ""
            text = NO_REMEDY + care
        response = self._response(
            intent, vertical, text, products, suggestion, unmet, outcome.result.unmet_reason, draft
        )
        if also_in:
            response["also_in"] = also_in
        if intent.occasion == "regalo" and ctx.mode == "propuesta":  # un regalo también se puede mandar
            favor = self.taxonomy.services["rappifavor"]
            response["actions"].append(
                {"label": f"Mandarlo con {favor.name}", "route": [favor.route], "service": favor.id}
            )
            response["service"] = favor.id
        if unmet and ctx.mode == "propuesta":  # lo que no está en el catálogo, un Rappitendero lo compra donde esté
            favor = self.taxonomy.services["rappifavor"]
            response["text"] += f" Si lo venden en otra tienda, {favor.label} te lo compra y te lo lleva."
            response["actions"].append(
                {"label": f"Pedirlo con {favor.name}", "route": [favor.route], "service": favor.id}
            )
            response["service"] = favor.id
        return response

    def _recommend(self, conn: Connection, intent: Intent, ctx: Context) -> dict:
        """«Qué me recomiendas», como una oferta (`offer`). Por cada interés que Mochi puede proponer, de mayor a menor
        (hasta RECOMMEND_INTERESTS), busca su nombre y, si no trae productos del interés, su primera keyword, que es
        como se llaman sus productos (las lanas del Mall no dicen «manualidades y mercería»). Desde Farmacia o Licores,
        que Mochi no propone, o sin pantalla (la Home), busca en la vertical más típica del interés entre las que
        propone (`ranked_verticals`). Responde el primero que trae productos del interés; si ninguno, los ejemplos de
        siempre, como sin perfil: lo que no encontró no se muestra ni se anota como demanda (no lo pidió la persona).
        Los intentos se redactan con plantillas; con Claude, solo el que responde."""
        interests = self._interests(ctx.profile)[:RECOMMEND_INTERESTS] if ctx.mode == "propuesta" else []
        trial = copy.copy(self)
        trial.composer = TemplateComposer()
        for interest in interests:
            vertical = ctx.vertical
            if not vertical or not offerable_vertical(vertical):
                vertical = next((v for v in ranked_verticals(conn, [interest]) if offerable_vertical(v)), None)
                if vertical is None:
                    continue
            concept = self.taxonomy.concepts[interest]
            keyword = [k for k in concept.keywords[:1] if normalize(k) != normalize(concept.name)]  # «Pizza», «pizza»
            for query in (concept.name, *keyword):
                response = trial._reply(conn, query, replace(ctx, vertical=vertical), offer=True)
                # Solo productos del interés (no lo que solo dice la palabra: «Set Parrillero Con Forma De Guitarra»), y
                # de una vertical que Mochi propone.
                found = any(p["concept"] == interest for p in response["products"])
                if not found or not offerable_vertical(response["vertical"]):
                    continue
                if self.composer.remote:
                    response = self._reply(conn, query, replace(ctx, vertical=vertical), offer=True)
                response["text"] = f"Por tu interés en {concept.label.lower()} 😉 " + response["text"]
                return response
        return self._small_talk(replace(intent, kind="ayuda"), ctx)

    def _advice(self, intent: Intent) -> dict:
        """«¿Qué le doy?», «qué me tomo», «dosis»: Mochi no da consejo médico ni muestra remedios (sería elegirlos por
        la persona). Lo dice, nombra a quién preguntarle y deja ir a Farmacia; con el nombre de un remedio, lo busca."""
        child = ADVICE_CHILD if set(tokens(intent.text)) & CHILD_WORDS else ""
        response = _base(intent, ADVICE_TEXT + child + ADVICE_URGENT + ADVICE_NAME)
        response["actions"] = [{"label": "Ir a Farmacia", "vertical": "farmacia"}]  # la app la lleva a su pantalla
        return response

    def _what_is(self, conn: Connection, intent: Intent, ctx: Context, offer: bool) -> dict:
        """«¿Qué es un poke?»: la ficha del plato (agent/glosario.toml, escrita a mano) y lo que hay de él, buscado como
        cualquier pedido (con sus guardias). Si no hay, la ficha y el «No encontré» de siempre."""
        dish = load_glossary()[intent.dish]
        # Sin el pedido anterior: «¿qué es una paella?» tras «pañales» no es «pañales paella».
        response = self._reply(conn, dish.query, replace(ctx, previous=None), offer)
        response["text"] = f"{dish.text} {response['text']}"
        response["intent"] = {**response["intent"], "kind": "que_es", "dish": dish.id}
        return response

    def _goes_with(self, conn: Connection, intent: Intent, ctx: Context, offer: bool) -> dict:
        """«¿Con qué acompaño un salmón?»: el complemento de ese concepto, elegido como la sugerencia cruzada
        (`suggest_complement`, con las guardias de offers/guards.py: nunca alcohol, farmacia, bebé ni salud), como
        respuesta principal. Sin complemento, lo dice y muestra lo que se nombró."""
        base = self.taxonomy.concepts[intent.concepts[0]]
        vertical = ctx.vertical or next(iter(_ranked_for(conn, [base.id])), None) or "supermercado"
        found = (
            suggest_complement(conn, [base.id], vertical, self.embedder, {base.id}, user_id=ctx.user_id)
            if ctx.mode == "propuesta" and not base.sensitive
            else None
        )
        if found is None:  # en «Rappi hoy» no sugiere: busca lo nombrado, sin decir que no se le ocurre nada
            response = self._reply(conn, intent.query, replace(ctx, previous=None), offer)
            if ctx.mode == "propuesta":
                response["text"] = f"No se me ocurre con qué acompañar {_mid(base.label)}. {response['text']}"
            return response
        complement = self.taxonomy.concepts[found.concept]
        label = VERTICAL_LABELS.get(found.vertical, found.vertical)
        text = f"Para acompañar {_mid(base.label)}, te propongo {_mid(complement.label)} en {label}."
        response = _base(replace(intent, concepts=[found.concept]), text)
        response.update(
            vertical=found.vertical,
            prototype_vertical=PROTOTYPE_VERTICALS.get(found.vertical),
            products=[p.to_dict() for p in found.products],
            reason=f"Va bien con {_mid(base.label)}",
            age_notice=False,  # el complemento nunca es alcohol (offers/guards.py)
        )
        response["intent"]["kind"] = "acompanar"
        return response

    def _service(self, conn: Connection, intent: Intent, ctx: Context) -> dict:
        """Servicio sin catálogo: su pantalla y, en «Propuesta», UN gancho del catálogo que lo acompaña (el primero
        con productos que no se haya mostrado en la sesión)."""
        service = self.taxonomy.services[intent.service]
        response = _base(intent, f"Para eso está {service.label}: {service.pitch}.")
        action = {"label": f"Abrir {service.name}", "route": [service.route], "service": service.id}
        response.update(service=service.id, actions=[action])
        if ctx.mode != "propuesta":
            return response
        said = f" {normalize(intent.text)} "
        # Primero los ganchos del contexto que se nombró («playa», «nieve»); los demás solo si no tienen contexto.
        in_context = [h for h in service.hooks if any(f" {normalize(w)} " in said for w in h.when)]
        for hook in in_context + [h for h in service.hooks if not h.when]:
            if hook.concept in ctx.shown_topics or not is_offerable(self.taxonomy.concepts[hook.concept]):
                continue
            for vertical in [v for v in ranked_verticals(conn, [hook.concept]) if offerable_vertical(v)][:2]:
                outcome = search_products(conn, vertical, hook.query, [hook.concept], self.embedder, k=4, offer=True)
                products = [p for p in outcome.products if p.concept == hook.concept][:3]
                if products:
                    suggestion = Suggestion(hook.concept, service.id, vertical, service.reason, products)
                    response["suggestion"] = self._suggestion(suggestion, question=hook.question)
                    response["reason"] = suggestion.reason
                    return response
        return response

    # ── Partes ────────────────────────────────────────────────────────────────
    def _search_query(self, intent: Intent) -> str:
        """Lo que se pidió explícitamente manda; la ocasión solo completa cuando no se nombró nada."""
        if intent.kind == "ocasion" and intent.occasion and not intent.explicit_concepts:
            return " ".join(self.taxonomy.concepts[c].name for c in intent.concepts[:4])
        return intent.query or intent.text

    def _small_talk(self, intent: Intent, ctx: Context) -> dict:
        interest = self._top_interest(ctx.profile) if ctx.mode == "propuesta" else None
        label = self.taxonomy.concepts[interest].label.lower() if interest else None
        text = self.composer.compose(Draft(kind=intent.kind, interest_label=label, learns=ctx.mode == "propuesta"))
        response = _base(intent, text)
        if intent.kind == "ayuda":  # ejemplos que se pueden tocar: nadie empieza frente a un campo vacío
            response["actions"] = [
                {"label": "🍣 Algo de sushi", "query": "sushi"},
                {"label": "🍽️ ¿Qué almuerzo hoy?", "query": "tengo hambre"},
                {"label": "🤒 Tengo fiebre", "query": "tengo fiebre"},
                {"label": "🎉 Arma un carrete", "query": "algo para el carrete"},
            ]
        return response

    def _clarify(self, intent: Intent) -> dict:
        concept = self.taxonomy.concepts[intent.concepts[0]]
        labels = [VERTICAL_LABELS[v] for v in intent.options]
        text = self.composer.compose(Draft(kind="aclarar", concept_label=concept.label, options=labels))
        response = _base(intent, text)
        response["actions"] = [
            {
                "label": "Pedir de un restaurante" if v == "restaurantes" else f"Comprar en {VERTICAL_LABELS[v]}",
                "query": intent.text,
                "vertical": v,
                "route": PROTOTYPE_VERTICALS.get(v),
            }
            for v in intent.options
        ]
        return response

    def _draft(self, intent, vertical, products, outcome, suggestion: Suggestion | None, unmet: bool) -> Draft:
        concept = self.taxonomy.concepts.get(intent.concepts[0]) if intent.concepts else None
        occasion = self.taxonomy.occasions.get(intent.occasion) if intent.occasion else None
        if products:
            kind = "resultados"
        elif intent.price_max is not None and outcome.cheapest_without_filter is not None:
            kind = "sin_precio"
        else:
            kind = "sin_resultado"  # se dice igual; solo se registra como demanda si `unmet`
        suggestion_concept = self.taxonomy.concepts.get(suggestion.concept) if suggestion else None
        # Si ningún resultado es del concepto pedido (la búsqueda calzó por palabras), no se rotulan con ese concepto.
        off_topic = products and intent.concepts and not any(p.concept in intent.concepts for p in products)
        return Draft(
            kind=kind,
            query=intent.query or intent.text,
            concept_label=None if off_topic else _label(occasion, concept),
            vertical_label=VERTICAL_LABELS.get(vertical, vertical),
            product_names=[p.name for p in products],
            price_max=clp(intent.price_max),
            cheapest=clp(outcome.cheapest_without_filter.price_value) if outcome.cheapest_without_filter else None,
            suggestion_reason=suggestion.reason if suggestion else None,
            suggestion_label=suggestion_concept.label.lower() if suggestion_concept else None,
            # +18 si lo muestra la respuesta o la sugerencia cruzada (ambas tienen botón para agregar).
            age_notice=any(p.age_restricted for p in [*products, *(suggestion.products if suggestion else [])]),
            unmet=unmet,
            people=intent.people,
            portion=occasion.portion if occasion else None,
        )

    def _response(self, intent, vertical, text, products, suggestion, unmet, unmet_reason, draft: Draft) -> dict:
        response = _base(intent, text)
        response.update(
            vertical=vertical,
            prototype_vertical=PROTOTYPE_VERTICALS.get(vertical),
            products=[p.to_dict() for p in products],
            unmet=unmet,
            unmet_reason=unmet_reason if unmet else None,
            age_notice=draft.age_notice,
        )
        if suggestion:
            response["suggestion"] = self._suggestion(suggestion)
            response["reason"] = suggestion.reason  # el prototipo muestra `reason` en el primer nivel
        return response

    def _suggestion(self, suggestion: Suggestion, question: str | None = None) -> dict:
        label = self.taxonomy.concepts[suggestion.concept].label.lower()
        return {
            "reason": suggestion.reason,
            "question": question or f"¿Te tinca sumar {label}?",
            "vertical": suggestion.vertical,
            "prototype_vertical": PROTOTYPE_VERTICALS.get(suggestion.vertical),
            "concept": suggestion.concept,
            "products": [p.to_dict() for p in suggestion.products],
            "basis": suggestion.basis,  # las fuentes del motor que la eligieron (`combinacion`, `compra_cruzada`)
        }

    def _also_in(self, conn, ctx: Context, intent: Intent, products, vertical, offer: bool = False) -> dict | None:
        """Multiverticalidad visible: en qué otras verticales también hay lo que pidió (no es una sugerencia:
        no se registra ni cuenta para la regla 3). Nunca para conceptos sensibles, en "Rappi hoy" ni cuando habla de
        síntomas (quien dice que está enfermo no necesita ver dónde más venden jugo). Si aquí no hay nada, el concepto
        es el pedido: justo entonces importa decir dónde sí está ("vodka" en farmacia). Si la respuesta es una oferta de
        el agente (`offer`), tampoco nombra las verticales ni las tiendas que no propone (offers/guards.py)."""
        concept_id = next((p.concept for p in products if p.concept), None)
        if not products and intent.concepts:
            concept_id = intent.concepts[0]
        concept = self.taxonomy.concepts.get(concept_id) if concept_id else None
        if ctx.mode != "propuesta" or concept is None or concept.sensitive:
            return None
        if offer:  # se piden todas y se cortan después: las que no se proponen no le quitan el lugar a las que sí
            verticals = _offerable_elsewhere(conn, available_elsewhere(conn, concept.id, {vertical}, limit=99))[:3]
        else:
            verticals = available_elsewhere(conn, concept.id, {vertical})
        if not verticals:
            return None
        for v in verticals:
            v["prototype_vertical"] = PROTOTYPE_VERTICALS.get(v["vertical"])
        return {"concept": concept.id, "label": concept.label, "verticals": verticals}

    def _home_for(self, conn: Connection, intent: Intent, vertical: str, offer: bool = False) -> tuple[str, int] | None:
        """(vertical, productos del concepto en `vertical`) donde buscar un concepto nombrado que `vertical` casi no
        tiene (menos de MIN_HOME_ITEMS), si otra tiene al menos eso. Nunca si se nombró la vertical o en síntomas. En
        una oferta (`offer`), solo una vertical que Mochi propone: «en chocolaterías casi no hay gaseosas» llevaba a
        Licores."""
        if not intent.explicit_concepts or intent.explicit_vertical or intent.symptom or intent.follow_up:
            return None
        concept = intent.concepts[0]
        items = dict(
            conn.execute("SELECT vertical, items FROM concept_assortment WHERE concept_id = %s", (concept,)).fetchall()
        )
        if items.get(vertical, 0) >= MIN_HOME_ITEMS:
            return None
        home = next(
            (
                v
                for v in ranked_verticals(conn, [concept])
                if items.get(v, 0) >= MIN_HOME_ITEMS and (not offer or offerable_vertical(v))
            ),
            None,
        )
        return (home, items.get(vertical, 0)) if home else None

    def _avoided(self, intent: Intent) -> list[str]:
        """Lo que se pide «sin»: «palta» en «sushi sin palta». No cuenta si es parte del concepto («algo sin carne»
        es vegano y su «carne vegetal» sirve)."""
        if not intent.explicit_concepts or intent.symptom:
            return []
        phrases = {p for c in intent.concepts for p in self._concept_phrases.get(c, ())}
        words = _query_words(intent.query)
        return [
            _stem(b)
            for a, b in zip(words, words[1:], strict=False)
            if a == "sin" and len(b) >= 3 and f"sin {b}" not in phrases
        ]

    def _detail(self, intent: Intent) -> tuple[str, str, bool] | None:
        """(raíz, cómo decirlo, si se pide «sin») de la primera palabra del pedido que no es el concepto ni relleno:
        «lúcuma» en «helado de lúcuma», «sin gluten» en «galletas para celíacos»."""
        concept_words = {w for c in intent.concepts for w in self._concept_words.get(c, ())}
        phrases = {p for c in intent.concepts for p in self._concept_phrases.get(c, ())}
        said = {normalize(w): w.lower() for w in intent.text.split()}
        words = _query_words(intent.query)
        for i, word in enumerate(words):
            stem = _stem(word)
            if word in DETAIL_ALIASES:
                return DETAIL_ALIASES[word]
            # tras «sin» cuenta aunque sea palabra del concepto («sandwich sin palta»), salvo «sin carne» en vegano
            free_from = i > 0 and words[i - 1] == "sin" and f"sin {word}" not in phrases
            known = set() if free_from else concept_words
            if len(word) >= 4 and word.isalpha() and not {word, stem} & (NOT_DETAIL | known):
                label = said.get(word, word).strip("¿?¡!.,")
                return stem, f"sin {label}" if free_from else label, free_from
        return None

    def _with_detail(
        self, conn: Connection, intent: Intent, vertical: str, detail: tuple[str, str, bool], offer: bool = False
    ):
        """(vertical, resultado, productos) del concepto que dicen el detalle en el nombre: entre más candidatos de
        esta vertical y, si no se nombró una, en las que más productos del concepto lo dicen. None si no hay.

        Esas verticales se buscan entre los productos con documento de búsqueda (los que tienen una oferta vigente)
        cuyo texto tiene la palabra, por el índice de `tsv_unaccent`; la expresión regular sobre el nombre, que no
        tiene índice, solo revisa esos. La palabra se busca en las formas que acepta la expresión (la raíz y sus
        plurales): el índice guarda la raíz de cada forma («kids» no es «kid»). Una palabra vacía de sentido
        («mucho», una stopword) no tiene raíz en el índice y no lleva a otra vertical."""
        stem, _, free_from = detail
        candidates = [vertical]
        if not intent.explicit_vertical:
            candidates += [
                v
                for (v,) in conn.execute(
                    """WITH forms AS (  -- con to_tsvector, una stopword no deja aviso: queda NULL y no calza nada
                           SELECT string_agg(quote_literal(lexeme), ' | ')::tsquery AS q
                           FROM unnest(to_tsvector('spanish', es_unaccent(%(forms)s)))
                       ),
                       said AS MATERIALIZED (
                           SELECT DISTINCT ic.entity_id FROM search_documents sd
                           JOIN item_concepts ic USING (entity_type, entity_id)
                           WHERE sd.entity_type = 'catalog_item' AND ic.concept_id = %(concept)s
                             AND sd.tsv_unaccent @@ (SELECT q FROM forms)
                       )
                       SELECT sv.vertical FROM said
                       JOIN catalog_items ci ON ci.master_product_id = said.entity_id::bigint
                       JOIN store_products sp USING (master_product_id) JOIN store_verticals sv USING (store_id)
                       WHERE unaccent(lower(ci.name)) ~ %(pattern)s AND sv.vertical <> %(vertical)s
                       GROUP BY 1 ORDER BY count(DISTINCT ci.master_product_id) DESC LIMIT 2""",
                    {
                        "concept": intent.concepts[0],
                        "forms": f"{stem} {stem}s {stem}es",  # lo que acepta `_name_pattern`
                        "pattern": _name_pattern(stem, free_from, sql=True),
                        "vertical": vertical,
                    },
                )
            ]
        for candidate in candidates:
            outcome = search_products(
                conn,
                candidate,
                self._search_query(intent),
                intent.concepts,
                self.embedder,
                intent.price_max,
                CHEAP_POOL,
                offer=offer,
            )
            products = [p for p in outcome.products if p.concept in intent.concepts and _names(p.name, stem, free_from)]
            products = products[:6]
            if len(products) >= (1 if candidate == vertical else MIN_ELSEWHERE):
                return candidate, outcome, products
        return None

    def _interests(self, profile: dict[str, float]) -> list[str]:
        concepts = self.taxonomy.concepts
        # Lo recomienda el agente por su cuenta («Por tu interés en…», «Veo tu interés en…»): solo intereses que puede
        # proponer, de mayor a menor (a igual puntaje, en el orden del perfil).
        allowed = {c: s for c, s in profile.items() if c in concepts and is_offerable(concepts[c])}
        return sorted(allowed, key=allowed.get, reverse=True)

    def _top_interest(self, profile: dict[str, float]) -> str | None:
        interests = self._interests(profile)
        return interests[0] if interests else None


def _ranked_for(conn: Connection, concept_ids: list[str]) -> list[str]:
    """Las verticales donde Mochi puede proponer esos conceptos, de la más típica a la menos."""
    return [v for v in ranked_verticals(conn, concept_ids) if offerable_vertical(v)]


def _offerable_elsewhere(conn: Connection, verticals: list[dict]) -> list[dict]:
    """«También en» sin las verticales que el agente no propone y sin las tiendas que Rappi rotula Farmacia, Sex shop o
    Smoking shop (el listado solo tiene sus nombres); una vertical que se queda sin tiendas se va."""
    blocked = {
        name
        for (name,) in conn.execute(
            """SELECT DISTINCT trim(s.name) FROM stores s JOIN store_verticals sv USING (store_id)
               WHERE sv.subvertical = ANY(%s)""",
            (unofferable_subverticals(),),
        )
    }
    kept = []
    for v in verticals:
        stores = [s for s in v["stores"] if s["name"] not in blocked]
        if offerable_vertical(v["vertical"]) and stores:
            kept.append({**v, "stores": stores})
    return kept


def _base(intent: Intent, text: str) -> dict:
    return {
        "text": text,
        "products": [],
        "stores": [],
        "actions": [],
        "reason": None,
        "tags": intent.concepts,
        "intent": {
            "kind": intent.kind,
            "vertical": intent.vertical,
            "concepts": intent.concepts,
            "occasion": intent.occasion,
            "price_max": intent.price_max,
            "confidence": intent.confidence,
            "query": intent.query,
            "follow_up": intent.follow_up,
            "symptom": intent.symptom,  # habló de síntomas o pidió consejo médico: la app no ofrece sus ideas debajo
        },
        "unmet": False,
        "age_notice": False,
    }


def _label(occasion, concept) -> str | None:
    if occasion and occasion.id != "enfermo":  # «opciones de me siento mal 🤒» no nombra lo que se muestra
        return f"{occasion.name.lower()} {occasion.emoji}"
    return concept.label if concept else None


def _stem(word: str) -> str:
    """Singular aproximado: «champiñones» → «champinon», «tomates» → «tomate», «paltas» → «palta»."""
    if word.endswith("es") and len(word) > 4 and word[-3] in "nrldzj":
        return word[:-2]
    return word[:-1] if word.endswith("s") and len(word) > 3 else word


def _query_words(query: str) -> list[str]:
    """Las palabras del pedido, sin el artículo tras «sin» («pizza sin las aceitunas»)."""
    return tokens(re.sub(r"\bsin (?:el|la|los|las|un|una|unos|unas) ", "sin ", normalize(query)))


def _name_pattern(stem: str, free_from: bool = False, sql: bool = False) -> str:
    """La palabra entera con su plural («sal» no es «salmón»); con `free_from`, dicha como «sin», «libre de» o «0»."""
    start, end = (r"\m", r"\M") if sql else (r"\b", r"\b")
    lead = r"(?:sin|libre de|cero|0)\s+" if free_from else ""
    return rf"{start}{lead}{stem}(?:es|s)?{end}"


def _names(name: str, stem: str, free_from: bool = False) -> bool:
    return re.search(_name_pattern(stem, free_from), normalize(name)) is not None


def _moved(here: str, there: str, what: str, count: int = 0) -> str:
    """«En X no hay…» solo si no hay ninguno; con unos pocos, «casi no hay»."""
    here, there = VERTICAL_LABELS.get(here, here), VERTICAL_LABELS.get(there, there)
    if count:
        return f"En {here} casi no hay «{what}»; en {there} hay más. "
    return f"En {here} no hay «{what}», pero en {there} sí. "
