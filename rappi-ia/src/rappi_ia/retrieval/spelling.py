"""Corrección de errores de tipeo con el vocabulario del catálogo (`search_vocabulary`, migración 041).

Se usa cuando nada de la vertical calza todas las palabras de la consulta (agent/tools.search_products, y
agent/grouped_search si ninguna vertical calza): se corrige la consulta y se vuelve a buscar con las reglas de siempre,
y lo corregido se muestra solo si algún documento calza todas sus palabras. Una negativa no deja de serlo por una
palabra cambiada que lleva a otra cosa ("pasaje … punta arenas" → "masaje … punta avenas" no calza). Lo que calza
cambia solo por un nombre (`matched`, abajo). Palabra por palabra:

- se saltan las muletillas, "hola" y las palabras de pedido del inicio ("eh", "quiero", "una") y la cortesía del final
  ("porfa", "gracias"), como las limpia el agente, si queda una consulta corta (hasta SHORT_QUERY palabras): "eh
  quiero este una coca porfa" → "coca". En medio de la frase quedan ("te quiero mochi": sin ellas sería otra consulta),
  una frase larga es una conversación, no una búsqueda ("necesito que me compren algo en una ferretería"), y los
  saludos de dos palabras también son palabras ("tardes de lluvia", "buenos aires"). Lo que queda solo con palabras de
  saludo o cortesía ("ok gracias") no se busca;
- una palabra que nombra un concepto queda como está: "cerveza" en una chocolatería es lo que no hay, no "cereza";
  tampoco cambia el orden por precio (`PRICE_WORDS`: "sushi barato" no es "sushi barto");
- una consulta que le habla al asistente ("oye mochi, ¿me recomiendas algo?", "hola mochi": su nombre junto a un
  saludo, una muletilla o un pedido) no se corrige: es una conversación, no una búsqueda mal escrita;
- una consulta que nombra una ocasión no se corrige: pide cosas que su nombre no dice ("regalo para mi polola" no
  calza todas sus palabras a propósito, y "polola" no es un error de "polla");
- una letra repetida tres o más veces se deja en una o en dos, y una letra doble en una, si la vertical tiene esa forma
  DOCS_RATIO veces más ("cervezaaaa" → "cerveza", "oreoo" → "oreo");
- una palabra de MIN_LENGTH letras o más que la vertical casi no tiene se cambia por la más parecida que sí tiene
  DOCS_RATIO veces más (`choose`): "nutela" → "nutella", "cuchuflis" → "cuchuflies". No por una de la misma raíz
  ("cuerpos" → "cuerpo"), que la búsqueda léxica ya junta, ni por una stopword ("estadio" → "estado"), que la
  búsqueda bota y dejaría calzar todo lo demás;
- una palabra de SHORT_LENGTH letras (una menos que MIN_LENGTH) se cambia solo si la que la reemplaza es la única a
  una edición con mucho más uso (en KNOWN_DOCS documentos o más y SHORT_RATIO veces los de la escrita) y esa edición
  es una letra que suena igual o casi (`SOUND_ALIKE`): "suchi" → "sushi", "arros" → "arroz", "bodka" → "vodka". Una
  vocal cambiada ya es otra palabra ("tonto" no es "tinto"), y bajo SHORT_LENGTH letras solo se deja una letra doble
  en una ("sofa" no es "soft");
- una palabra que el catálogo entero tiene en KNOWN_DOCS documentos o más es una palabra real, no un error, aunque la
  vertical no la tenga: "crema para las manos" en Licores no pasa a "crema para las anos", ni "comida china" a
  "comida chica". Tampoco un número ("3000" no es "30").

La palabra corregida se muestra como la escribe el catálogo (`search_vocabulary.display`: "pañales", no "panales").

Cuando algo ya calza (`matched`), solo se corrige una palabra que el catálogo trae nada más que en el nombre de un
local, una tienda o una marca (`name_words`), si su corrección de siempre es una letra que suena igual
(`SOUND_ALIKE`) y, en cada vertical donde está, la candidata está en NAME_RATIO veces más documentos: "suchi" calza los
16 platos de "Suchi Tacna", un local de otra ciudad, y quien lo escribe busca "sushi" (45 mil documentos, 2.813 veces
más). Un nombre que cambia, agrega o quita letras es un nombre buscado a propósito ("Burgery", "Cevicheo",
"Wiphone"), y uno que suena igual a una palabra con menos uso en su vertical también ("Cakao", la chocolatería, frente
a "cacao": 566 veces; "Todo Likores", 165): esos no cambian. La respuesta dice qué se buscó y la app ofrece buscar lo
escrito tal cual (`correct=false`).

Sin diccionario, una palabra que el catálogo casi no tiene puede ser real ("tengo resaca" → "tengo reseca"): la
respuesta dice qué se buscó y la app ofrece buscar lo escrito tal cual (docs/resultados/busqueda-2026-10-24.md).

#129 midió por qué hace falta: los cosenos de e5 no separan un error de tipeo ("cuchuflis" en Turbo, 0,843) de una
negativa ("sofá de tres cuerpos" en el súper, 0,839), y el τ de 0,85 dejó a los dos "sin resultado".
"""

