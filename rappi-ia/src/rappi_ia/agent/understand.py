"""Entender el mensaje: intención, vertical, conceptos, ocasión, filtros y consulta limpia (reglas; sin LLM).

Lo que hace:
- un saludo al inicio no tapa el pedido ("hola, quiero sushi" → buscar sushi), y "hola buenas" u
  "ok gracias" son saludo/agradecimiento, no una búsqueda;
- palabras completas, no substrings ("bebestibles" no es bebé);
- a la búsqueda va la consulta limpia (sin saludo, sin "quiero/tienen", sin el tope de precio);
- el vertical sale del contexto (pantalla actual), de una mención inequívoca ("en el súper", no "super 8") o del
  surtido del concepto (de todos los de la ocasión, si es una ocasión); si un concepto nombrado vive en
  restaurantes y en tiendas con surtido parecido, pregunta; sin surtido en ningún lado, el vertical de su grupo;
- los síntomas ("tengo fiebre") no llevan a medicamentos: activan el aviso de farmacia (regla 6d).
"""

import re
import unicodedata
from dataclasses import dataclass, field

from psycopg import Connection

from ..concepts.assign import concept_matcher
from ..concepts.matcher import KeywordMatcher, Match
from ..concepts.taxonomy import load_taxonomy
from ..offers.guards import is_offerable
from ..text import GREETING_WORDS, REQUEST_WORDS, THANKS_WORDS, assistant_words, normalize
from .glossary import load_glossary
from .verticals import contending_verticals, ranked_verticals

