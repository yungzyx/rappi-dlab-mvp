"""Procesa los jobs de tiendas: tienda → pasillos → sub-pasillos, y guarda todo en Postgres."""

import logging

from psycopg import Connection

from .. import config
from ..scraping.client import PAGE_ERRORS, RappiClient, StoreUnavailable
from ..scraping.next_data import ParseError
from ..scraping.store_parser import parse_aisles, parse_products, parse_store, parse_sub_aisles
from ..storage import repository
from .discover import canonical_vertical
from .queue import GONE_MID_CRAWL, NO_BRANCH_AVAILABLE, process_with_retry

log = logging.getLogger(__name__)

TOO_MANY_SKIPPED = "demasiadas páginas omitidas"


def _tag(products: list[dict], aisle_id=None, sub_aisle_id=None) -> dict[str, dict]:
    """Copia cada producto con su pasillo/sub-pasillo (sin mutar el original)."""
    return {
        str(p["product_id"]): {**p, "_aisle_id": aisle_id, "_sub_aisle_id": sub_aisle_id}
        for p in products
        if p.get("product_id")
    }


def crawl_store(client: RappiClient, store_data: dict, max_aisles: int | None = None) -> dict:
    """Recorre pasillos y sub-pasillos a partir de la página de la tienda ya descargada.

    Una página de pasillo o sub-pasillo ilegible se omite y se anota (`skipped_aisles`, con el id del pasillo o
    sub-pasillo); si no se pudo leer ningún pasillo, lanza ParseError para que el job quede fallido en vez de "hecho"
    solo con la portada. Un pasillo que redirige al listado (StoreUnavailable) no se atrapa aquí: es la sucursal la que
    dejó de despachar. Tampoco un posible bloqueo (PossibleBlock), que detiene la corrida."""
    store = parse_store(store_data)
    products = _tag(parse_products(store_data))
    aisles = []
    store_aisles = parse_aisles(store_data)[:max_aisles]
    skipped_aisles: list[int] = []
    attempted_pages = aisles_read = 0

    for aisle in store_aisles:
        aisles.append({**aisle, "parent_aisle_id": None})
        aisle_path = f"{store['path']}/{aisle['friendly_url']}"
        attempted_pages += 1
        try:  # leer la página también va aquí: puede llegar sin fallback['storefront/...'] (ParseError)
            aisle_data = client.get_next_data(aisle_path)
            aisle_products, sub_aisles = parse_products(aisle_data), parse_sub_aisles(aisle_data)
        except PAGE_ERRORS as exc:
            log.warning("  pasillo omitido %s: %s", aisle_path, exc)
            skipped_aisles.append(aisle["aisle_id"])
            continue
        aisles_read += 1
        products.update(_tag(aisle_products, aisle["aisle_id"]))

        for sub in sub_aisles:
            aisles.append({**sub, "parent_aisle_id": aisle["aisle_id"]})
            sub_path = f"{aisle_path}/{sub['friendly_url']}"
            attempted_pages += 1
            try:
                sub_products = parse_products(client.get_next_data(sub_path))
            except PAGE_ERRORS as exc:
                log.warning("  sub-pasillo omitido %s: %s", sub_path, exc)
                skipped_aisles.append(sub["aisle_id"])
                continue
            products.update(_tag(sub_products, aisle["aisle_id"], sub["aisle_id"]))

    if store_aisles and not aisles_read:  # sin números en el mensaje: el reporte agrupa los errores por texto
        log.warning("  ningún pasillo se pudo leer (%d omitidos)", len(skipped_aisles))
        raise ParseError("ningún pasillo se pudo leer")
    context = store_data["props"]["pageProps"].get("storeContext")
    return {
        "store": store,
        "context": context,
        "aisles": aisles,
        "products": list(products.values()),
        "skipped_aisles": skipped_aisles,
        "attempted_pages": attempted_pages,
    }


