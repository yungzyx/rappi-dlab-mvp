"""Descubrimiento: qué tiendas hay en cada vertical y qué restaurantes/cadenas existen.

Crea los jobs de la corrida. Modo catálogo: un job por formato de tienda (`store_type`,
que identifica marca + formato, p. ej. 'lider' o 'casaideas_multitiendas_enc') y un job
por cadena de restaurantes; los restaurantes independientes van uno por uno. Si el sitemap
de restaurantes no responde, se usa la lista de la última corrida terminada.
"""

import gzip
import logging
import re
from collections import defaultdict

import requests
from psycopg import Connection

from .. import config
from ..reporting import FALLBACK_LIST, fallback_message
from ..scraping.client import PAGE_ERRORS, PageNotFound, RappiClient, StoreUnavailable
from ..scraping.listing_parser import parse_brand_chain, parse_vertical_listing
from ..scraping.store_metadata import normalize_stores
from ..storage import repository

log = logging.getLogger(__name__)

# Vertical canónico -> listado de Rappi. Turbo no tiene listado propio: sale del subvertical.
VERTICAL_LISTINGS = {
    "supermercado": "/tiendas/tipo/market",
    "conveniencia": "/tiendas/tipo/express-big",
    "mall": "/tiendas/tipo/rappimall-parent",
    "farmacia": "/tiendas/tipo/farma",
    "licores": "/tiendas/tipo/licores",
    "chocolateria": "/tiendas/tipo/chocolateria",
}
MIN_STORES_PER_CITY = 3
MAX_CANDIDATES = 5
SITEMAP_BASE = "https://www.rappi.cl/sitemaps/country/cl/"
# Plantillas: los sitemaps vienen numerados (-0, -1, …; cada uno con hasta 50.000 URLs) y se leen todos.
CHAIN_SITEMAP = SITEMAP_BASE + "sitemap-restaurant-brand-chain-country-cl-{}.xml.gz"
PARTNER_SITEMAP = SITEMAP_BASE + "sitemap-restaurant-partner-cl-{}.xml.gz"
MAX_SITEMAP_SHARDS = 200  # tope por si rappi.cl respondiera 200 a cualquier número en vez de 404
SITEMAP_MAX_URLS = 50_000  # máximo de URLs por parte (protocolo de sitemaps): una parte con menos es la última
# Un sitemap que no se pudo bajar o leer. PossibleBlock no está: un bloqueo sigue deteniendo la corrida (código 4).
SITEMAP_ERRORS = (*PAGE_ERRORS, gzip.BadGzipFile, EOFError, UnicodeDecodeError)
_RESTAURANT_ID_RE = re.compile(r"/restaurantes/(\d+)")


FAILED_LISTINGS = "listados_fallidos"  # clave en scrape_runs.params


class SitemapUnavailable(Exception):
    """El sitemap de restaurantes no respondió y no hay una corrida anterior terminada de la que tomar la lista."""


def canonical_vertical(listing_vertical: str, store: dict) -> str:
    """Turbo es un vertical propio aunque Rappi lo muestre dentro de otros listados."""
    if store.get("subvertical") == "Turbo" or store.get("store_type", "").startswith("turbo"):
        return "turbo"
    return listing_vertical


def city_locations(metadata: dict) -> list[dict]:
    """Un punto de despacho por ciudad (desde el listado público S3), Santiago primero.

    Se usa la tienda con más reseñas y no el promedio de coordenadas: el promedio puede caer
    fuera de la zona de despacho (pasó en Viña del Mar y Antofagasta) y el listado da 404.
    """
    by_city = defaultdict(list)
    for store in normalize_stores(metadata):
        by_city[store["city"]].append(store)
    cities = []
    for city, stores in by_city.items():
        if len(stores) < MIN_STORES_PER_CITY:
            continue
        anchor = max(stores, key=lambda s: s["reviews"])
        cities.append({"city": city, "lat": anchor["lat"], "lng": anchor["lng"], "stores": len(stores)})
    return sorted(cities, key=lambda c: (c["city"] != "Santiago de Chile", -c["stores"]))


