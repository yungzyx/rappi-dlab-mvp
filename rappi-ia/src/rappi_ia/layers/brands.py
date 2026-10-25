"""Marcas canónicas: Rappi declara `trademark` en el 32 % de los productos y con muchas escrituras. Esta capa las junta,
enrolla las líneas bajo su marca («Coca-Cola Zero» → coca-cola) y deduce la marca del inicio del nombre cuando falta."""

import logging
import re
import tomllib
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from psycopg import Connection

from ..text import normalize
from .runs import finish_layer_run, rules_version, start_layer_run

log = logging.getLogger(__name__)

RULES_FILE = Path(__file__).resolve().parents[1] / "concepts" / "brands.toml"
MIN_PARENT_ITEMS = 10  # una marca con al menos tantos productos puede ser el padre de sus líneas
MIN_PARENT_LENGTH = 4
MIN_INDEX_ITEMS = 5  # marcas declaradas en al menos tantos productos se buscan en los nombres sin marca
MIN_INDEX_SUPPORT = 0.5  # …y solo si la mitad de sus propios ítems la llevan en el nombre
JUNK_ITEMS = 20  # una marca con tantos ítems y casi ninguno la nombra («AO», «Suave») es un valor de relleno
JUNK_SUPPORT = 0.10
MIN_GROUP_ITEMS = 2  # ítems declarados que hacen de un grupo de conceptos uno propio de la marca
_CORPORATE_SUFFIX = re.compile(r"( s a| sa| ltda| spa| limitada| inc| llc| sac)$")
_CHAIN_SUFFIX = re.compile(r"\s*-?\s*turbo\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class BrandRules:
    not_brands: frozenset[str]
    store_brands: frozenset[str]
    name_stop: frozenset[str]
    aliases: dict[str, str]
    families: frozenset[str] = frozenset()
    retailer_trademarks: frozenset[str] = frozenset()
    extra_index: frozenset[str] = frozenset()
    no_parent: frozenset[str] = frozenset()


@dataclass(frozen=True)
class NormBrand:
    spaced: str  # «coca cola»
    compact: str  # «cocacola»: la clave para juntar escrituras


def load_brand_rules(path: Path | None = None) -> tuple[str, BrandRules]:
    raw = tomllib.loads((path or RULES_FILE).read_text(encoding="utf-8"))

    def words(key: str) -> frozenset[str]:
        return frozenset(normalize(x) for x in raw.get(key, ()))

    rules = BrandRules(
        not_brands=words("not_brands"),
        store_brands=words("store_brands"),
        name_stop=words("name_stop"),
        aliases={normalize(a["alias"]): normalize(a["brand"]) for a in raw.get("alias", ())},
        families=words("families"),
        retailer_trademarks=words("retailer_trademarks"),
        extra_index=words("extra_index"),
        no_parent=words("no_parent"),
    )
    return raw["version"], rules


def norm_brand(raw: str | None, rules: BrandRules) -> NormBrand | None:
    spaced = _CORPORATE_SUFFIX.sub("", normalize(raw or ""))
    spaced = rules.aliases.get(spaced, spaced)
    compact = spaced.replace(" ", "")
    if len(compact) < 2 or spaced in rules.not_brands:
        return None
    return NormBrand(spaced, compact)


def chain_name(name: str) -> str:
    """El nombre de una cadena sin el sufijo «Turbo» ni el ®: «Burger King Turbo» y «Burger King®» son la misma."""
    return _CHAIN_SUFFIX.sub("", name).replace("®", "").strip()


def _contains(words: list[str], brand: list[str]) -> bool:
    return any(words[i : i + len(brand)] == brand for i in range(len(words) - len(brand) + 1))


def name_support(spaced: str, names: list[str]) -> float:
    """Qué parte de esos nombres lleva la marca (palabras enteras): una marca que casi ningún ítem suyo nombra no sirve
    para buscarla en otros nombres."""
    if not names:
        return 0.0
    brand = spaced.split()
    return sum(1 for n in names if _contains(normalize(n).split(), brand)) / len(names)


def trademark_fits(trademark: str, name: str, rules: BrandRules) -> bool:
    """Un nombre de cadena como `trademark` (Unimarc, Jumbo) solo es la marca del producto si el nombre la lleva."""
    nb = norm_brand(trademark, rules)
    if nb is None or nb.spaced not in rules.retailer_trademarks:
        return True
    return _contains(normalize(name).split(), nb.spaced.split())


def inference_ok(declared_groups: dict[str, int], item_group: str | None) -> bool:
    """Una marca deducida del nombre solo vale si el producto es de un grupo de conceptos donde la marca ya tiene
    productos declarados («Corona Graduado» no es de la cerveza Corona)."""
    if item_group is None:
        return True
    return declared_groups.get(item_group, 0) >= MIN_GROUP_ITEMS


def roll_up(
    counts: dict[str, int], families: frozenset[str] = frozenset(), blocked: frozenset[str] = frozenset()
) -> dict[str, str]:
    """{escritura: su marca padre}: el prefijo más largo (en palabras) que ya es una marca con ≥ MIN_PARENT_ITEMS
    productos, o una familia curada. «coca cola zero» → «coca cola»; sin padre (o bloqueada), es su propia marca."""
    parent = {}
    for spaced in counts:
        words = spaced.split()
        best = spaced
        if spaced not in blocked:
            for k in range(len(words) - 1, 0, -1):
                prefix = " ".join(words[:k])
                if (counts.get(prefix, 0) >= MIN_PARENT_ITEMS or prefix in families) and len(
                    prefix
                ) >= MIN_PARENT_LENGTH:
                    best = prefix
                    break
        parent[spaced] = best
    return parent


def brand_index(
    counts: dict[str, int], rules: BrandRules, support: dict[str, float] | None = None
) -> dict[tuple[str, ...], str]:
    """{palabras de una marca: su marca padre} de las marcas que se buscan al inicio de un nombre: las declaradas en
    ≥ MIN_INDEX_ITEMS productos (cuyo nombre la lleva, si se conoce `support`), las familias y las extra."""
    parent = roll_up(counts, rules.families, rules.no_parent)
    index = {
        tuple(spaced.split()): parent[spaced]
        for spaced, n in counts.items()
        if n >= MIN_INDEX_ITEMS
        and len(spaced.replace(" ", "")) >= 3
        and spaced not in rules.name_stop
        and (support is None or support.get(spaced, 1.0) >= MIN_INDEX_SUPPORT)
    }
    for spaced in (*rules.families, *rules.extra_index):
        index[tuple(spaced.split())] = spaced
    return index


def infer_brand(name: str, index: dict[tuple[str, ...], str]) -> str | None:
    """La marca (padre) cuyo nombre abre `name`, la más larga si hay varias."""
    words = normalize(name).split()
    for size in range(min(max((len(k) for k in index), default=0), len(words)), 0, -1):
        if brand := index.get(tuple(words[:size])):
            return brand
    return None


def _slug(spaced: str) -> str:
    return spaced.replace(" ", "-")


def build_brands(conn: Connection) -> dict:
    """Recalcula `product_brands`, `brand_aliases` e `item_brands` (idempotente). Los `curado` de `item_brands` no se
    tocan y las marcas se actualizan en el lugar: el producto canónico no se pierde (se recalcula después)."""
    version, rules = load_brand_rules()
    run = start_layer_run(conn, "brands", rules_version(version, RULES_FILE, Path(__file__)))
    products = conn.execute(
        "SELECT master_product_id::text, name, coalesce(trademark, '') FROM catalog_items"
    ).fetchall()
    groups = dict(
        conn.execute(
            """SELECT ic.entity_id, c.parent_id FROM item_concepts ic JOIN concepts c USING (concept_id)
               WHERE ic.entity_type = 'catalog_item'"""
        ).fetchall()
    )

    # 1. Marcas declaradas: sin valores de relleno, sin cadenas que no están en el nombre y sin marcas que ningún
    #    ítem suyo nombra.
    declared: dict[str, NormBrand] = {}
    names_of: dict[str, list[str]] = defaultdict(list)
    for item_id, name, trademark in products:
        if (nb := norm_brand(trademark, rules)) and trademark_fits(trademark, name, rules):
            declared[item_id] = nb
            names_of[nb.spaced].append(name)
    support = {spaced: name_support(spaced, names) for spaced, names in names_of.items()}
    junk = {s for s, names in names_of.items() if len(names) >= JUNK_ITEMS and support[s] < JUNK_SUPPORT}
    declared = {i: nb for i, nb in declared.items() if nb.spaced not in junk}
    raw_of: dict[str, Counter] = defaultdict(Counter)  # escritura normalizada → escrituras originales
    for item_id, _name, trademark in products:
        if item_id in declared:
            raw_of[declared[item_id].spaced][trademark.strip()] += 1
    counts = {spaced: sum(c.values()) for spaced, c in raw_of.items()}
    parent = roll_up(counts, rules.families, rules.no_parent)

    # 2. Una marca por clave compacta del padre: gana como slug la escritura más frecuente; el nombre sale de las
    #    escrituras del propio padre.
    group_spaced: dict[str, Counter] = defaultdict(Counter)
    for spaced, n in counts.items():
        group_spaced[parent[spaced].replace(" ", "")][parent[spaced]] += n
    slug_of = {compact: _slug(c.most_common(1)[0][0]) for compact, c in group_spaced.items()}
    store_compact = {s.replace(" ", "") for s in rules.store_brands}
    curated_targets = {s.replace(" ", "") for s in rules.aliases.values()}
    brands: dict[str, dict] = {}
    for compact, c in group_spaced.items():
        top_spaced = c.most_common(1)[0][0]
        own = Counter()
        for spaced in counts:
            if spaced.replace(" ", "") == compact:
                own.update(raw_of[spaced])
        brands[slug_of[compact]] = {
            "name": own.most_common(1)[0][0] if own else top_spaced.title(),
            "kind": "marca",
            "store": compact in store_compact,
            "curated": compact in curated_targets,
            "items": sum(c.values()),
        }

    # 3. Marca de cada producto: declarada, o deducida del inicio del nombre si el producto es de un grupo de
    #    conceptos donde la marca ya tiene productos.
    index = {
        words: slug_of.get(spaced.replace(" ", "")) or _slug(spaced)
        for words, spaced in brand_index(counts, rules, support).items()
    }
    declared_groups: dict[str, Counter] = defaultdict(Counter)
    for item_id, nb in declared.items():
        if (group := groups.get(item_id)) is not None:
            declared_groups[slug_of[parent[nb.spaced].replace(" ", "")]][group] += 1
    curated_rows = {
        (e, i) for e, i in conn.execute("SELECT entity_type, entity_id FROM item_brands WHERE source = 'curado'")
    }
    item_rows, inferred = [], 0
    for item_id, name, _trademark in products:
        if ("catalog_item", item_id) in curated_rows:
            continue
        if nb := declared.get(item_id):
            item_rows.append(("catalog_item", item_id, slug_of[parent[nb.spaced].replace(" ", "")], "rappi", run))
        elif (key := infer_brand(name, index)) and inference_ok(declared_groups.get(key, {}), groups.get(item_id)):
            if key not in brands:  # familia o marca extra que Rappi no declara sola
                brands[key] = {"name": key.replace("-", " ").title(), "kind": "marca", "store": False,
                               "curated": False, "items": 0}  # fmt: skip
            brands[key]["store"] = brands[key]["store"] or key.replace("-", "") in store_compact
            item_rows.append(("catalog_item", item_id, key, "regla", run))
            inferred += 1

    # 4. Los platos toman la cadena del local como marca.
    taken = {b.replace("-", ""): b for b in brands}
    for item_id, chain in conn.execute(
        """SELECT mi.item_id::text, b.name FROM menu_items mi JOIN stores s USING (store_id)
           JOIN brands b ON b.brand_id = s.brand_id"""
    ).fetchall():
        if ("menu_item", item_id) in curated_rows or not (nb := norm_brand(chain_name(chain), rules)):
            continue
        key = taken.get(nb.compact)
        if key is None:
            key = taken[nb.compact] = _slug(nb.spaced)
            brands[key] = {"name": chain_name(chain), "kind": "cadena", "store": False, "curated": False, "items": 0}
        brands[key]["items"] += 1
        item_rows.append(("menu_item", item_id, key, "cadena", run))

    # 5. Escritura en el lugar: sin borrar en cascada (el producto canónico y lo curado a mano sobreviven).
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO product_brands (brand_key, name, kind, is_store_brand, curated, items)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (brand_key) DO UPDATE SET name = EXCLUDED.name, kind = EXCLUDED.kind,
                 is_store_brand = EXCLUDED.is_store_brand, curated = EXCLUDED.curated, items = EXCLUDED.items""",
            [(k, b["name"], b["kind"], b["store"], b["curated"], b["items"]) for k, b in brands.items()],
        )
        conn.execute("DELETE FROM item_brands WHERE source <> 'curado'")
        conn.execute("DELETE FROM brand_aliases")
        cur.executemany(
            "INSERT INTO brand_aliases (alias, brand_key, source, items) VALUES (%s, %s, %s, %s)",
            [
                (s, slug_of[parent[s].replace(" ", "")], "curado" if s in rules.aliases.values() else "rappi", n)
                for s, n in counts.items()
            ],
        )
    with conn.cursor().copy("COPY item_brands (entity_type, entity_id, brand_key, source, run_id) FROM STDIN") as copy:
        for row in item_rows:
            copy.write_row(row)
    conn.execute(
        """DELETE FROM product_brands p WHERE p.brand_key <> ALL(%s)
           AND NOT EXISTS (SELECT 1 FROM item_brands b WHERE b.brand_key = p.brand_key)""",
        (list(brands),),
    )
    for table in ("product_brands", "brand_aliases", "item_brands"):
        conn.execute(f"ANALYZE {table}")
    counts_out = {
        "marcas": len(brands),
        "alias": len(counts),
        "descartadas": len(junk),
        "productos": sum(1 for r in item_rows if r[0] == "catalog_item"),
        "deducidas_del_nombre": inferred,
        "platos": sum(1 for r in item_rows if r[0] == "menu_item"),
        "propias": sum(1 for b in brands.values() if b["store"]),
    }
    finish_layer_run(conn, run, counts_out)
    log.info("Marcas: %s", counts_out)
    return counts_out
