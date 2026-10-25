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
from itertools import zip_longest

from psycopg import Connection

from ..concepts.taxonomy import load_taxonomy
from ..embeddings.base import MemoizedQueryEmbedder, TextEmbedder
from ..offers.guards import is_offerable, offerable_vertical, unofferable_subverticals
from ..text import normalize, tokens
from .compose import Draft, TemplateComposer
from .compose import _mid_sentence as _mid
from .glossary import load_glossary
from .tools import (
    _NAME_SKIP,
    VERTICAL_LABELS,
    Product,
    Suggestion,
    _forms,
    clp,
    search_products,
    search_remedies,
    suggest_complement,
)
from .understand import CHILD_WORDS, Intent, Understander
from .understand import _without_order as without_order
from .understand import _without_people as without_people
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
    previous: dict | None = None  # el turno anterior: el `conversation` de la respuesta anterior (ver _conversation)
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
# «sin X» de un régimen: el nombre tiene que decirlo (no se sabe si un helado común tiene lactosa) y, si nada lo dice,
# Mochi lo dice en vez de mostrar otra cosa. Lo demás («sin palta») es un ingrediente: fuera lo que lo nombra.
DIETS = {"carne", "lactosa", "gluten", "azucar", "alcohol", "sal", "grasa", "cafeina", "sodio"}
# Cómo lo dice el nombre, además de «sin X», «libre de X», «cero X» o «0 X» (_name_pattern), y esas palabras para
# buscarlas en el índice (_with_detail).
DIET_NAMES = {"carne": r"vegetarian[oa]s?|vegan[oa]s?|veggies?|vegetal(?:es)?", "lactosa": r"deslactosad[oa]s?"}
DIET_FORMS = {"carne": "vegetariana vegetariano vegana vegano veggie vegetal", "lactosa": "deslactosada deslactosado"}
# Cómo se busca un régimen: «sin» no se indexa y «pizza sin carne» calzaba «carne» (pepperoni, Carnivori).
DIET_SEARCH = {"carne": "vegetariana vegana veggie"}
# Tildes de lo que se dice «sin», para repetirlo (la consulta va sin tildes ni ñ: «sin azucar», «sin pina»).
ACCENTS = {
    **{"azucar": "azúcar", "cafeina": "cafeína", "pina": "piña", "jamon": "jamón", "limon": "limón", "mani": "maní"},
    **{"platano": "plátano", "sesamo": "sésamo", "atun": "atún", "salmon": "salmón", "champinon": "champiñón"},
    **{"champinones": "champiñones", "pimenton": "pimentón", "cebollin": "cebollín", "lacteos": "lácteos"},
}
# Una ocasión sin productos nombrados («cumpleaños», «once»): cada concepto se busca por su nombre y se reparten.
OCCASION_CONCEPTS = 6  # hasta estos conceptos de la ocasión
OCCASION_EACH = 6  # productos por concepto (si los demás no tienen, uno solo llena la respuesta); con orden, «otra
# opción» o «sin», OCCASION_POOL
OCCASION_POOL = 12
MAX_SHOWN_IDS = 48  # «otra opción» acumula lo ya mostrado hasta esto (lo que acepta la API en `previous`)
MAX_QUERY, MAX_CONCEPTS = 200, 10  # también lo que acepta la API en `previous` (api/app.py: PreviousTurnIn)
NAMES_SKIP = {"talla", "tamano", "sabor", "marca", "tipo"}  # «Bubu Pañal Ultra Premium G» es talla G
# «Quiero algo picante»: un antojo sin concepto se busca primero en restaurantes, con lo que lo dice en el nombre.
CRAVING = re.compile(r"^algo (?:bien |muy )?([a-z]{4,})$")
NOT_A_DISH = {None, "salsas", "aceites-condimentos"}
ADD_ON = re.compile(r"(?:salsa|extra|adicional|agregado|porcion de)\b")
ADD_ON_PRICE = 1000  # un «Picante Chile» de $430 es un agregado del ramen, no un plato
# «Algo para que mi guagua duerma»: nada que le ayude a dormir (lo ve su pediatra); lo de la hora de dormir que no es
# salud y lo dice el nombre, nunca de adulto.
SLEEP_WORDS = {"duerma", "duerman", "dormir", "duerme", "dormirse", "sueno"}
BEDTIME_CONCEPTS = ["articulos-bebe", "panales"]
BEDTIME_NAMES = re.compile(r"\b(?:dormir|noche|nocturn[oa]s?|sueno)\b")
ADULT_NAMES = re.compile(r"\b(?:adultos?|incontinencia)\b")
BEDTIME_TEXT = "Para que duerma no te puedo recomendar remedios ni nada que se tome: eso lo ve su pediatra 🧡."
BEDTIME_SHOWN = " Esto es para la hora de dormir."


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
        response = turn._reply(conn, message, ctx, offer)
        response.setdefault("conversation", None)  # un saludo, el consejo médico o una aclaración no se siguen
        return response

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
        # Un niño y dormir, sin nombrar algo que Mochi propone («pijama para que duerma» es ropa): ni remedios ni
        # suplementos («para dormir» nombra vitaminas).
        said = set(tokens(intent.text))
        offerable = any(is_offerable(self.taxonomy.concepts[c]) for c in intent.concepts if intent.explicit_concepts)
        if said & SLEEP_WORDS and said & CHILD_WORDS and not offerable:
            return self._bedtime(conn, intent)
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
        if outcome is None and not ctx.vertical:
            craving = self._craving(conn, intent, offer)
            if craving:
                outcome, vertical = craving, "restaurantes"
        # Una ocasión sin productos nombrados se reparte entre sus conceptos (ya ordenados y sin lo que no va).
        spread = outcome is None and intent.kind == "ocasion" and not intent.explicit_concepts and not intent.symptom
        if spread:
            outcome, products = self._occasion_products(conn, intent, vertical, offer)
        else:
            outcome = outcome or search_products(
                conn,
                vertical,
                self._search_query(intent),
                intent.concepts,
                self.embedder,
                intent.price_max,
                k=_pool(intent, ctx, bool(avoided)),
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
        unmet_diet = False  # «helado sin lactosa» y ningún nombre lo dice
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
            elif detail[2] and detail[0] in DIETS:  # un régimen que nada dice: no se muestra otra cosa como si lo fuera
                products, unmet_diet = [], True
        if "carnes" in intent.concepts and "carne" not in avoided:  # el seitán y la hamburguesa vegana rotulados carne
            products = [p for p in products if not _names(p.name, "carne", True)]
        if avoided:  # «sushi sin palta»: fuera lo que nombra la palta (salvo «sin palta»); nunca se muestra igual
            products = [
                p for p in products if not any(_names(p.name, w) and not _names(p.name, w, True) for w in avoided)
            ]
        if intent.exclude_previous and ctx.previous:  # «de otra marca»: sin lo que ya se mostró
            seen = set(ctx.previous.get("product_ids") or [])
            products = [p for p in products if p.entity_id not in seen]
        if not spread and (intent.cheapest or intent.priciest or intent.exclude_previous):
            # Ordenar por precio (o saltarse lo ya visto) en un grupo más amplio sube lo menos parecido: un asado «más
            # barato» traía albóndigas y los pañales talla G «más baratos», otras tallas. Si hay suficientes, solo lo
            # que dice lo pedido.
            core = _core_query(intent.query)
            named = [p for p in products if _says(p.name, core)] if core else []
            products = _by_price(named if len(named) >= MIN_SHOWN else products, intent)
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
        unmet = unmet or unmet_diet
        # «en el súper mejor» para algo que el súper no vende (un desayuno listo): existe en Rappi, no es demanda nueva.
        before = (ctx.previous or {}).get("vertical")
        elsewhere = None
        if not products and intent.follow_up and intent.explicit_vertical and before and before != vertical:
            elsewhere, unmet = VERTICAL_LABELS.get(before, before), False
        seen = bool((ctx.previous or {}).get("product_ids"))
        if not products and intent.exclude_previous and seen:  # ya vio lo que hay: no es demanda nueva
            unmet = False
        draft = self._draft(intent, vertical, products, outcome, suggestion, unmet)
        draft.elsewhere = elsewhere
        draft.other = intent.exclude_previous and seen
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
        # Lo que no se encontró en otra vertical no mueve la conversación: «otra opción» sigue con lo de antes.
        response["conversation"] = ctx.previous if elsewhere else self._conversation(intent, vertical, products, ctx)
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

    def _bedtime(self, conn: Connection, intent: Intent) -> dict:
        """«Algo para que mi guagua duerma»: Mochi no recomienda nada para dormir (un remedio o un suplemento sería
        elegirlo por la persona; antes mostraba pañales). Lo dice, nombra a su pediatra y muestra lo de la hora de
        dormir que no es salud y que el nombre lo dice (chupete nocturno, pañales de noche), nunca de adulto. Es el
        tema de la persona (su guagua), no una oferta: los artículos de bebé se muestran porque los pidió."""
        vertical = next(iter(ranked_verticals(conn, BEDTIME_CONCEPTS)), "farmacia")
        rows = []
        for concept_id in BEDTIME_CONCEPTS:
            name = self.taxonomy.concepts[concept_id].name
            outcome = search_products(conn, vertical, f"{name} noche dormir", [concept_id], self.embedder, k=12)
            rows.append(
                [
                    p
                    for p in outcome.products
                    if p.concept == concept_id
                    and BEDTIME_NAMES.search(normalize(p.name))
                    and not ADULT_NAMES.search(normalize(p.name))
                ]
            )
        products = [p for row in zip_longest(*rows) for p in row if p is not None][:6]
        intent = replace(intent, kind="buscar", concepts=BEDTIME_CONCEPTS, symptom=True)
        response = _base(intent, BEDTIME_TEXT + (BEDTIME_SHOWN if products else ""))
        response.update(
            vertical=vertical if products else None,
            prototype_vertical=PROTOTYPE_VERTICALS.get(vertical) if products else None,
            products=[p.to_dict() for p in products],
        )
        return response

    def _craving(self, conn: Connection, intent: Intent, offer: bool):
        """«Quiero algo picante»: un antojo sin concepto ni ocasión, dicho sin pantalla, se busca en restaurantes; si al
        menos MIN_SHOWN platos lo dicen en el nombre, son la respuesta (en el súper salía una mezcla de salsa, ramen
        instantáneo y chicharrón). Si no, la búsqueda de siempre."""
        craving = CRAVING.match(normalize(intent.query or ""))
        if not craving or intent.concepts or intent.occasion or intent.symptom or intent.explicit_vertical:
            return None
        word = craving.group(1)
        if word in {*REMEDY_WORDS, "barato", "barata", "caro", "cara", "nuevo", "nueva", "distinto", "distinta"}:
            return None
        outcome = search_products(
            conn, "restaurantes", word, None, self.embedder, intent.price_max, k=CHEAP_POOL, offer=offer
        )
        # Platos: no una salsa ni un agregado («Salsa Picante», «Extra ají», uno de $430).
        says = [
            p
            for p in outcome.products
            if _names(p.name, _stem(word))
            and p.concept not in NOT_A_DISH
            and not ADD_ON.match(normalize(p.name))
            and (p.price_value or 0) >= ADD_ON_PRICE
        ]
        return replace(outcome, products=says) if len(says) >= MIN_SHOWN else None

    def _what_is(self, conn: Connection, intent: Intent, ctx: Context, offer: bool) -> dict:
        """«¿Qué es un poke?»: la ficha del plato (agent/glosario.toml, escrita a mano) y lo que hay de él, buscado como
        cualquier pedido (con sus guardias). Si no hay, la ficha y el «No encontré» de siempre."""
        dish = load_glossary()[intent.dish]
        # Sin el pedido anterior: «¿qué es una paella?» tras «pañales» no es «pañales paella».
        # Sin pantalla, donde dice la ficha («paella» en el súper traía una paila y una hallulla).
        where = replace(ctx, previous=None, vertical=ctx.vertical or dish.vertical)
        response = self._reply(conn, dish.query, where, offer)
        # Si algo dice el plato en su nombre, solo eso: lo demás es cercanía de la búsqueda (un poke junto a la paella).
        named = [p for p in response["products"] if _says(p["name"], dish.query)]
        if named and len(named) < len(response["products"]):
            response["products"] = named
            if response["conversation"]:
                response["conversation"]["product_ids"] = [p["entity_id"] for p in named]
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
        """Lo que se pidió explícitamente manda; la ocasión solo completa cuando no se nombró nada. Lo que va «sin» se
        busca como lo dicen los nombres (_without_searched): «pizza sin carne» busca «pizza vegetariana vegana veggie»,
        «sushi sin palta», «sushi»."""
        if intent.kind == "ocasion" and intent.occasion and not intent.explicit_concepts:
            return " ".join(self.taxonomy.concepts[c].name for c in intent.concepts[:4])
        query = intent.query or intent.text
        if not self._without(intent):
            return query
        words = _query_words(query)
        kept = [w for i, w in enumerate(words) if w != "sin" and (i == 0 or words[i - 1] != "sin")]
        return " ".join([*kept, self._without_searched(intent, intent.concepts)]).strip() or query

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
            without=[label for _, label in self._without(intent)] if products else [],
            other=intent.exclude_previous,
            cheap=intent.cheapest,
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
        """Lo que se pide «sin» en un pedido con productos nombrados: «palta» en «sushi sin palta»."""
        return [stem for stem, _ in self._without(intent)] if intent.explicit_concepts else []

    def _without(self, intent: Intent) -> list[tuple[str, str]]:
        """(raíz, cómo decirlo) de lo que se pide «sin»: («palta», «sin palta») en «sushi sin palta». No cuenta si es
        parte del concepto («algo sin carne» es vegano y su «carne vegetal» sirve) ni con síntomas."""
        if intent.symptom:
            return []
        phrases = {p for c in intent.concepts for p in self._concept_phrases.get(c, ())}
        said = {normalize(w): w.lower().strip("¿?¡!.,") for w in intent.text.split()}
        words = _query_words(intent.query)
        return [
            (_stem(b), f"sin {said.get(b) or ACCENTS.get(b, b)}")
            for a, b in zip(words, words[1:], strict=False)
            if a == "sin" and len(b) >= 3 and f"sin {b}" not in phrases
        ]

    def _without_searched(self, intent: Intent, concepts: list[str]) -> str:
        """Lo que va «sin», como se busca: un ingrediente no se busca (la palabra traía justo eso), un régimen sí, como
        lo dicen los nombres («vegetariana»), y «sin alcohol» en lo que no tiene alcohol, nada."""
        said = []
        for stem, label in self._without(intent):
            if stem not in DIETS or (stem == "alcohol" and not self._alcoholic(concepts)):
                continue
            said.append(DIET_SEARCH.get(stem, label))
        return " ".join(said)

    def _occasion_products(self, conn: Connection, intent: Intent, vertical: str, offer: bool):
        """(resultado de la primera búsqueda, productos) de una ocasión sin productos nombrados («cumpleaños», «once»):
        cada concepto se busca por su nombre y se reparten, uno de cada uno en el orden de la ocasión (una sola búsqueda
        con todos los nombres traía solo decoración). Con «más barato», lo más barato de cada uno; lo que va «sin» se
        aplica a cada uno (un régimen, solo lo que lo dice; «sin alcohol» no cambia lo que no tiene alcohol)."""
        without = self._without(intent)
        refined = intent.cheapest or intent.priciest or intent.exclude_previous or without
        # Solo lo que esta vertical vende de verdad: tres quesos rallados de una chocolatería no son una cena romántica.
        items = dict(
            conn.execute(
                "SELECT concept_id, items FROM concept_assortment WHERE vertical = %s AND concept_id = ANY(%s)",
                (vertical, intent.concepts),
            ).fetchall()
        )
        sold = [c for c in intent.concepts if items.get(c, 0) >= MIN_HOME_ITEMS] or intent.concepts
        # Si queda uno solo, la búsqueda de siempre con los nombres de la ocasión: «Chocolates» solo traía galletones y
        # «Flores y regalos Chocolates…» trae cajas de bombones (una cena romántica, un regalo en chocolaterías).
        alone = self._search_query(intent)
        rows, first = [], None
        for concept_id in sold[:OCCASION_CONCEPTS]:
            concept = self.taxonomy.concepts[concept_id]
            outcome = search_products(
                conn,
                vertical,
                f"{alone if len(sold) == 1 else concept.name} {self._without_searched(intent, [concept_id])}".strip(),
                [concept_id],
                self.embedder,
                intent.price_max,
                k=OCCASION_POOL if refined else OCCASION_EACH,
                offer=offer,
            )
            first = first or outcome
            kept = [p for p in outcome.products if p.concept == concept_id and _keeps(p.name, without, concept)]
            rows.append(_by_price(kept, intent))
        return first, [p for row in zip_longest(*rows) for p in row if p is not None]

    def _conversation(self, intent: Intent, vertical: str, products: list[Product], ctx: Context) -> dict:
        """El estado que la app devuelve como `previous` en el próximo mensaje (docs/diseno/2026-10-25-mochi-
        conversacion-design.md): lo pedido con sus detalles (sin el orden por precio), los conceptos nombrados (vacío
        en una ocasión sin productos nombrados), la ocasión, la vertical, el tope, las personas, el orden, si habló de
        síntomas y lo ya mostrado (que se acumula mientras se pida «otra opción»)."""
        shown = [p.entity_id for p in products]
        if intent.exclude_previous and ctx.previous:
            shown = [*(ctx.previous.get("product_ids") or []), *shown]
        words = without_order((intent.query or normalize(intent.text)).split())
        while len(" ".join(words)) > MAX_QUERY:  # lo que acepta la API en `previous`: se pierde lo más antiguo
            words = words[1:]
        return {
            "query": " ".join(words),
            "concepts": (intent.concepts if intent.explicit_concepts else [])[:MAX_CONCEPTS],
            "occasion": intent.occasion,
            "vertical": vertical,
            "price_max": intent.price_max,
            "people": intent.people,
            "order": "barato" if intent.cheapest else "caro" if intent.priciest else None,
            "symptom": intent.symptom,
            "product_ids": list(dict.fromkeys(shown))[-MAX_SHOWN_IDS:],
        }

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
            if free_from and stem == "alcohol" and not self._alcoholic(intent.concepts):
                continue  # «bebidas sin alcohol»: no tienen; no hay que buscar las que lo dicen (ni ir a Licores)
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
                        # lo que acepta `_name_pattern` (con un régimen, también sus otros nombres: «vegetariana»)
                        "forms": f"{stem} {stem}s {stem}es {DIET_FORMS.get(stem, '') if free_from else ''}".strip(),
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

    def _alcoholic(self, concept_ids: list[str]) -> bool:
        return any(c in self.taxonomy.concepts and self.taxonomy.concepts[c].age_restricted for c in concept_ids)

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
    """La palabra entera con su plural («sal» no es «salmón»); con `free_from`, dicha como «sin», «libre de» o «0», o
    con otro nombre del régimen («vegetariana» es sin carne: DIET_NAMES)."""
    start, end = (r"\m", r"\M") if sql else (r"\b", r"\b")
    if not free_from:
        return rf"{start}{stem}(?:es|s)?{end}"
    other = f"|{DIET_NAMES[stem]}" if stem in DIET_NAMES else ""
    return rf"{start}(?:(?:sin|libre de|cero|0)\s+{stem}(?:es|s)?{other}){end}"


def _names(name: str, stem: str, free_from: bool = False) -> bool:
    return re.search(_name_pattern(stem, free_from), normalize(name)) is not None


def _keeps(name: str, without: list[tuple[str, str]], concept) -> bool:
    """Si el producto cumple lo que va «sin»: un régimen, si el nombre lo dice («sin lactosa», «vegetariana»); un
    ingrediente, si no lo nombra (o dice «sin»). «Sin alcohol» no pide nada a lo que no tiene alcohol."""
    for stem, _ in without:
        if stem == "alcohol" and not concept.age_restricted:
            continue
        if stem in DIETS and not _names(name, stem, True):
            return False
        if stem not in DIETS and _names(name, stem) and not _names(name, stem, True):
            return False
    return True


def _says(name: str, query: str) -> bool:
    """¿El nombre dice todas las palabras de la consulta (sin tildes ni ñ, en singular o plural)? Como
    tools._names_query, pero con la consulta ya normalizada: «panales» dice «Pañales»."""
    have = {form for word in tokens(name) for form in _forms(word)}
    wanted = [w for w in tokens(query) if w not in _NAME_SKIP]
    return bool(wanted) and all(_forms(w) & have for w in wanted)


def _core_query(query: str) -> str:
    """Lo pedido sin lo que no va, sin el orden por precio ni la cantidad de personas, y sin las palabras que los
    nombres se saltan («talla», «sabor»): «asado» en «asado de 6 sin sal», «panales g» en «panales talla g»."""
    words = _query_words(query)
    kept = [w for i, w in enumerate(words) if w != "sin" and (i == 0 or words[i - 1] != "sin")]
    return without_people(" ".join(w for w in without_order(kept) if w not in NAMES_SKIP))


def _pool(intent: Intent, ctx: Context, avoided: bool) -> int:
    """Cuántos candidatos buscar: 6, o CHEAP_POOL para ordenar por precio o sacar lo que no va; con «otra opción», el
    doble más lo ya mostrado (hasta MAX_SHOWN_IDS), que se va a saltar: entre los siguientes tiene que quedar algo que
    diga lo pedido («talla g»)."""
    if intent.exclude_previous:
        return 2 * CHEAP_POOL + len((ctx.previous or {}).get("product_ids") or [])
    return CHEAP_POOL if intent.cheapest or intent.priciest or avoided else 6


def _by_price(products: list[Product], intent: Intent) -> list[Product]:
    """«barato»: lo más barato primero; «uno más caro»: lo más caro (sin precio, al final)."""
    if intent.cheapest:
        return sorted(products, key=lambda p: (p.price_value is None, p.price_value or 0))
    if intent.priciest:
        return sorted(products, key=lambda p: (p.price_value is None, -(p.price_value or 0)))
    return products


def _moved(here: str, there: str, what: str, count: int = 0) -> str:
    """«En X no hay…» solo si no hay ninguno; con unos pocos, «casi no hay»."""
    here, there = VERTICAL_LABELS.get(here, here), VERTICAL_LABELS.get(there, there)
    if count:
        return f"En {here} casi no hay «{what}»; en {there} hay más. "
    return f"En {here} no hay «{what}», pero en {there} sí. "