def discover_stores(
    conn: Connection,
    client: RappiClient,
    run_id: int,
    verticals: list[str],
    cities: list[dict],
    only: set[tuple[str, str]] | None = None,
) -> int:
    """Recorre los listados de cada vertical en cada ciudad y crea un job por formato de tienda.

    Parte de los jobs pendientes de la corrida, así redescubrir algunas ciudades suma
    candidatas y verticales en vez de reemplazar lo ya descubierto.

    Los listados que fallan o llegan sin tiendas quedan anotados en la corrida (`failed_listings`), como (ciudad,
    vertical); con `only` se piden solo esos. A las 03:00 las botillerías están cerradas y su listado llega sin
    tiendas: se reintenta al terminar la descarga de tiendas, y el reporte de calidad avisa de los que sigan fallando.
    """
    failed: list[list[str]] = []
    groups = repository.pending_payloads(conn, run_id, "store_group")
    for city in cities:
        wanted = [v for v in verticals if only is None or (city["city"], v) in only]
        if not wanted:
            continue
        client.set_location(city["lat"], city["lng"], city["city"], city["city"])
        for vertical in wanted:
            try:
                listing = parse_vertical_listing(client.get_next_data(VERTICAL_LISTINGS[vertical]))
            except (*PAGE_ERRORS, StoreUnavailable) as exc:
                log.warning("Listado %s en %s falló: %s", vertical, city["city"], exc)
                failed.append([city["city"], vertical])
                continue
            log.info("%-22s %-13s %3d tiendas", city["city"], vertical, len(listing))
            if not listing:
                failed.append([city["city"], vertical])
                continue
            for store in listing:
                store_vertical = canonical_vertical(vertical, store)
                if not store["store_type"]:
                    # Solo salió en filtros: si su página ya dijo que es Turbo (lo guardó save_crawl), sigue en Turbo.
                    saved = repository.saved_store_format(conn, store["store_id"])
                    store_vertical = canonical_vertical(store_vertical, saved)
                # Una tienda nacional sale en el listado de varias ciudades: la del listado solo vale si no tenía.
                repository.upsert_store(conn, {**store, "city": city["city"]}, keep_city=True)
                repository.upsert_store_vertical(
                    conn,
                    store["store_id"],
                    store_vertical,
                    store["subvertical"],
                    store["landing_classification"],
                    store["filters"],
                )
                _add_candidate(groups, store, store_vertical, city)
            conn.commit()
        # Guardar la cola después de cada ciudad: si algo falla, no se pierde lo descubierto.
        repository.add_jobs(
            conn,
            run_id,
            [{"job_key": key, "job_type": "store_group", "payload": payload} for key, payload in groups.items()],
        )
    repository.set_run_param(conn, run_id, FAILED_LISTINGS, failed)
    return len(groups)


def failed_listings(conn: Connection, run_id: int) -> set[tuple[str, str]]:
    """(ciudad, vertical) de los listados que fallaron la última vez que se descubrió en esa corrida."""
    return {(city, vertical) for city, vertical in repository.run_params(conn, run_id).get(FAILED_LISTINGS, [])}


def _add_candidate(groups: dict, store: dict, vertical: str, city: dict) -> None:
    # Sin store_type (tiendas que solo aparecen en filtros) no se puede agrupar por marca.
    key = f"type:{store['store_type']}" if store["store_type"] else f"id:{store['store_id']}"
    group = groups.setdefault(key, {"store_type": store["store_type"], "verticals": [], "candidates": []})
    if vertical not in group["verticals"]:
        group["verticals"].append(vertical)
    known = {c["store_id"] for c in group["candidates"]}
    if store["store_id"] not in known and len(group["candidates"]) < MAX_CANDIDATES:
        group["candidates"].append(
            {
                "store_id": store["store_id"],
                "path": store["path"],
                "city": city["city"],
                "lat": city["lat"],
                "lng": city["lng"],
            }
        )


def _sitemap_urls(client: RappiClient, template: str) -> list[str]:
    """URLs de todos los sitemaps numerados de la plantilla (-0, -1, …), hasta el primero que no existe. El -0 tiene que
    existir: sin él, el error sube (no es lo mismo que no haya restaurantes).

    El 18-10 rappi.cl respondió 403, no 404, a la parte -1 de cadenas, con la -0 muy lejos del tope: lo más probable
    es que no exista. Después de una parte con menos de SITEMAP_MAX_URLS no hay otra, así que ese 403 se toma como el
    final; después de una llena puede ser un bloqueo, y sube."""
    urls, last_count = [], 0
    for shard in range(MAX_SITEMAP_SHARDS):
        try:
            content = client.get_content(template.format(shard))
            xml = gzip.decompress(content).decode("utf-8")
        except (PageNotFound, gzip.BadGzipFile):  # una página de error con 200 en vez de un 404 también es el final
            if shard == 0:
                raise
            return urls
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if shard == 0 or status != 403 or last_count >= SITEMAP_MAX_URLS:
                raise
            log.warning(
                "Sitemap %s: la parte %d respondió 403 tras una de %d URLs (no llena): se toma como el final. Si fuera "
                "un bloqueo, faltarían las partes siguientes",
                template,
                shard,
                last_count,
            )
            return urls
        found = re.findall(r"<loc>([^<]+)</loc>", xml)
        urls += found
        last_count = len(found)
    log.warning("Sitemap %s: se leyeron %d partes sin llegar al final (tope)", template, MAX_SITEMAP_SHARDS)
    return urls


def _add_chain_job(conn: Connection, run_id: int, chain: dict, jobs: list, chain_store_ids: set) -> None:
    repository.upsert_brand(conn, chain["brand_id"], chain["name"], "restaurant")
    chain_store_ids.update(s["store_id"] for s in chain["stores"])
    if not chain["stores"]:
        conn.commit()
        return
    job = {
        "job_key": f"chain:{chain['brand_id']}",
        "job_type": "restaurant",
        "payload": {
            "verticals": ["restaurantes"],
            "brand_id": chain["brand_id"],
            "name": chain["name"],
            "candidates": [{"store_id": s["store_id"], "path": s["path"]} for s in chain["stores"][:MAX_CANDIDATES]],
        },
    }
    jobs.append(job)
    repository.add_jobs(conn, run_id, [job])  # se guarda al tiro (y hace commit)