# Menciones inequívocas de un vertical. Palabras sueltas como "mall", "super" o "express" son también marcas
# ("Pall Mall", "Super 8", "Express Lider"): no cuentan.
VERTICAL_MENTIONS = {
    "supermercado": ["supermercado", "en el super", "del super", "al super", "lider", "unimarc", "jumbo", "tottus"],
    "licores": ["botilleria", "licoreria", "en licores"],
    "farmacia": ["farmacia", "farmacias", "farmasia", "cruz verde", "salcobrand", "farmacias ahumada"],
    "restaurantes": [
        "restaurante",
        "restaurant",
        "para pedir ya",
        "para llevar",
        "delivery de comida",
        # Cadenas: «mcdonalds» se buscaba en el súper y quedaba sin resultado.
        "mcdonalds",
        "mc donalds",
        "mcdonald",
        "burger king",
        "papa johns",
        "dominos",
        "domino s",
        "pizza hut",
        "juan maestro",
        "doggis",
        "telepizza",
        "subway",
        "little caesars",
        "tarragona",
        "wendys",
        "starbucks",
    ],
    "mall": ["rappi mall", "en el mall", "tienda de ropa"],
    "conveniencia": ["oxxo", "minimarket", "almacen de barrio"],
    "chocolateria": ["chocolateria"],
}
# Sobre lo que el agente recuerda: se contesta antes de buscar («olvida lo que te dije» traía un dije de joyería).
# Frases, no palabras sueltas: «olvídate de la pizza» o «lámina de privacidad» son pedidos.
MEMORY_QUESTIONS = [
    "olvida lo que",
    "olvida todo",
    "olvidate de mi",
    "olvidate de todo",
    "que sabes de mi",
    "que sabes sobre mi",
    "que recuerdas",
    "no guardes",
    "borra lo que",
    "borra mis datos",
    "mis datos personales",
    "mi privacidad",
]
# Muletillas al dictar por voz («eh quiero este una coca po»): solo se quitan en los bordes del mensaje.
VOICE_FILLERS = {"eh", "em", "mm", "mmm", "este", "ya", "mira", "oye", "po", "pues"}
_CALLS = GREETING_WORDS | THANKS_WORDS | VOICE_FILLERS  # lo que va antes de nombrar a quien se le habla
_COURTESY_AT_END = _CALLS | {"porfa", "por", "favor"}
# Lo que empieza un pedido después de llamar a alguien («mochi, quiero sushi»). Sin «porfa», «por» ni artículos:
# «quiero un mochi porfa» pide el postre.
_REQUEST_VERBS = {
    "quiero",
    "queria",
    "busco",
    "busca",
    "necesito",
    "nesecito",
    "nececito",
    "nesesito",
    "tienen",
    "tienes",
    "hay",
    "dame",
    "podrias",
    "puedes",
}
# «holaaaa», «cervezaaaa»: tres o más letras iguales seguidas son una (no hay palabras así en español).
STRETCHED = re.compile(r"([^\W\d_xw])\1{2,}")  # salvo x y w: «talla xxxl», «www»
# Risas («jajaja», «xd») y links no piden nada: se responde como a un mensaje vacío, sin anotar demanda.
LAUGHTER = re.compile(r"(?:j[aeiou]){2,}j?|(?:[aeiou]?j){2,}|x+d+|lol|jsjs\w*")
LINK = re.compile(r"https?://|www\.", re.IGNORECASE)
# Nombres genéricos de vertical, que no se buscan. Las cadenas sí («leche lider», «big mac de mcdonalds»): su
# nombre está en los productos.
GENERIC_MENTIONS = {
    *("supermercado", "en el super", "del super", "al super", "botilleria", "licoreria", "en licores"),
    *(
        "farmacia",
        "farmacias",
        "farmasia",
        "rappi mall",
        "en el mall",
        "minimarket",
        "almacen de barrio",
        "chocolateria",
    ),
}
# Artículos y preposiciones que acompañan a una vertical nombrada («en el súper», «de la farmacia»).
MENTION_LEADS = r"(?:(?:en|de|del|al|el|la|los|las)\s+)*"
# Preguntas sobre la app, no búsquedas (se buscaba la frase literal: «quien eres» traía ajos). Normalizadas.
APP_QUESTIONS = {
    "ayuda": [
        "ayuda",
        "ayudame",
        "quien eres",
        "que eres",
        "que puedes hacer",
        "que haces",
        "como funciona",
        "como te uso",
    ],
    "envio": [
        "hacen delivery",
        "hay delivery",
        "hacen despacho",
        "cuanto se demora",
        "cuanto demora",
        "cuanto tarda",
        "cuanto cuesta el envio",
        "costo de envio",
        "cuando llega",
        # horario y lugar: lo resuelve la app con la ubicación del usuario, no una búsqueda
        "de turno",
        "abierto ahora",
        "abierta ahora",
        "cerca de mi",
        "cerca de aqui",
        "horario",
        "a que hora cierra",
    ],
    "ofertas": ["ofertas", "tienen ofertas", "hay ofertas", "descuentos", "promociones", "promos"],
    # Remedios de enfermedades crónicas: son con receta, no se buscan. «La presión» sí: hay tensiómetros.
    "receta": ["hipertension", "diabetes", "colesterol", "tiroides"],
    # Un pedido en curso (estado, cancelar, reclamo): se resuelve en «Mis pedidos», no es demanda no atendida.
    "pedido": [
        "mi pedido",
        "el pedido",
        "cancelar",
        "reclamo",
        "reclamar",
        "devolucion",
        "reembolso",
        "donde viene",
        "no llega",
        "no ha llegado",
        "llego mal",
    ],
    # Fuera de tema: se contesta con humor y se vuelve a lo que el agente sabe hacer; no es demanda no atendida.
    "fuera": [
        "clima",
        "chiste",
        "capital de",
        "te quiero",
        "te amo",
        "eres tonto",
        "tonto",
        "idiota",
        "como estas",
        "quien gano",
        "noticias",
    ],
    "recomendar": [
        "me recomiendas",
        "que me recomiendas",
        "recomiendame",
        "que me sugieres",
        "sugiereme",
        "sorprendeme",
    ],
}
PACKAGED_WORDS = {
    "grano",
    "molido",
    "capsulas",
    "instantaneo",
    "nescafe",
    "kilo",
    "kilos",
    "kg",
    "paquete",
    "sobres",
    "congelada",
    "congelado",
    "congeladas",
    "congelados",
}
# Un mensaje corto que empieza así refina el anterior aunque nombre algo («con papas» tras «hamburguesa»).
REFINE_START = {
    "con",
    "sin",
    "talla",
    "mas",
    "menos",
    "de",
    "del",
    "tamano",
    "sabor",
    "marca",
    "light",
    "grande",
    "chico",
}
OTHER_WORDS = {
    "otra",
    "otro",
    "otras",
    "otros",
    "distinta",
    "distinto",
    "diferente",
    "diferentes",
    "ninguno",
    "ninguna",
}
FOLLOW_UP_FILLER = {
    "y",
    "en",
    "el",
    "la",
    "los",
    "las",
    "mejor",
    "entonces",
    "ahora",
    "tambien",
    "pero",
    "algo",
    "uno",
    "una",
}
CHEAP_WORDS = {"barato", "barata", "baratos", "baratas", "economico", "economica", "economicos", "economicas"}
PRICEY_WORDS = {"caro", "caros", "premium"}  # «cara» solo tras «más»: «crema para la cara» es la cara
# «no quiero pizza», «menos sushi»: el concepto que sigue se descarta y se saca de la consulta. «sin» también se
# descarta, pero queda en la consulta («yogurt sin azúcar» busca eso).
REFUSALS = [("no", "quiero"), ("no", "sea"), ("nada", "de"), ("menos",), ("excepto",), ("salvo",)]
LESS = {"con", "mas", "lo", "al"}
SIZE_OR_PRICE = {"mas", "menos", "talla", "tamano", "grande", "chico", "chica"}  # refinan, no son otra opción
ARTICLES = {
    "el",
    "la",
    "los",
    "las",
    "un",
    "una",
    "unos",
    "unas",
}  # «con menos azúcar» es menos, no sin: se trata como «sin»
# «para mi papá», «de mi mamá»: una persona no se busca (traía papas y mamaderas).
PEOPLE = re.compile(
    r"\b(?:(?:de|para|a|al)\s+)?(?:mi|mis|tu|su)\s+(?:mama|papa|esposo|esposa|marido|senora|hijo|hija|hijos|"
    r"polola|pololo|novia|novio|abuela|abuelo|amigo|amiga|amigos|jefe|jefa|hermano|hermana)\b"
)