import re
from dataclasses import dataclass

from psycopg import Connection

from ..catalog.cache import cached_many
from ..text import CHEAP_WORDS, FILLER_WORDS, MUTTER_WORDS, PRICEY_WORDS, REQUEST_WORDS, assistant_words, normalize
from .hybrid import detect_concepts, named_occasion

MIN_LENGTH = 6  # bajo esto, una edición ya suele ser otra palabra ("sofa" → "soft", "tonto" → "tinto")
SHORT_LENGTH = 5  # con estas letras, solo una letra que suena igual, a una única candidata ("suchi" → "sushi")
SHORT_RATIO = 100  # la candidata de una palabra de SHORT_LENGTH letras está en 100 veces más documentos que ella
# Letras que se confunden al escribir de oído: c, s y z ("arros"); ch y sh ("suchi"); b y v; g y j; c, k y q; i e y.
SOUND_ALIKE = (frozenset("csz"), frozenset("bv"), frozenset("gj"), frozenset("ckq"), frozenset("iy"))
LONG_WORD = 9  # desde aquí se aceptan dos ediciones ("cancelar" → "canela" no)
KNOWN_DOCS = 20  # en tantos documentos del catálogo (todas las verticales), la palabra es real: no se corrige
# Con algo que ya calza, la candidata está en tantas veces más documentos que el nombre en cada vertical donde él está
# ("suchi" → "sushi" en Restaurantes: 2.813). Supuesto propio, medido con los nombres del catálogo del 14-11-2026: el
# siguiente que suena igual es "cakao" → "cacao" (566 en el súper), una chocolatería que se busca por su nombre.
NAME_RATIO = 1000
# Lo que en un documento de búsqueda es un nombre (rappi_scraper/storage/search.py): la marca de un producto o de una
# tienda, el local de un plato y la ciudad. En el documento de una tienda, también su primer pedazo (el nombre).
NAME_LABELS = ("Marca: ", "Restaurante: ", "Ciudad: ")
DOCS_RATIO = 10  # la palabra corregida está en al menos 10 veces más documentos de la vertical que la escrita
CANDIDATES = 50  # candidatas por trigramas (`%` de pg_trgm, similitud ≥ 0,3) que se miden con `edit_distance`
SKIP_WORDS = frozenset(REQUEST_WORDS | MUTTER_WORDS | {"hola", "holi", "hey", "wena", "alo", "ola"})
TRAILING_WORDS = frozenset({"porfa", "por", "favor", "plis", "gracias"})
SHORT_QUERY = 4
# El orden por precio no es un error de tipeo, aunque el catálogo casi no lo tenga: "barato" pasaba a "barto".
PRICE_WORDS = frozenset(CHEAP_WORDS | PRICEY_WORDS)
_REPEAT = re.compile(r"(.)\1{2,}")
_WORD = re.compile(r"[^\W_]+")
_LETTERS = "abcdefghijklmnopqrstuvwxyz"  # las del vocabulario: sin tildes ni ñ


@dataclass(frozen=True)
class QueryWord:
    surface: str  # como la escribió la persona, en minúsculas
    word: str  # sin tildes ni ñ: como el vocabulario
    skip: bool  # muletilla o palabra de pedido


def query_words(query: str) -> list[QueryWord]:
    """Las palabras de la consulta; `skip` en las muletillas y palabras de pedido del inicio y la cortesía del final."""
    pairs = [(s, w) for s in _WORD.findall(query.lower()) if (w := normalize(s).replace(" ", ""))]
    forms = [{w, _REPEAT.sub(r"\1", w)} for _, w in pairs]  # "holaaaa" también es un saludo, y "mmm" una muletilla
    start = 0
    while start < len(pairs) and forms[start] & SKIP_WORDS:
        start += 1
    end = len(pairs)
    while end > start and forms[end - 1] & TRAILING_WORDS:
        end -= 1
    if end - start > SHORT_QUERY:
        start, end = 0, len(pairs)
    return [QueryWord(s, w, not start <= i < end) for i, (s, w) in enumerate(pairs)]