def discover_restaurants(
    conn: Connection,
    client: RappiClient,
    run_id: int,
    max_chains: int | None = None,
    max_independents: int | None = None,
) -> int:
    """Un job por cadena (con sus sucursales como candidatas) y uno por restaurante independiente. Si un sitemap no
    responde, completa la cola con la lista de la última corrida terminada (`_use_previous_list`)."""
    # Sin ubicación la página de cadena lista todas sus sucursales; con ubicación, solo las cercanas.
    client.clear_location()
    jobs, chain_store_ids = [], set()
    try:
        chain_urls = _sitemap_urls(client, CHAIN_SITEMAP)[:max_chains]
    except SITEMAP_ERRORS as exc:
        return _use_previous_list(conn, run_id, exc, max_chains, max_independents)
    failed = []
    # Segunda pasada solo con las que fallaron (suelen ser errores transitorios de Rappi).
    for attempt, urls in enumerate((chain_urls, failed)):
        for chain_url in list(urls):
            try:
                chain = parse_brand_chain(client.get_next_data(chain_url.replace(config.BASE_URL, "")))
            except (*PAGE_ERRORS, StoreUnavailable) as exc:
                log.warning("Cadena %s falló (intento %d): %s", chain_url, attempt + 1, exc)
                if attempt == 0:
                    failed.append(chain_url)
                continue
            _add_chain_job(conn, run_id, chain, jobs, chain_store_ids)
    log.info("%d cadenas, %d sucursales en cadenas", len(jobs), len(chain_store_ids))

    try:
        partner_urls = _sitemap_urls(client, PARTNER_SITEMAP)
    except SITEMAP_ERRORS as exc:  # las cadenas recién descubiertas quedan; los independientes, de la lista anterior
        return len(jobs) + _use_previous_list(conn, run_id, exc, 0, max_independents, skip_store_ids=chain_store_ids)
    independents = []
    for url in partner_urls:
        match = _RESTAURANT_ID_RE.search(url)
        if match and int(match.group(1)) not in chain_store_ids:
            store_id = int(match.group(1))
            independents.append(
                {
                    "job_key": f"rest:{store_id}",
                    "job_type": "restaurant",
                    "payload": {
                        "verticals": ["restaurantes"],
                        "candidates": [{"store_id": store_id, "path": url.replace(config.BASE_URL, "")}],
                    },
                }
            )
    independents = independents[:max_independents]
    log.info("%d restaurantes independientes en la cola", len(independents))
    repository.add_jobs(conn, run_id, independents)
    return len(jobs) + len(independents)


def _use_previous_list(
    conn: Connection,
    run_id: int,
    exc: Exception,
    max_chains: int | None,
    max_independents: int | None,
    skip_store_ids: set[int] = frozenset(),
) -> int:
    """El sitemap no respondió (bloqueo o caída): la cola se completa con los jobs de la última corrida de restaurantes
    terminada por `refresh` (lo que se descubrió entonces, se haya bajado o no; sin los que ya no existían en Rappi), y
    se descargan con los mismos jobs, pausas y detección de bloqueos de siempre. Lo que ya estaba en la cola no se toca.
    Los topes valen como al descubrir (`max_chains=0`: sin cadenas, porque ya se descubrieron hoy), y un independiente
    que hoy es sucursal de una cadena (`skip_store_ids`) no entra. La próxima corrida nueva vuelve a descubrir. Sin una
    corrida anterior, sube SitemapUnavailable (la corrida queda fallida, como antes)."""
    error = f"{type(exc).__name__}: {exc}"
    source = repository.last_done_run_with_jobs(conn, "restaurants", run_id)
    if source is None:
        raise SitemapUnavailable(
            f"{error}. No hay una corrida de restaurantes terminada de la que usar la lista: no se actualizan"
        ) from exc
    previous_jobs = repository.run_jobs(conn, source, "restaurant", skip_reason=repository.GONE_REASON)
    chains = [j for j in previous_jobs if j["job_key"].startswith("chain:")][:max_chains]
    skipped_keys = {f"rest:{store_id}" for store_id in skip_store_ids}
    others = [j for j in previous_jobs if not j["job_key"].startswith("chain:") and j["job_key"] not in skipped_keys]
    previous = repository.run_params(conn, source).get(FALLBACK_LIST)
    # Los jobs y la nota se guardan juntos (set_run_param hace el commit): una corrida con la lista copiada lleva la
    # nota aunque se corte justo después.
    copied = repository.insert_new_jobs(conn, run_id, chains + others[:max_independents])
    fallback = {
        "corrida": source,
        "descubierta_en": previous["descubierta_en"] if previous else source,
        "restaurantes": copied,
        "error": error,
    }
    repository.set_run_param(conn, run_id, FALLBACK_LIST, fallback)
    log.warning("%s (%s)", fallback_message(fallback), error)
    return copied