SYMPTOMS = [
    "fiebre",
    "resfrio",
    "resfriado",
    "tos",
    "gripe",
    "dolor",
    "migrana",
    "me duele",
    "guata",
    "nauseas",
    "diarrea",
    "alergia",
    "enfermo",
    "enferma",
    "me siento mal",
    "remedio",
    "acidez",
    "garganta",
    "estrenido",
    "estrenida",
    "estrenimiento",
]

# Un concepto en restaurantes y en otra tienda es ambiguo si, entre las dos verticales que compiten, la de menor
# participación tiene al menos esta fracción de la otra: la misma medida que elige la vertical (agent/verticals.py).
# Con la base del 03-10 preguntan «café», «empanadas» y «platos listos».
AMBIGUITY_RATIO = 0.5
# Quien habla de síntomas no va a una botillería, aunque ahí el jugo pese más que en el súper (es para mezclar).
NOT_WHEN_SICK = {"licores"}
# Vertical natural de un grupo, para conceptos sin surtido en ningún vertical (los demás grupos van al súper).
GROUP_VERTICALS = {
    "comida": "restaurantes",
    "alcohol": "licores",
    "salud": "farmacia",
    "moda": "mall",
    "tecnologia": "mall",
    "deportes": "mall",
    "juguetes": "mall",
    "libreria": "mall",
}
# «u» suelta es «unidades», salvo que sea la «o» antes de otra o («5 lucas u otro trago»).
_UNITS = (
    r"(?:kg|kilos?|gr?|gramos?|l|litros?|ml|cc|grados?|unidades|u(?!\s+o)|personas?|porciones|cm|mts?|metros?"
    r"|piezas)"
)
_DECIMAL = r"\d+[.,]\d{1,2}(?=\s*(?:mil|lucas|k)\b)"  # «1,5 lucas»: decimales solo con mil/lucas/k
PRICE = re.compile(
    # «de 2 lucas» o «con 8 mil» también son un tope, pero solo con $ o mil/lucas/k («pack de 6» no lo es)
    r"(?:bajo|menos de|hasta|maximo|max|no mas de|por menos de|que cueste menos de"
    r"|\b(?:de|con)(?=\s*(?:\$|\d[\d.,]*\s*(?:mil|lucas)\b))"
    r"|\b(?=\d[\d.,]*\s*lucas\b))\s*"  # «10 lucas» solo es plata
    r"(\$)?\s*(" + _DECIMAL + r"|\d{1,3}(?:[.,\s]\d{3})+|\d+)(?![.,]\d)\s*(mil|lucas|k)?\b"
    r"(?:\s*(?:pesos|clp)\b)?(?!\s*" + _UNITS + r"\b)"
)