def transpositions(word: str) -> list[str]:
    """`word` con cada par de letras vecinas distintas dado vuelta: los trigramas casi no ven una trasposición en una
    palabra corta ("olvia" y "oliva" comparten 2 de 10), así que estas se buscan tal cual."""
    return [word[:i] + word[i + 1] + word[i] + word[i + 2 :] for i in range(len(word) - 1) if word[i] != word[i + 1]]


def edit_distance(a: str, b: str) -> int:
    """Distancia de edición con trasposición de dos letras vecinas ("jhonnie" → "johnnie" es una)."""
    previous2, previous = None, list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        current = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            current[j] = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            if previous2 is not None and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                current[j] = min(current[j], previous2[j - 2] + 1)
        previous2, previous = previous, current
    return previous[len(b)]


def single_forms(word: str) -> list[str]:
    """`word` con cada letra doble dejada en una ("oreoo" → "oreo", "pinno" → "pino"): el error más común de una
    palabra corta, que la regla de `choose` no toca bajo MIN_LENGTH letras."""
    return [word[:i] + word[i + 1 :] for i in range(len(word) - 1) if word[i] == word[i + 1]]


def repeat_forms(word: str) -> list[str]:
    """Las formas de `word` con cada letra repetida tres o más veces dejada en una y en dos."""
    if not _REPEAT.search(word):
        return []
    return [_REPEAT.sub(r"\1", word), _REPEAT.sub(r"\1\1", word)]


def sound_alike(word: str, candidate: str) -> bool:
    """`candidate` es `word` con una sola letra cambiada por otra que suena igual o casi (`SOUND_ALIKE`)."""
    if len(word) != len(candidate):
        return False
    changed = [(a, b) for a, b in zip(word, candidate, strict=True) if a != b]
    return len(changed) == 1 and any(set(changed[0]) <= group for group in SOUND_ALIKE)


def one_edit_forms(word: str) -> list[str]:
    """Todas las palabras a una edición de `word` (sin una letra, con una cambiada o de más, o dos dadas vuelta): en
    una palabra corta los trigramas casi no ven una letra cambiada ("suchi" y "sushi" comparten 2 de 7) y se buscan
    todas tal cual, para saber si la candidata es la única."""
    splits = [(word[:i], word[i:]) for i in range(len(word) + 1)]
    forms = {a + b[1:] for a, b in splits if b}
    forms |= {a + c + b[1:] for a, b in splits if b for c in _LETTERS}
    forms |= {a + c + b for a, b in splits for c in _LETTERS}
    forms |= set(transpositions(word))
    forms.discard(word)
    return sorted(forms)


def choose(
    word: str, own_docs: int, candidates: list[tuple[str, int]], excluded: frozenset[str] = frozenset()
) -> str | None:
    """La palabra por la que se cambia `word` (en `own_docs` documentos de la vertical), entre `candidates` (palabra,
    documentos): a una edición (dos desde LONG_WORD letras), en al menos DOCS_RATIO veces más documentos, sin la misma
    raíz que `word` y sin ser stopword (`excluded`). Gana la más cercana y, entre ellas, la de más documentos
    ("bluetooth", no la errata "bluetooh" que también trae el catálogo). None si ninguna sirve."""
    ranked = _ranked(word, own_docs, candidates)
    return next((candidate for candidate in ranked if candidate not in excluded), None)


def _ranked(word: str, own_docs: int, candidates: list[tuple[str, int]]) -> list[str]:
    if len(word) < SHORT_LENGTH or word.isdigit():
        return []
    if len(word) < MIN_LENGTH:
        return _ranked_short(word, own_docs, candidates)
    limit = 2 if len(word) >= LONG_WORD else 1
    floor = max(1, DOCS_RATIO * own_docs)
    scored = []
    for candidate, docs in candidates:
        if candidate == word or docs < floor:
            continue
        distance = edit_distance(word, candidate)
        if distance <= limit:  # a igual documentos, la más larga: lo más común es que falte una letra
            scored.append((distance, -docs, -len(candidate), candidate))
    return [candidate for *_, candidate in sorted(scored)]


