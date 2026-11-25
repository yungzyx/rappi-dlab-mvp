"""Procesa los jobs de restaurantes: una sucursal por cadena y cada restaurante independiente.

Desde el sitio en Astro (25-11-2026) el menú de un restaurante solo sale por secciones si la ubicación de despacho está
en su zona; si no, la página lo muestra entero como "No disponible" (`STATUS` OUT_OF_COVERAGE) y el parser no lo toma.
Por eso cada sucursal se pide con la ubicación en sus coordenadas guardadas; una que no tiene, sin ubicación (rappi.cl
usa entonces el centro de Santiago)."""

import logging

from psycopg import Connection

from .. import config
from ..scraping.client import PAGE_ERRORS, RappiClient, RestaurantGone
from ..scraping.restaurant_parser import parse_restaurant
from ..storage import repository
from .queue import NO_BRANCH_WITH_MENU, process_with_retry

log = logging.getLogger(__name__)

LOG_EVERY_N_JOBS = 25  # los restaurantes son muchos y rápidos: no se loguea cada uno


def process_restaurant_jobs(conn: Connection, client: RappiClient, run_id: int, limit: int | None = None) -> None:
    jobs = repository.pending_jobs(conn, run_id, "restaurant")[:limit]
    log.info("%d jobs de restaurantes pendientes", len(jobs))
    done_brands = repository.brands_done(conn, run_id)
    store_ids = [c["store_id"] for job in jobs for c in job["payload"]["candidates"] if c.get("store_id")]
    locations = repository.store_locations(conn, store_ids)
    conn.commit()  # sin esto, la lectura queda "idle in transaction" durante todo el primer job
    process_with_retry(
        conn,
        run_id,
        jobs,
        lambda job: _run_restaurant_job(conn, client, run_id, job["payload"], done_brands, locations),
        log_every=LOG_EVERY_N_JOBS,
    )


def _run_restaurant_job(
    conn: Connection,
    client: RappiClient,
    run_id: int,
    payload: dict,
    done_brands: set[int],
    locations: dict[int, tuple[float, float, str]],
) -> tuple[str, dict | None, str | None]:
    """Guarda la primera sucursal con menú. Si la marca ya se guardó en la corrida, se salta (pasa con un restaurante
    independiente que resultó ser de una cadena ya bajada)."""
    error = NO_BRANCH_WITH_MENU
    candidates = payload["candidates"][: config.MAX_BRANCH_ATTEMPTS]
    gone = 0
    for cand in candidates:
        if location := locations.get(cand.get("store_id")):
            lat, lng, city = location
            client.set_location(lat, lng, city, city)
        else:
            client.clear_location()
        try:
            parsed = parse_restaurant(client.get_page(cand["path"]))
        except RestaurantGone:
            gone += 1
            continue
        except PAGE_ERRORS as exc:
            log.warning("  %s falló: %s", cand["path"], exc)
            error = str(exc)
            continue
        brand_id = parsed["store"]["brand_id"]
        if brand_id and brand_id in done_brands:
            return "skipped", {"brand_id": brand_id, "reason": "marca ya scrapeada"}, None
        if not parsed["items"]:
            continue  # sucursal sin menú visible: probar otra de la cadena
        with conn.transaction():
            saved = repository.save_restaurant(conn, run_id, parsed)
        if brand_id:
            done_brands.add(brand_id)
        return "done", {"store_id": parsed["store"]["store_id"], "brand_id": brand_id, "items": saved}, None
    if candidates and gone == len(candidates):  # no hay nada que bajar: no es una falla del scraper
        return "skipped", {"reason": repository.GONE_REASON}, None
    return "failed", None, error