# Para cuántas personas: «somos 10», «para 4 personas», «para dos» al final y, con una ocasión, «asado de 6» al final.
# Un número que sigue con otra cosa no es gente: «pañales para 2 años», «comida para 2 perros», «mi hijo de 6».
_NUMBERS = {
    **{"dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10},
    **{"doce": 12, "quince": 15, "veinte": 20, "treinta": 30},  # sin «once»: «algo para una once para 4»
}
_HOW_MANY = r"(\d{1,2}|" + "|".join(_NUMBERS) + r")"
_WHO = r"(?:personas?|amigos|amigas|adultos|invitados)"
PEOPLE_COUNT = re.compile(
    r"\b(?:somos|seremos)\s+" + _HOW_MANY + r"\b"
    r"|\bpara\s+(?:unas?\s+)?" + _HOW_MANY + r"(?:\s+" + _WHO + r"\b|\s*$)"
)
PEOPLE_COUNT_OF = re.compile(r"\bde\s+" + _HOW_MANY + r"(?:\s+" + _WHO + r")?\s*$")  # «asado de 6» (con ocasión)
CHILD_WORDS = {
    *("hijo", "hija", "hijos", "hijas", "nino", "nina", "ninos", "ninas", "guagua", "guaguas", "bebe", "bebes"),
    *("nieto", "nieta", "sobrino", "sobrina"),
}
MAX_PEOPLE = 40
# Lo que queda de una pregunta sin pedido («qué pido hoy»): entonces la frase de pregunta no se quita.
TIME_FILLER = {"hoy", "ahora", "ya", "esta", "noche", "tarde", "manana", "dia", "algo", "rico"}
# Frases de pregunta antes de lo que se pide: «qué llevo para un asado», «se me antoja algo salado», «cosas para
# limpiar». No se buscan (traían una manta para «qué compro para un picnic»).
QUESTION_LEAD = re.compile(
    r"^(?:(?:que|como)\s+(?:llevo|compro|pido|preparo|cocino|hago|me\s+compro|me\s+pido"
    r"|puedo\s+(?:comer|cenar|almorzar|comprar|pedir|llevar|regalar|preparar))"
    r"|se\s+me\s+antoja[n]?|me\s+(?:tinca|tincan|apetece)|cosas)\b"
    r"(?:\s+(?:para|de|con|en)\b)?(?:\s+(?:un|una|el|la|los|las|unos|unas)\b)?\s*"
)
# «qué trago me recomiendas», «cuál vino me sugieres»: se pide eso.
RECOMMEND_ASK = re.compile(
    r"^(?:(?:que|cual|cuales)\s+)?(.+?)\s+(?:me\s+)?(?:recomiendas|recomendarias|sugieres|recomiendan)$"
)
# Pedir consejo médico («¿qué le doy?», «qué me tomo», «dosis»): con un síntoma o un remedio nombrado, Mochi no lo da.
ADVICE = re.compile(
    r"\b(?:le|les|me|te)\s+(?:doy|damos|tomo|tomas|puedo\s+dar|puedo\s+tomar)\b|\b(?:puedo|puede|debo|debe)\s+tomar\b"
    r"|\bque\s+(?:tomo|tomar|remedio|remedios|medicamento|pastilla|jarabe)\b|\bdosis\b|\bcada\s+cuanto\b"
    r"|\b(?:sirve|sirven|es\s+bueno|es\s+buena)\s+para\b"
)
GENERIC_MEDICINE = {"remedio", "remedios", "medicamento", "medicamentos", "pastilla", "pastillas", "jarabe", "dosis"}
NAMED_MEDICINE = {"paracetamol", "ibuprofeno", "aspirina", "antibiotico", "antialergico", "antigripal"}
MEDICINE_WORDS = GENERIC_MEDICINE | NAMED_MEDICINE
NOT_ADVICE_OCCASIONS = {"enfermo", "guagua"}  # nombrar otra ocasión («le doy un regalo») no pide consejo médico
# «¿qué es un poke?», «¿qué lleva una paella?»: una ficha del glosario (agent/glosario.toml). Solo si se pregunta por
# el plato: a lo más una palabra más («qué es lo más barato en sushi» no es la ficha del sushi).
DISH_EXTRA_WORDS = 1
WHAT_IS = re.compile(
    r"^(?:que|q)\s+(?:es|son|significa|lleva|llevan|trae|tiene)\s+(?:un|una|el|la|los|las|unos|unas)?\s*(.+)$"
    r"|^de\s+que\s+es\s+(?:un|una|el|la)?\s*(.+)$"
)
# «¿con qué acompaño un salmón?»: el complemento de lo que se nombra, no más de eso.
GOES_WITH = re.compile(
    r"^(?:con\s+que\s+(?:acompano|acompanar|acompanamos|combino|combinar|sirvo|servir)"
    r"|que\s+(?:le\s+pongo|le\s+echo|acompana|combina|va\s+bien|queda\s+bien)\s+(?:a|al|con)"
    r"|que\s+va\s+con|que\s+(?:sirvo|pongo)\s+con)\s+(.+)$"
)


@dataclass
class Intent:
    # saludo | gracias | ayuda | envio | ofertas | fuera | pedido | receta | memoria | buscar | ocasion | aclarar
    # | servicio | vacio | consejo (consejo médico) | que_es (ficha de un plato) | acompanar (con qué acompañar algo)
    kind: str
    text: str
    vertical: str | None = None
    concepts: list[str] = field(default_factory=list)
    occasion: str | None = None
    price_max: float | None = None
    confidence: float = 0.0
    options: list[str] = field(default_factory=list)  # verticales candidatos cuando hay que aclarar
    explicit_vertical: bool = False
    explicit_concepts: bool = False  # los conceptos se nombraron (no vienen solo de la ocasión)
    query: str = ""  # consulta limpia para buscar y para repetirle al usuario
    symptom: bool = False  # habló de síntomas: remedios de farmacia sin receta, sin venta cruzada
    service: str | None = None  # servicio sin catálogo (RappiTravel, RappiFavor)
    cheapest: bool = False  # «barato»: lo más barato primero
    priciest: bool = False  # «más caro»: lo más caro primero
    follow_up: bool = False  # refina el mensaje anterior («talla g» tras «pañales»)
    exclude_previous: bool = False  # «de otra marca», «otras opciones»: sin lo que ya se mostró
    people: int | None = None  # para cuántas personas («asado de 6»)
    dish: str | None = None  # ficha del glosario («¿qué es un poke?»)


class Understander:
    def __init__(self):
        taxonomy = load_taxonomy()
        self.taxonomy = taxonomy
        self.concepts = concept_matcher(taxonomy, for_queries=True)
        self.occasions = KeywordMatcher((o.id, kw) for o in taxonomy.occasions.values() for kw in o.keywords)
        self.verticals = KeywordMatcher((v, kw) for v, kws in VERTICAL_MENTIONS.items() for kw in kws)
        self.symptoms = KeywordMatcher(("sintoma", kw) for kw in SYMPTOMS)
        self.services = KeywordMatcher((s.id, kw) for s in taxonomy.services.values() for kw in s.keywords)
        self.app_questions = KeywordMatcher((kind, kw) for kind, kws in APP_QUESTIONS.items() for kw in kws)
        self.memory_questions = KeywordMatcher(("memoria", kw) for kw in MEMORY_QUESTIONS)
        self.dishes = KeywordMatcher((d.id, kw) for d in load_glossary().values() for kw in d.keywords)
        # «🍕» o «quiero un 🍔»: el emoji de un concepto se lee como su nombre (gana el primero que lo usa).
        self.emojis: dict[str, str] = {}
        for concept in taxonomy.concepts.values():
            if concept.emoji:
                self.emojis.setdefault(concept.emoji.replace("\ufe0f", ""), concept.name)

    def understand(
        self, conn: Connection, text: str, current_vertical: str | None = None, previous: dict | None = None
    ) -> Intent:
        """`previous`: el pedido anterior de la conversación ({query, concepts, vertical}), para los seguimientos."""
        # «no, quiero pizza»: el «no» contesta algo anterior, no rechaza la pizza.
        original, text = text, re.sub(r"^\s*no\s*[,.;!]+", "", STRETCHED.sub(r"\1", self._emoji_names(text)))
        normalized = normalize(text)
        words = set(normalized.split())
        if not re.search(r"[a-z]", normalized) or LINK.search(original) or all(LAUGHTER.fullmatch(w) for w in words):
            return Intent("vacio", original)
        # El nombre solo, sin saludo ni «gracias», es un pedido: el mochi también es un postre.
        names = assistant_words()
        if words <= GREETING_WORDS | names and words & GREETING_WORDS:
            return Intent("saludo", text, current_vertical, confidence=1.0)
        if words <= THANKS_WORDS | GREETING_WORDS | names and words & THANKS_WORDS:
            return Intent("gracias", text, current_vertical, confidence=1.0)
        if self.memory_questions.best(normalized):
            return Intent("memoria", text, current_vertical, confidence=1.0)

        price_max, without_price = _price(text)
        # Habla chilena: «pa» y «pal» son «para» y «para el» («algo pa comer», «juguete pal gato»).
        said = re.sub(r"\bpal\b", "para el", re.sub(r"\bpa\b", "para", normalize(without_price)))
        asked = self._question(said, current_vertical)
        if asked:
            return asked
        # Ocasiones y síntomas, sobre el texto sin limpiar: «me siento mal» y «me duele» empiezan con «me».
        occasion = self.occasions.best(said)
        # La cantidad se queda en la consulta: los combos la dicen («Desayuno Para Dos», «Pichanga para 4 Personas»).
        people = _people(said, occasion is not None)
        body = " ".join(PEOPLE.sub(" ", _clean(_without_lead(_clean(said)))).split())
        # «sin azúcar» no pide azúcar ni «no quiero pizza» pizza: se descarta el concepto nombrado después.
        body_words = body.split()
        concept_matches, refused = [], []
        for m in self.concepts.matches(body):
            before = tuple(body_words[max(0, m.position - 2) : m.position])
            refusal = next((r for r in REFUSALS if before[-len(r) :] == r), None)
            if refusal == ("menos",) and before[:1] and before[0] in LESS:
                continue
            if refusal:
                refused.append(m)
                body_words[m.position - len(refusal) : m.position + m.words] = [""] * (len(refusal) + m.words)
            elif before[-1:] == ("sin",) or (before[:1] == ("sin",) and before[1] in ARTICLES):  # «sin la palta»
                continue
            else:
                concept_matches.append(m)
        if refused:  # lo rechazado tampoco se busca
            body = " ".join(w for w in body_words if w)
            body_words = body.split()
        concepts = [m.target for m in concept_matches]
        refused_ids = {m.target for m in refused}
        if refused and not concepts and not occasion and not body:  # «no quiero cerveza»: nada que buscar
            return Intent("vacio", original)
        if refused and not concepts and not occasion:  # «cualquier cosa menos sushi»: el resto de su ocasión
            occasion = next(
                (Match(o.id, "", 0, 0) for o in self.taxonomy.occasions.values() if refused_ids & set(o.concepts)),
                None,
            )
        mention = self._mention(body, concept_matches)
        # La ocasión «Me siento mal» cuenta como síntoma («malestar», «cuidarme»): sin Licores, sin «También en» ni
        # venta cruzada, y con el aviso de farmacia. Aunque otra ocasión vaya antes («un tecito para el malestar»).
        symptom = self.symptoms.best(said) is not None or any(
            m.target == "enfermo" for m in self.occasions.matches(said)
        )

        explicit = bool(concepts)
        # Sobre lo dicho si la limpieza se comió la pregunta: «oye mochi me recomiendas…» queda «recomiendas…».
        question = None if explicit or occasion else self.app_questions.best(body) or self.app_questions.best(said)
        if question:  # «hacen delivery?», «quien eres»: se contesta, no se busca
            return Intent(question.target, text, current_vertical, confidence=1.0)
        # Un servicio sin catálogo, si no se nombra un producto («paquete de pañales» no es un envío) ni un síntoma.
        service = None if explicit or symptom else self.services.best(said)
        if service:
            return Intent("servicio", text, None, [], confidence=0.8, query=body or normalized, service=service.target)
        follow_up = self._follow_up(text, said, body_words, concepts, occasion, symptom, mention, previous, price_max)
        if follow_up:
            return follow_up
        if occasion and not concepts:
            concepts = [c for c in self.taxonomy.occasions[occasion.target].concepts if c not in refused_ids]
        kind = "ocasion" if occasion else "buscar"
        confidence = 0.9 if concept_matches else (0.7 if occasion else 0.3)
        common = dict(
            occasion=_id(occasion),
            price_max=price_max,
            confidence=confidence,
            explicit_concepts=explicit,
            # la vertical nombrada no se busca («en el super algo…» traía comida para gatos Super)
            # (lo rechazado no vuelve por el texto completo: «menos sushi» no busca sushi)
            query=_without_mention(body, mention) or body or ("" if refused else normalized),
            symptom=symptom,
            **_price_order(said.split()),
        )

        common["people"] = people
        if mention:
            return Intent(kind, text, mention, concepts, explicit_vertical=True, **common)
        if current_vertical:
            return Intent(kind, text, current_vertical, concepts, **common)
        if not concepts:
            return Intent(kind, text, None, [], **common)

        if not explicit:  # ocasión: su vertical fijo o el de más surtido para el conjunto de sus conceptos
            fixed = self.taxonomy.occasions[occasion.target].vertical
            if fixed:
                return Intent(kind, text, fixed, concepts, **common)
            options = _ranked(conn, concepts, symptom)
            return Intent(kind, text, options[0] if options else self._home(concepts[0]), concepts, **common)
        options = _ranked(conn, concepts[:1], symptom)
        if words & PACKAGED_WORDS:  # «café en grano», «2 kilos de»: se compra en tienda, no se pide hecho
            options = [v for v in options if v != "restaurantes"]
        pair = [v for v in options[:2] if v in contending_verticals(conn, concepts[:1])]
        if len(pair) == 2 and "restaurantes" in pair and _comparable(conn, concepts[0], pair):
            return Intent("aclarar", text, None, concepts, options=pair, **common)
        return Intent(kind, text, options[0] if options else self._home(concepts[0]), concepts, **common)

    def _question(self, said: str, current_vertical: str | None) -> Intent | None:
        """Las preguntas que no son un pedido: consejo médico, la ficha de un plato o con qué acompañar algo."""
        if self._advice(said):
            return Intent("consejo", said, current_vertical, confidence=1.0, symptom=True, query=said)
        plain = _clean(said)  # sin saludo ni nombre: «hola mochi, ¿qué es un ramen?»
        what = WHAT_IS.match(plain)
        rest = (what.group(1) or what.group(2)) if what else ""
        dish = self.dishes.best(rest) if what else None
        if dish and len(rest.split()) - dish.words <= DISH_EXTRA_WORDS:
            return Intent("que_es", said, current_vertical, confidence=0.9, query=said, dish=dish.target)
        goes = GOES_WITH.match(plain)
        if goes:
            rest = _clean(goes.group(1))
            named = [m.target for m in self.concepts.matches(rest)]
            occasion = self.occasions.best(rest)
            # De una ocasión, lo primero que Mochi puede proponer («con qué acompaño el carrete» no nombra la cerveza).
            of_occasion = self.taxonomy.occasions[occasion.target].concepts if occasion else ()
            offerable = [c for c in of_occasion if self._offerable(c)]
            base = named[:1] or offerable[:1]
            if base:
                return Intent(
                    "acompanar", said, current_vertical, base, confidence=0.8, explicit_concepts=True, query=rest
                )
        return None

    def _advice(self, said: str) -> bool:
        """Si se pide consejo médico: «¿qué le doy?», «qué me tomo», «dosis», con un síntoma o un remedio nombrado; o un
        síntoma de un niño sin nombrar el remedio («mi guagua tiene fiebre»: elegirle un remedio es un consejo). No, si
        se nombra algo que Mochi puede proponer («qué sopa le doy a mi hijo resfriado») u otra ocasión («le doy un
        regalo»)."""
        words = set(said.split())
        symptom = self.symptoms.best(said) is not None
        if not (symptom or words & MEDICINE_WORDS):
            return False
        if any(self._offerable(m.target) for m in self.concepts.matches(said)):
            return False
        if any(m.target not in NOT_ADVICE_OCCASIONS for m in self.occasions.matches(said)):
            return False
        child = symptom and bool(words & CHILD_WORDS) and not words & NAMED_MEDICINE
        return child or ADVICE.search(said) is not None

    def _offerable(self, concept_id: str) -> bool:
        concept = self.taxonomy.concepts.get(concept_id)
        return concept is not None and is_offerable(concept)

    def _follow_up(self, text, said, body_words, concepts, occasion, symptom, mention, previous, price_max):
        """Un mensaje corto que no nombra nada nuevo (o que empieza con «con», «sin», «talla», «más»…) sigue el pedido
        anterior: «talla g» tras «pañales» busca «pañales talla g»; «y en el súper?» busca lo mismo allá."""
        if body_words[:2] == ["mejor", "no"]:  # «mejor no, algo más barato»: el «no» rechaza lo anterior
            body_words = body_words[2:]
        if not previous or occasion or symptom or len([w for w in body_words if w not in FOLLOW_UP_FILLER]) > 4:
            return None
        previous_concepts = [c for c in previous.get("concepts") or [] if c in self.taxonomy.concepts]
        if not previous_concepts or (concepts and body_words[:1] and body_words[0] not in REFINE_START):
            return None
        mention_words = {w for kw in VERTICAL_MENTIONS.get(mention, ()) for w in kw.split()}
        rest = [w for w in body_words if w not in FOLLOW_UP_FILLER and w not in mention_words]
        other = bool(set(body_words) & OTHER_WORDS)
        extra = "" if other or (mention and not rest) else " ".join(rest)  # «mejor no, algo más barato» → «mas barato»
        base = previous.get("query") or ""
        order = _price_order(said.split())
        # «y de vainilla?», «y blanco?»: otra opción, no se suma a «de chocolate». «y más barato?» o «y talla g?» sí.
        if body_words[:1] == ["y"] and rest[:1] and rest[0] not in SIZE_OR_PRICE and not any(order.values()):
            base = normalize(self.taxonomy.concepts[previous_concepts[0]].name)
        return Intent(
            "buscar",
            text,
            mention or previous.get("vertical"),
            previous_concepts,
            price_max=price_max,
            confidence=0.8,
            explicit_vertical=bool(mention),
            explicit_concepts=True,
            query=" ".join(p for p in (base, extra) if p),
            **order,
            follow_up=True,
            exclude_previous=other,
        )

    def _emoji_names(self, text: str) -> str:
        if text.isascii():
            return text
        text = text.replace("\ufe0f", "")
        for emoji, name in self.emojis.items():
            text = text.replace(emoji, f" {name} ")
        return text

    def _home(self, concept_id: str) -> str | None:
        concept = self.taxonomy.concepts.get(concept_id)
        return GROUP_VERTICALS.get(concept.parent) if concept else None

    def _mention(self, body: str, concept_matches) -> str | None:
        """Mención de vertical que no se solapa con un concepto nombrado (p. ej. "cigarros pall mall")."""
        for match in self.verticals.matches(body):
            span = set(range(match.position, match.position + match.words))
            overlapping = [m for m in concept_matches if span & set(range(m.position, m.position + m.words))]
            # Una mención más larga que el concepto que pisa gana: «burger king» es la cadena, no «burger».
            if all(match.words > m.words for m in overlapping):
                return match.target
        return None


def _people(said: str, with_occasion: bool) -> int | None:
    """Para cuántas personas. «de N» al final solo cuenta con una ocasión («asado de 6»; «huevos de 12» no) y no tras
    un niño («cumpleaños de mi hijo de 6» es la edad)."""
    for pattern in (PEOPLE_COUNT, PEOPLE_COUNT_OF) if with_occasion else (PEOPLE_COUNT,):
        match = pattern.search(said)
        if match and pattern is PEOPLE_COUNT_OF and said[: match.start()].split()[-1:] in ([w] for w in CHILD_WORDS):
            continue
        if match:
            number = next(g for g in match.groups() if g)
            people = int(number) if number.isdigit() else _NUMBERS[number]
            if 2 <= people <= MAX_PEOPLE:
                return people
    return None


def _without_lead(body: str) -> str:
    """Sin la frase de pregunta del inicio ni el «me recomiendas» del final: «qué trago me recomiendas» → «trago»."""
    rest = QUESTION_LEAD.sub("", body)
    if rest and set(rest.split()) <= TIME_FILLER or not rest:  # «qué pido hoy»: no queda un pedido
        rest = body
    asked = RECOMMEND_ASK.match(rest)
    return asked.group(1) if asked else rest


def _without_mention(body: str, mention: str | None) -> str:
    if mention is None:
        return body
    for keyword in sorted(GENERIC_MENTIONS & set(VERTICAL_MENTIONS[mention]), key=len, reverse=True):
        cleaned, found = re.subn(rf"\b{MENTION_LEADS}{re.escape(keyword)}\b", " ", body, count=1)
        if found:
            return " ".join(cleaned.split())
    return body


def _simplify(text: str) -> str:
    """Minúsculas y sin tildes, pero conservando $ y puntos (normalize los borra y el precio los necesita)."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def _price_order(words: list[str]) -> dict[str, bool]:
    """«barato» o «menos caro»/«no tan caro» piden lo más barato primero; «caro», «premium» o «más cara», lo más
    caro."""
    cheapest = priciest = False
    for i, word in enumerate(words):
        before = words[max(0, i - 3) : i]
        pricey = word in PRICEY_WORDS or (word in {"cara", "caras"} and before[-1:] == ["mas"])
        if word in CHEAP_WORDS or (pricey and {"menos", "no", "tan"} & set(before)):
            cheapest = True
        elif pricey:
            priciest = True
    return {"cheapest": cheapest, "priciest": priciest and not cheapest}


def _price(text: str) -> tuple[float | None, str]:
    """Tope de precio y el texto sin esa frase (con su "pesos" o "clp"). "hasta 5 kilos" o "2 litros" no son
    precios; "bajo 5" tampoco: se exige $, "mil"/"lucas"/"k" o al menos 3 dígitos. "1,5 lucas" son $1.500 y
    "$10,000" (coma de miles) $10.000; "$5,5", sin mil/lucas/k, no es precio."""
    # «entre 5 y 10 mil» es «hasta 10 mil»; «menos de mil» es «menos de 1000».
    # Si no queda un precio, el texto vuelve tal cual: «entre 2 y 3 kilos» no es «hasta 3 kilos».
    plain = _simplify(text)
    simple = re.sub(r"\bentre\s+\$?\s*[\d.,]+\s*(?:mil|lucas|k)?\s+y\s+(?=\$?\s*\d)", "hasta ", plain)
    simple = re.sub(r"\b(menos de|bajo|hasta|maximo|no mas de)\s+(?:mil|una luca)\b", r"\1 1000", simple)
    for match in PRICE.finditer(simple):
        currency, digits, thousands = match.groups()
        decimal = re.fullmatch(r"\d+[.,]\d{1,2}", digits)
        if decimal and not thousands:  # «1,5 mil ml»: la regex soltó «mil» porque le sigue una unidad
            continue
        value = float(digits.replace(",", ".")) if decimal else float(re.sub(r"[.,\s]", "", digits))
        if not (currency or thousands or value >= 100):
            continue
        return (value * 1000 if thousands else value), simple[: match.start()] + simple[match.end() :]
    return None, plain


def _clean(body: str) -> str:
    """Quita saludo, nombre del asistente y verbos de pedido al inicio, y la cortesía al final:
    "hola mochi quiero sushi porfa" → "sushi". El nombre se quita solo como vocativo: después de un saludo, un
    «gracias» o un «oye», o antes de un pedido («mochi, quiero sushi»). Si no, es lo que se pide («quiero mochi»,
    «mochi de matcha»)."""
    names = assistant_words()
    words = body.split()
    called = False  # la palabra anterior llama a alguien («hola», «gracias», «oye»)
    # «m» (de «mmm» ya colapsado) solo al inicio: al final es una talla («pañales talla m»)
    while words:
        first = words[0]
        if first in names:
            if not (called or (len(words) > 1 and words[1] in _CALLS | _REQUEST_VERBS)):
                break
        elif first not in _CALLS | REQUEST_WORDS | {"m"}:
            break
        called = first in _CALLS
        words = words[1:]
    while words:
        last = words[-1]
        if last in names:
            if not (len(words) > 1 and words[-2] in _COURTESY_AT_END):
                break
        elif last not in _COURTESY_AT_END:
            break
        words = words[:-1]
    return " ".join(words)


def _id(match) -> str | None:
    return match.target if match else None


def _ranked(conn: Connection, concept_ids: list[str], sick: bool) -> list[str]:
    return [v for v in ranked_verticals(conn, concept_ids) if not (sick and v in NOT_WHEN_SICK)]


def _comparable(conn: Connection, concept_id: str, verticals: list[str]) -> bool:
    """Participaciones parecidas (no conteos: restaurantes tiene ~5 veces más ítems y nunca habría empate)."""
    shares = dict(
        conn.execute(
            """WITH total AS (SELECT vertical, sum(items) AS items FROM concept_assortment GROUP BY vertical)
               SELECT a.vertical, a.items::float / t.items FROM concept_assortment a JOIN total t USING (vertical)
               WHERE a.concept_id = %s AND a.vertical = ANY(%s)""",
            (concept_id, verticals),
        ).fetchall()
    )
    values = [shares.get(v, 0) for v in verticals]
    return min(values) >= AMBIGUITY_RATIO * max(values)