def _ranked_short(word: str, own_docs: int, candidates: list[tuple[str, int]]) -> list[str]:
    """Una palabra de SHORT_LENGTH letras: la única candidata a una edición con mucho más uso, si suena igual."""
    floor = max(KNOWN_DOCS, SHORT_RATIO * own_docs)
    near = {candidate for candidate, docs in candidates if docs >= floor and edit_distance(word, candidate) == 1}
    return [*near] if len(near) == 1 and sound_alike(word, *near) else []


def correct_query(conn: Connection, query: str, vertical: str | None, matched: bool = False) -> str | None:
    """La consulta corregida con el vocabulario de `vertical` (con None, el de todas), o None si no hay nada que
    corregir. Las palabras que estaban bien quedan como se escribieron; las muletillas salen. Con `matched` (algo ya
    calza todas las palabras), solo se corrige un nombre que suena igual a una palabra con muchísimo más uso
    (`_name_fix`), y no si la consulta trae otra palabra de ese mismo nombre ("suchi tacna" busca el local); sin eso no
    hay nada que corregir aunque sobre una muletilla."""
    if named_occasion(query) is not None:
        return None
    words = query_words(query)
    said = {w.word for w in words}
    if said & assistant_words() and said & (FILLER_WORDS | MUTTER_WORDS):
        return None
    kept = [w for w in words if not w.skip]
    if all(w.word in FILLER_WORDS for w in kept):
        return None
    candidates = [w.word for w in kept if not detect_concepts(w.word) and w.word not in PRICE_WORDS]
    fixes = _fixes(conn, vertical, candidates, matched)
    if matched:  # el resto del nombre también escrito: se busca el local, la tienda o la marca
        others = {w.word for w in kept}
        fixes = {w: fix for w, fix in fixes.items() if not (others - {w}) & (name_words(conn, w) or set())}
    corrected = [fixes.get(w.word) or w.surface for w in kept]
    if (matched or len(kept) == len(words)) and not any(w.word in fixes for w in kept):
        return None
    return " ".join(corrected)


def _fixes(conn: Connection, vertical: str | None, words: list[str], matched: bool = False) -> dict[str, str]:
    """La corrección de cada palabra que tiene una (de la caché del catálogo: cambia solo con él)."""
    fixer = _name_fix if matched else _fix

    def compute(missing: list[str]) -> dict[str, str | None]:
        return {word: fixer(conn, vertical, word) for word in missing}

    prefix = f"spelling{'-name' if matched else ''}:{vertical or '*'}"
    found = cached_many(prefix, conn, list(dict.fromkeys(words)), compute)
    return {word: fix for word, fix in found.items() if fix}


def _fix(conn: Connection, vertical: str | None, word: str) -> str | None:
    """Cómo se muestra la palabra por la que se cambia `word`, o None."""
    chosen = _choice(conn, vertical, word)
    return _display(conn, vertical, chosen) if chosen else None


def _name_fix(conn: Connection, vertical: str | None, word: str) -> str | None:
    """Como `_fix`, para una palabra que ya calza: solo si el catálogo la trae nada más que en nombres
    (`name_words`), su corrección es una letra que suena igual y, en cada vertical donde está (o en `vertical`), la
    candidata está en NAME_RATIO veces más documentos."""
    own = _docs_by_vertical(conn, vertical, word)
    chosen = _choice(conn, vertical, word) if own else None  # ya mira que sea rara en el catálogo y sin números
    if chosen is None or not sound_alike(word, chosen):
        return None
    theirs = _docs_by_vertical(conn, vertical, chosen)
    if any(theirs.get(v, 0) < NAME_RATIO * docs for v, docs in own.items()):
        return None
    return _display(conn, vertical, chosen) if name_words(conn, word) is not None else None


def name_words(conn: Connection, word: str) -> frozenset[str] | None:
    """Si los documentos del catálogo que traen `word` (sin tildes, palabra entera) la traen solo en un nombre
    (NAME_LABELS, o el primer pedazo del documento de una tienda), las palabras de esos nombres; si no, o si ninguno la
    trae, None. Un pedazo se corta en ". ", como los arma rappi_scraper/storage/search.py: si un nombre trae ". ", lo
    de después cuenta como texto, y la palabra no se corrige."""
    rows = conn.execute(
        """SELECT entity_type, content FROM search_documents
           WHERE tsv_unaccent @@ to_tsquery('spanish', %(word)s)
             AND es_unaccent(lower(content)) ~ ('\\m' || %(word)s || '\\M')""",
        {"word": word},
    ).fetchall()
    named: set[str] = set()
    for entity_type, content in rows:
        for i, piece in enumerate(content.split(". ")):
            said = {normalize(w).replace(" ", "") for w in _WORD.findall(piece.lower())}
            if word not in said:
                continue
            if not (piece.startswith(NAME_LABELS) or (entity_type == "store" and i == 0)):
                return None
            named |= said
    return frozenset(named) if named else None


