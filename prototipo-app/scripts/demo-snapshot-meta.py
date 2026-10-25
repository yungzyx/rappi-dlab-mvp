"""Las tablas del backend que la API simulada de la demo sin conexión necesita y que la API no expone: los conceptos con
sus guardias de ofertas y las palabras con que se los nombra en una consulta (con las de las ocasiones y las de
relleno), los servicios sin catálogo, la tabla de combinaciones de Rappi (motor/combos.toml), los
nombres visibles de las verticales, los perfiles de gusto (offers/perfiles.toml) con los conceptos que los activan
(concepts/segments.toml) y las reglas de lo destacado (offers/destacado.toml). Lo corre `scripts/demo-snapshot.mjs`
con el Python de rappi-ia; escribe JSON en la salida estándar. No toca la base."""

import json

from rappi_ia.agent.grouped_search import SCREEN_VERTICALS
from rappi_ia.agent.tools import VERTICAL_LABELS
from rappi_ia.concepts.assign import _name_keyword, _query_only_words
from rappi_ia.concepts.taxonomy import load_taxonomy
from rappi_ia.layers.segments import load_segment_rules
from rappi_ia.motor.combos import FINE_ORDER, OWN_SIGNALS_ONLY, SERVICES, load_combos
from rappi_ia.offers.featured import load_rules
from rappi_ia.offers.guards import is_offerable
from rappi_ia.offers.profiles import load_profiles
from rappi_ia.text import FILLER_WORDS, tokens

taxonomy = load_taxonomy()
combos = load_combos()
segments = {rule.id: rule for rule in load_segment_rules()[1]}
featured = load_rules()


def phrase(text: str) -> str:
    """Una keyword como la compara concepts/matcher.py: palabras sin tildes ni signos, separadas por un espacio."""
    return " ".join(tokens(text))


def query_keywords(concept) -> dict:
    """Con qué palabras una consulta nombra el concepto (concepts/assign.py: concept_matcher con `for_queries`): las
    `alone` cuentan solo si son todo el pedido y `avoid` impide que calce. `broad`: agrupa productos de varios tipos."""
    alone = set(_query_only_words(concept))
    words = (*_name_keyword(concept, True), *concept.keywords, *concept.query_keywords)
    return {
        "keywords": list(dict.fromkeys(phrase(k) for k in words if k not in alone and tokens(k))),
        "alone": [phrase(k) for k in alone],
        "avoid": [phrase(a) for a in concept.avoid],
        "broad": concept.broad,
    }


def profile_concepts(profile) -> list[str]:
    """Los conceptos que activan los segmentos de un perfil de gusto, sin repetir y en orden."""
    found = [c for s in profile.segments for c in segments[s].signals.get("concepts", [])]
    return list(dict.fromkeys(found))


print(
    json.dumps(
        {
            "concepts": {
                c.id: {
                    "name": c.name,
                    "emoji": c.emoji,
                    "group": c.parent or c.id,
                    "offerable": is_offerable(c),
                    **query_keywords(c),
                }
                for c in taxonomy.concepts.values()
            },
            "services": {
                key: {
                    "id": taxonomy.services[payload].id,
                    "name": taxonomy.services[payload].name,
                    "pitch": taxonomy.services[payload].pitch,
                    "route": taxonomy.services[payload].route,
                }
                for key, payload in combos.services.items()
            },
            "combos": {
                "version": combos.version,
                "groups": combos.groups,
                "retention": {combo: row.retention_m1 for combo, row in combos.rappi.items()},
                "diminishing": {
                    "reduction_base": combos.diminishing.reduction_base,
                    "decay": combos.diminishing.decay,
                    "service": combos.diminishing.service,
                },
                "services": combos.services,
                "fine_order": list(FINE_ORDER),
                "service_keys": list(SERVICES),
                "own_signals_only": sorted(OWN_SIGNALS_ONLY),
            },
            "profiles": {
                p.id: {"name": p.name, "emoji": p.emoji, "main": p.main, "concepts": profile_concepts(p)}
                for p in load_profiles().values()
            },
            "featured": {
                "min_main_price": featured.min_main_price,
                "not_main": sorted(featured.not_main),
                "side_sections": [list(start) for start in featured.side_sections],
            },
            "occasion_keywords": [phrase(k) for o in taxonomy.occasions.values() for k in o.keywords],
            "filler_words": sorted(FILLER_WORDS),
            "vertical_labels": VERTICAL_LABELS,
            "screen_verticals": SCREEN_VERTICALS,
        },
        ensure_ascii=False,
    )
)
