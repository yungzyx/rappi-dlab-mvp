"""Carga la taxonomía propia (`taxonomy.toml`) y los complementos curados (`complements.toml`)."""

import tomllib
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from rappi_scraper.storage.search import VERTICALS

DATA_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Concept:
    id: str
    name: str
    emoji: str
    parent: str | None
    keywords: tuple[str, ...] = ()
    query_keywords: tuple[str, ...] = ()  # solo para entender consultas, nunca para asignar productos
    product_keywords: tuple[str, ...] = ()  # solo para asignar productos, nunca para entender consultas
    avoid: tuple[str, ...] = ()  # palabras que, en el nombre, impiden asignar este concepto por palabra clave
    sensitive: bool = False
    age_restricted: bool = False
    prepared: bool = False  # se pide hecho: también puede buscarse en restaurantes
    broad: bool = False  # agrupa productos de varios tipos («picoteo»): su nombre no lo dice

    @property
    def label(self) -> str:
        return f"{self.emoji} {self.name}"


@dataclass(frozen=True)
class Occasion:
    id: str
    name: str
    emoji: str
    keywords: tuple[str, ...]
    concepts: tuple[str, ...]
    vertical: str | None = None  # vertical fijo ("hambre ya" = pedir a un restaurante); si no, el del surtido
    portion: tuple[int, str] | None = None  # gramos por persona y de qué («asado de 6»: 350 g de carne cada uno)
    plan: bool = True  # si es un plan de la Home (un kit); las que solo sirven para entender preguntas, no


@dataclass(frozen=True)
class Hook:
    concept: str
    query: str
    question: str
    when: tuple[str, ...] = ()  # contextos de la consulta en que aplica («playa»); vacío = siempre


@dataclass(frozen=True)
class Service:
    """Servicio sin catálogo (RappiTravel, RappiFavor): se reconoce por keywords y lleva a su pantalla."""

    id: str
    name: str
    emoji: str
    pitch: str
    route: str
    keywords: tuple[str, ...]
    hooks: tuple[Hook, ...] = ()
    reason: str | None = None  # «Porque…» de la sugerencia de un gancho

    @property
    def label(self) -> str:
        return f"{self.emoji} {self.name}"


@dataclass(frozen=True)
class Taxonomy:
    version: str
    groups: dict[str, Concept]
    concepts: dict[str, Concept]  # solo hojas
    occasions: dict[str, Occasion]
    services: dict[str, Service] = field(default_factory=dict)

    def get(self, concept_id: str) -> Concept:
        return self.concepts.get(concept_id) or self.groups[concept_id]

    def all_nodes(self) -> list[Concept]:
        """Grupos primero (son padres de las hojas)."""
        return [*self.groups.values(), *self.concepts.values()]


@cache
def load_taxonomy(path: Path = DATA_DIR / "taxonomy.toml") -> Taxonomy:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    groups = {
        g["id"]: Concept(g["id"], g["name"], g["emoji"], None, prepared=g.get("prepared", False)) for g in raw["group"]
    }
    concepts = {
        c["id"]: Concept(
            id=c["id"],
            name=c["name"],
            emoji=c["emoji"],
            parent=c["parent"],
            keywords=tuple(c.get("keywords", ())),
            query_keywords=tuple(c.get("query_keywords", ())),
            product_keywords=tuple(c.get("product_keywords", ())),
            avoid=tuple(c.get("avoid", ())),
            sensitive=c.get("sensitive", False),
            age_restricted=c.get("age_restricted", False),
            prepared=c.get("prepared", groups[c["parent"]].prepared if c["parent"] in groups else False),
            broad=c.get("broad", False),
        )
        for c in raw["concept"]
    }
    occasions = {
        o["id"]: Occasion(
            o["id"],
            o["name"],
            o["emoji"],
            tuple(o["keywords"]),
            tuple(o["concepts"]),
            o.get("vertical"),
            (o["portion"]["grams"], o["portion"]["of"]) if "portion" in o else None,
            o.get("plan", True),
        )
        for o in raw.get("occasion", ())
    }
    services = {
        s["id"]: Service(
            s["id"],
            s["name"],
            s["emoji"],
            s["pitch"],
            s["route"],
            tuple(s["keywords"]),
            tuple(Hook(h["concept"], h["query"], h["question"], tuple(h.get("when", ()))) for h in s.get("hooks", ())),
            s.get("reason"),
        )
        for s in raw.get("service", ())
    }
    _validate(groups, concepts, occasions, services)
    return Taxonomy(raw["version"], groups, concepts, occasions, services)


@cache
def sensitive_concepts() -> frozenset[str]:
    """Conceptos sensibles (salud, sexualidad, tabaco…): un producto que está en uno solo pasa a otro sensible."""
    return frozenset(c.id for c in load_taxonomy().concepts.values() if c.sensitive)


def keeps_sensitive(current: str | None, candidate: str) -> bool:
    """True si reemplazar `current` por `candidate` sacaría un producto de un concepto sensible."""
    sensitive = sensitive_concepts()
    return current in sensitive and candidate not in sensitive


@cache
def guarded_concepts() -> frozenset[str]:
    """Lo sensible, lo +18 (el alcohol) y lo de bebé: lo que el agente nunca ofrece y una pista débil (los vecinos del
    kNN) no saca de su concepto. Salud no está: sus categorías mezclan de todo (cinturones en «Productos naturales»,
    anzuelos en «Equipos médicos») y ahí los vecinos corrigen bien."""
    return frozenset(
        c.id for c in load_taxonomy().concepts.values() if c.sensitive or c.age_restricted or c.parent == "bebe"
    )


def keeps_guarded(current: str | None, candidate: str) -> bool:
    """True si reemplazar `current` por `candidate` sacaría un producto de lo sensible, lo +18 o lo de bebé."""
    guarded = guarded_concepts()
    return current in guarded and candidate not in guarded


@cache
def load_complements(path: Path = DATA_DIR / "complements.toml") -> tuple[tuple[str, str, float], ...]:
    edges = tomllib.loads(path.read_text(encoding="utf-8"))["edges"]
    taxonomy = load_taxonomy()
    for source, target, weight in edges:
        if source not in taxonomy.concepts or target not in taxonomy.concepts:
            raise ValueError(f"Complemento con concepto desconocido: {source} → {target}")
        if not 0 <= weight <= 1:
            raise ValueError(f"Peso fuera de [0, 1]: {source} → {target} = {weight}")
    return tuple((s, t, float(w)) for s, t, w in edges)


def _validate(groups: dict, concepts: dict, occasions: dict, services: dict | None = None) -> None:
    clashes = groups.keys() & concepts.keys()
    if clashes:
        raise ValueError(f"Ids repetidos entre grupos y conceptos: {sorted(clashes)}")
    orphans = [c.id for c in concepts.values() if c.parent not in groups]
    if orphans:
        raise ValueError(f"Conceptos con grupo inexistente: {orphans}")
    for occasion in occasions.values():
        unknown = [c for c in occasion.concepts if c not in concepts]
        if unknown:
            raise ValueError(f"Ocasión {occasion.id} con conceptos inexistentes: {unknown}")
        if occasion.vertical and occasion.vertical not in VERTICALS:
            raise ValueError(f"Ocasión {occasion.id} con vertical inexistente: {occasion.vertical}")
    for service in (services or {}).values():
        unknown = [h.concept for h in service.hooks if h.concept not in concepts]
        if unknown:
            raise ValueError(f"Servicio {service.id} con ganchos inexistentes: {unknown}")
        if service.hooks and not service.reason:
            raise ValueError(f"Servicio {service.id} con ganchos y sin `reason`")