def _choice(conn: Connection, vertical: str | None, word: str) -> str | None:
    """La palabra del vocabulario por la que se cambia `word`, o None."""
    if any(ch.isdigit() for ch in word):  # "3000" no es "30", ni "500g" "50g"
        return None
    known = _docs(conn, None, [word]).get(word, 0)  # en todo el catálogo
    if known >= KNOWN_DOCS:
        return None
    own = known if vertical is None else _docs(conn, vertical, [word]).get(word, 0)
    floor = max(1, DOCS_RATIO * own)
    repeated = [(docs, form) for form, docs in _docs(conn, vertical, repeat_forms(word)).items() if docs >= floor]
    if repeated:
        return max(repeated)[1]
    singles = _docs(conn, vertical, single_forms(word))
    if len(word) < MIN_LENGTH:  # una palabra corta pierde una letra doble o, con SHORT_LENGTH letras, cambia una
        fit = [(docs, form) for form, docs in singles.items() if docs >= floor]
        if fit or len(word) < SHORT_LENGTH:
            return max(fit)[1] if fit else None
        rows = list(_docs(conn, vertical, one_edit_forms(word)).items())  # todas: la candidata tiene que ser la única
    else:
        rows = conn.execute(
            """SELECT word, sum(docs)::int FROM search_vocabulary
               WHERE word %% %(word)s AND (%(vertical)s::text IS NULL OR vertical = %(vertical)s)
               GROUP BY word
               ORDER BY similarity(word, %(word)s) DESC, word
               LIMIT %(n)s""",
            {"word": word, "vertical": vertical, "n": CANDIDATES},
        ).fetchall()
        rows += [*_docs(conn, vertical, transpositions(word)).items(), *singles.items()]
    ranked = _ranked(word, own, rows)
    if not ranked:
        return None
    return choose(word, own, rows, _excluded(conn, word, ranked))


def _excluded(conn: Connection, word: str, candidates: list[str]) -> frozenset[str]:
    """Las candidatas que no sirven: las que la búsqueda léxica ya junta con `word` (el mismo tsvector en español:
    "cuerpos" y "cuerpo" → 'cuerp'; "cuchuflis" y "cuchuflies" no) y las stopwords, que la coincidencia estricta bota
    ("estado": "entradas para el estado 2 personas" calzaría solo "entradas", "2" y "personas")."""
    rows = conn.execute(
        "SELECT c, strip(to_tsvector('spanish', c))::text FROM unnest(%s::text[]) AS c", ([word, *candidates],)
    ).fetchall()
    roots = dict(rows)
    return frozenset(c for c in candidates if roots[c] == roots[word] or not roots[c])


def _display(conn: Connection, vertical: str | None, word: str) -> str:
    """Cómo escribe el catálogo `word` (con tildes y ñ), en la vertical o en todas."""
    row = conn.execute(
        """SELECT display FROM search_vocabulary WHERE word = %s AND (%s::text IS NULL OR vertical = %s)
           ORDER BY docs DESC, display LIMIT 1""",
        (word, vertical, vertical),
    ).fetchone()
    return row[0] if row else word


def _docs_by_vertical(conn: Connection, vertical: str | None, word: str) -> dict[str, int]:
    """En cuántos documentos de cada vertical (o solo de `vertical`) está `word`."""
    return dict(
        conn.execute(
            "SELECT vertical, docs FROM search_vocabulary WHERE word = %s AND (%s::text IS NULL OR vertical = %s)",
            (word, vertical, vertical),
        ).fetchall()
    )


def _docs(conn: Connection, vertical: str | None, words: list[str]) -> dict[str, int]:
    return dict(
        conn.execute(
            """SELECT word, sum(docs)::int FROM search_vocabulary
               WHERE word = ANY(%s) AND (%s::text IS NULL OR vertical = %s)
               GROUP BY word""",
            (words, vertical, vertical),
        ).fetchall()
    )