def save_crawl(conn: Connection, run_id: int, crawl: dict, verticals: list[str]) -> int:
    store = crawl["store"]
    # Una tienda que solo salió en filtros llega sin store_type: recién su página dice si es Turbo, y la fila que
    # dejó el descubrimiento en el vertical del listado pasa a Turbo.
    page = {"store_type": store["store_type"], "subvertical": store["sub_group"]}
    with conn.transaction():
        repository.upsert_store(conn, store, raw=crawl["context"])
        for vertical in verticals:
            canonical = canonical_vertical(vertical, page)
            if canonical != vertical:
                repository.move_store_vertical(conn, store["store_id"], vertical, canonical)
            repository.upsert_store_vertical(conn, store["store_id"], canonical, store.get("sub_group") or "")
        repository.upsert_aisles(conn, store["store_id"], crawl["aisles"])
        return repository.save_products(conn, run_id, store["store_id"], crawl["products"])


def process_store_jobs(
    conn: Connection,
    client: RappiClient,
    run_id: int,
    vertical: str | None = None,
    limit: int | None = None,
    max_aisles: int | None = None,
) -> None:
    jobs = repository.pending_jobs(conn, run_id, "store_group", vertical)[:limit]
    log.info("%d jobs de tiendas pendientes", len(jobs))
    done_types = repository.store_types_done(conn, run_id)
    conn.commit()  # sin esto, la lectura queda «idle in transaction» durante todo el primer job
    process_with_retry(
        conn,
        run_id,
        jobs,
        lambda job: _run_store_job(conn, client, run_id, job["payload"], done_types, max_aisles),
        describe=lambda job: f"{job['job_key']} ({', '.join(job['payload']['verticals'])})",
    )


def _run_store_job(
    conn: Connection, client: RappiClient, run_id: int, payload: dict, done_types: set[str], max_aisles: int | None
) -> tuple[str, dict | None, str | None]:
    """Prueba las sucursales candidatas hasta scrapear una. Devuelve (status, result, error)."""
    error = NO_BRANCH_AVAILABLE
    for cand in payload["candidates"][: config.MAX_BRANCH_ATTEMPTS]:
        client.set_location(cand["lat"], cand["lng"], cand["city"], cand["city"])
        try:
            store_data = client.get_next_data(cand["path"])
            store_type = parse_store(store_data)["store_type"]
        except StoreUnavailable:
            log.info("  %s no disponible, probando otra", cand["store_id"])
            continue
        except PAGE_ERRORS as exc:
            log.warning("  %s falló: %s", cand["store_id"], exc)
            error = str(exc)
            continue
        if store_type and store_type in done_types:
            return "skipped", {"store_type": store_type, "reason": "marca ya scrapeada"}, None
        try:
            crawl = crawl_store(client, store_data, max_aisles)
        except StoreUnavailable as exc:  # un pasillo redirigió al listado: no guardar un catálogo a medias
            log.info("  %s dejó de estar disponible (%s), probando otra", cand["store_id"], exc)
            error = GONE_MID_CRAWL
            continue
        skipped, attempted = len(crawl["skipped_aisles"]), crawl["attempted_pages"]
        pages = {
            "pasillos_omitidos": crawl["skipped_aisles"],
            "paginas_omitidas": skipped,
            "paginas_intentadas": attempted,
        }
        if attempted and skipped / attempted > config.SKIPPED_PAGES_MAX:
            # Guardarla la volvería la corrida vigente del formato y escondería lo no leído: falla (y pasa por el
            # reintento), y la corrida anterior sigue siendo la que vale. Sin números: el reporte agrupa por texto.
            log.warning("  %s: %d de %d páginas omitidas, no se guarda", cand["store_id"], skipped, attempted)
            return (
                "failed",
                {"store_id": crawl["store"]["store_id"], "store_type": store_type, **pages},
                TOO_MANY_SKIPPED,
            )
        saved = save_crawl(conn, run_id, crawl, payload["verticals"])
        done_types.add(store_type)
        log.info("  -> %s: %d productos", crawl["store"]["name"], saved)
        result = {"store_id": crawl["store"]["store_id"], "store_type": store_type, "products": saved, **pages}
        return "done", result, None
    return "failed", None, error
