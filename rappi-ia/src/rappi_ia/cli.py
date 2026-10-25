"""CLI de rappi-ia.

Flujo típico (después de cada `rappi refresh` del scraper):
    rappi-ia migrate
    rappi-ia concepts                # capa 2: taxonomía, complementos, mapeos y conceptos por ítem
    rappi-ia concepts --solo-reporte # cobertura sin recalcular
    rappi-ia map-categories          # categorías sin mapeo revisado, con concepto sugerido, a un CSV para revisar
    rappi-ia map-categories --jev    # Jev propone su concepto (solo con clave y adopción); --exportar para revisarlas
    rappi-ia measures | brands | canonical | attributes | relations
                                     # capa de datos: medidas, marcas, canónicos, atributos y grafo (`make layers`)
    rappi-ia segments --source synthetic   # segmentos de usuario por fuente (con historia)
    rappi-ia motor                   # motor multivertical de las dos fuentes (transiciones, combinaciones, afinidad…)
    rappi-ia layer-report            # calidad de las capas (data/eval/capas.md)
    rappi-ia layer-sample | layer-precision   # muestra fija de la capa para juzgar / precisión por regla
    rappi-ia embed-text              # embeddings e5 de search_documents (incremental) + HNSW por vertical
    rappi-ia prune-embeddings        # borra del caché los vectores que ya no usa ningún documento ni nombre
    rappi-ia search "algo para el carrete" --vertical licores
    rappi-ia eval-search             # léxico vs vectorial vs híbrido + calibración de τ ("sin resultado")
    rappi-ia eval-typos              # errores de tipeo (eval/typos.json): cuántos recupera la corrección
    rappi-ia eval-sample | eval-human   # muestra de pares para juzgar a mano / el juez automático contra esos juicios
    rappi-ia jev-planillas           # planillas CSV (data/eval/) para juzgar a mano; luego `eval-human` da el κ
    rappi-ia jev-piloto              # con clave y planillas juzgadas: mide a Jev y propone adoptarlo (o no)
    rappi-ia synth                   # usuarios y eventos SIMULADOS para el panel (reemplaza los anteriores)
    rappi-ia analytics               # resumen de métricas del panel (frecuencia, abandono, oportunidades…)
    rappi-ia purge                   # borra consultas de más de 90 días y personas del prototipo sin actividad
    rappi-ia multivertical           # mapa multivertical (docs/mapas/)
    rappi-ia seed-demo               # catálogo de prueba inventado, SOLO en la base DATABASE_URL_TEST (_test)
    rappi-ia doctor                  # revisa (solo lectura) que DATABASE_URL tenga catálogo; sale 1 si no
    rappi-ia check-migrations        # se niega a migrar la base real desde una rama sin fusionar (MIGRATE=1 lo fuerza)
    rappi-ia deploy-migrate          # paso del despliegue: respalda si hay pendientes, migra y da permisos
    rappi-ia dump-entrega            # respaldo para entregar, sin las personas del prototipo (solo lee la base)
    rappi-ia token proto-…           # token (X-User-Token) de una persona, firmado con el secreto de la API
"""

import argparse
import logging
import os
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import psycopg
from psycopg import sql
from rappi_scraper.storage.backup import backup_database
from rappi_scraper.storage.db import APPLIED_BY_DEPLOY, MIGRATE_LOCK, PendingMigrations, check_migrations

from . import config
from .concepts.pipeline import build_concepts
from .concepts.report import coverage_report, jev_review_path, render_text, write_category_proposals
from .concepts.taxonomy import load_taxonomy
from .db import changed_migrations, connect, database_url, migrate, pending_migrations
from .demo.doctor import check_database, check_pending_migrations
from .demo.seed import ensure_test_database, reset_test_database, seed_demo
from .layers.attributes import build_attributes
from .layers.brands import build_brands
from .layers.canonical import build_canonical
from .layers.graph import build_relations
from .layers.measures import build_measures
from .layers.report import layer_report
from .layers.segments import build_segments
from .retrieval.hybrid import MODES, Filters, retrieve

log = logging.getLogger("rappi_ia")


# Una tabla tomada más allá de MIGRATE_LOCK_TIMEOUT: lo dicen igual `migrate` y `deploy-migrate`, sin traceback.
BUSY_TABLE = "Una tabla está ocupada; la migración no se aplicó. Intenta de nuevo en unos minutos."


def cmd_migrate(conn, args) -> None:
    if args.solo_revisar:  # post-refresh en producción: las aplica el despliegue, que respalda antes
        try:
            check_migrations(conn, APPLIED_BY_DEPLOY)
        except PendingMigrations as exc:
            raise SystemExit(str(exc)) from exc
        print("Migraciones al día.")
        return
    try:
        applied = migrate(conn)
    except psycopg.errors.LockNotAvailable as exc:
        raise SystemExit(BUSY_TABLE) from exc
    print("Migraciones aplicadas: " + (", ".join(applied) if applied else "ninguna (al día)"))


def cmd_concepts(conn, args) -> None:
    if not args.solo_reporte:
        embedder = None
        if not args.sin_knn:
            try:
                from .embeddings.models import text_embedder

                embedder = text_embedder()
            except ImportError:
                log.warning("Sin el extra `ml` (sentence-transformers): conceptos solo por categoría y reglas")
        build_concepts(conn, embedder)
    print(render_text(coverage_report(conn)))


def cmd_attributes(conn, args) -> None:
    print(build_attributes(conn))


def cmd_layer_report(conn, args) -> None:
    out = config.DATA_DIR / "eval" / "capas.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(layer_report(conn, args.muestra), encoding="utf-8")
    print(f"Reporte en {out}")


def cmd_canonical(conn, args) -> None:
    print(build_canonical(conn))


def cmd_relations(conn, args) -> None:
    print(build_relations(conn))


def cmd_layer_sample(conn, args) -> None:
    from .layers import quality

    versioned = quality.sample_file(args.seed)
    if versioned.exists() and not args.force:
        raise SystemExit(f"{versioned} ya existe y tiene juicios asociados; usa --force para reemplazarla.")
    sample = quality.build_quality_sample(conn, args.seed)
    quality.save_sample(sample, versioned, quality.local_sample_file(args.seed))
    kinds = {k: sum(r["kind"] == k for r in sample) for k in ("atributo", "marca", "concepto")}
    print(f"{len(sample)} afirmaciones ({kinds}) en {versioned}")
    print(f"Textos para juzgar (fuera de git): {quality.local_sample_file(args.seed)}")


def cmd_layer_precision(conn, args) -> None:
    import json

    from .layers import quality

    judged = quality.judgments_file(args.seed)
    if not judged.exists():
        raise SystemExit(f"Todavía no hay juicios ({judged} no existe).")
    sample = quality.with_names(conn, json.loads(quality.sample_file(args.seed).read_text(encoding="utf-8"))["filas"])
    given = json.loads(judged.read_text(encoding="utf-8"))
    text = quality.render_precision(quality.precision_report(sample, given["juicios"]), given["juez"])
    after = quality.after_changes(sample, given["juicios"], quality.still_asserted(conn, sample))
    text += "\n" + quality.render_after(after)
    out = config.DATA_DIR / "eval" / f"capas-precision{quality._suffix(args.seed)}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text.split("## Reglas a revisar")[0])
    print(quality.render_after(after))
    print(f"Reporte en {out}")


def cmd_segments(conn, args) -> None:
    print(build_segments(conn, args.source, args.user))


def cmd_motor(conn, args) -> None:
    from datetime import datetime

    from .motor.build import build_motor
    from .motor.evaluate import not_evaluated, report

    out_dir = config.DATA_DIR / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    for source in [args.source] if args.source else ["synthetic", "prototype"]:
        counts = build_motor(conn, source, evaluate=not args.sin_evaluar)
        print(
            f"Motor ({source}): {counts['transiciones']} transiciones, {counts['combinaciones']} combinaciones "
            f"({counts['pasos']} pasos), {counts['combinaciones_finas']} combinaciones finas "
            f"({counts['pasos_finos']} pasos), {counts['reglas']} reglas de compra cruzada, {counts['tendencias']} "
            f"tendencias, {counts['afinidad']} filas de afinidad y {counts['recompra']} de recompra"
        )
        weights = counts["pesos"]
        evaluation = counts["evaluacion"]
        out = out_dir / f"motor-{source}.md"  # uno por fuente: una no pisa a la otra
        if evaluation is None:
            if args.sin_evaluar:
                why = "se pidió sin evaluar (--sin-evaluar)"
            elif counts["pedidos"] == 0:
                why = "sin pedidos"
            else:
                why = "menos de 84 días de pedidos"
            print(f"  Sin evaluar ({why}); pesos: {weights}")
            when = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
            out.write_text(not_evaluated(source, why, weights, when), encoding="utf-8")
        else:
            nv = evaluation["proximo_vertical"]
            notice = evaluation["validacion"].get("aviso")
            print(
                f"  Pesos {'(sin validar, los anteriores)' if notice else 'elegidos'}: {weights}; nDCG en prueba: "
                f"combinado {nv['combinado']['ndcg']}, afinidad {nv['afinidad']['ndcg']}, popularidad "
                f"{nv['popularidad']['ndcg']}, orden fijo {nv['orden_fijo']['ndcg']}"
            )
            out.write_text(report(evaluation, source), encoding="utf-8")
        print(f"  Informe en {out}")


def cmd_brands(conn, args) -> None:
    print(build_brands(conn))


def cmd_measures(conn, args) -> None:
    print(build_measures(conn))


def cmd_map_categories(conn, args) -> None:
    if args.jev:
        _map_categories_with_jev(conn, args)
        return
    if args.solo_nuevas or args.exportar:
        log.error("--solo-nuevas y --exportar van con --jev")
        sys.exit(2)
    rows = coverage_report(conn)["categorias_sin_mapear"]
    out = config.DATA_DIR / "concepts" / "categorias-sin-mapear.csv"
    write_category_proposals(rows, out)
    print(f"{len(rows)} categorías sin mapeo revisado en {out}")
    print("Revisar cada fila, cambiar el método a «curado» y copiarla a src/rappi_ia/concepts/category_map.csv.")


def _map_categories_with_jev(conn, args) -> None:
    from . import jev
    from .concepts import jev_map

    if args.exportar:
        out = jev_map.export_path()
        n = jev_map.export_for_review(conn, out_path=out)
        print(f"{n} categorías de Jev (aplicadas y pendientes) en {out}")
        print("Revisar cada fila, cambiar el método a «curado» y copiarla a src/rappi_ia/concepts/category_map.csv.")
        return
    adoption = jev.load_adoption()
    if not adoption.categorias:
        print(
            "Jev no está adoptado para etiquetar categorías (falta eval/jev-adopcion.json o dice que no):"
            " no se hace nada."
        )
        return
    client = jev.client_or_none()
    if client is None:
        print("Sin TYPESAFE_API_KEY: Jev no etiqueta categorías y no se escribe nada.")
        return
    if adoption.model_version and adoption.model_version != client.model:
        print(
            f"La adopción es para {adoption.model_version} y JEV_MODEL dice {client.model}: no se hace nada hasta"
            " repetir el piloto con ese modelo."
        )
        return
    summary = jev_map.map_categories(
        conn, client, load_taxonomy(), adoption.t_auto, only_new=args.solo_nuevas, variant=adoption.variante
    )
    conn.commit()
    print(
        f"Jev: {summary['consultadas']} categorías consultadas; mapeó {summary['mapear']},"
        f" {summary['revisar']} a revisión ({jev_review_path()}), {summary['nada']} sin concepto y"
        f" {summary['sin_respuesta']} sin respuesta."
    )
    if client.stats.stopped_by_cap:
        print(f"⚠ Se llegó al tope de {config.JEV_MAX_REQUESTS} llamadas (JEV_MAX_REQUESTS): faltaron categorías.")


def cmd_embed_text(conn, args) -> None:
    from .embeddings.models import text_embedder
    from .embeddings.text_store import ScrapeRunning, embed_search_documents, scrape_running

    if scrape_running(conn):  # antes de cargar el modelo
        log.error("Hay una corrida del scraper en curso: embed-text corre después (make post-refresh)")
        sys.exit(1)
    try:
        print(embed_search_documents(conn, text_embedder(), limit=args.limit))
    except ScrapeRunning as exc:
        log.error("%s", exc)
        sys.exit(1)


# Desde cuántos vectores borrados vale la pena sugerir VACUUM FULL (~4 KB cada uno: 10 mil son ~40 MB).
VACUUM_FULL_HINT_ROWS = 10_000


def cmd_prune_embeddings(conn, args) -> None:
    from .embeddings.text_store import ORPHAN_MIN_AGE_DAYS, ScrapeRunning, prune_orphan_embeddings

    try:
        result = prune_orphan_embeddings(conn)
    except ScrapeRunning as exc:
        log.error("%s", exc)
        sys.exit(1)
    deleted, left = result["vectores_borrados"], result["vectores_que_quedan"]
    print(f"Vectores sin uso de más de {ORPHAN_MIN_AGE_DAYS} días borrados: {deleted} (quedan {left}).")
    if deleted >= VACUUM_FULL_HINT_ROWS:
        print("El espacio lo reusa autovacuum; para devolverlo al disco, VACUUM FULL text_embeddings a mano.")


def cmd_search(conn, args) -> None:
    embedder = None
    if args.modo != "lexico":
        from .embeddings.models import text_embedder

        embedder = text_embedder()
    result = retrieve(
        conn, args.vertical, args.query, embedder, k=args.limit, filters=Filters(args.precio_max), mode=args.modo
    )
    for i, hit in enumerate(result.hits, start=1):
        price = hit.metadata.get("precio_min", hit.metadata.get("precio"))
        cosine = f"{hit.cosine:.3f}" if hit.cosine is not None else "  -  "
        print(f"{i:>2}. [{hit.concept_id or '?':<16}] cos {cosine} ${price}  {hit.content[:90]}")
    print(f"Conceptos de la consulta: {result.query_concepts or '-'}")
    if result.unmet:
        print(f"⚠ Sin resultado (demanda no satisfecha): {result.unmet_reason}")


def cmd_eval_search(conn, args) -> None:
    from . import jev
    from .eval import search_eval
    from .retrieval.hybrid import thresholds

    jev_client = None
    if args.juez_jev:
        jev_client = jev.client_or_none()
        if jev_client is None:
            raise SystemExit("--juez-jev necesita TYPESAFE_API_KEY (en rappi-ia/.env): sin ella no hay juez Jev.")
    elif getattr(args, "jev_auto", False):
        jev_client = _adopted_jev_judge()
    embedder = None
    if not args.solo_lexico:
        from .embeddings.models import text_embedder

        embedder = text_embedder()
    runs = search_eval.run_queries(conn, embedder, search_eval.load_queries())
    summary = search_eval.summarize(runs)
    current = thresholds()
    proposed = search_eval.calibrate_tau(runs) if embedder else {}
    saved = bool(args.guardar_tau and proposed)
    in_use = search_eval.thresholds_after_saving(current, proposed) if saved else current
    if saved:
        search_eval.save_thresholds(in_use)
    unmet = search_eval.unmet_quality(runs, in_use, run_taus=current)
    model = embedder.model_name if embedder else None
    comparisons = search_eval.compare_modes(runs)
    jev_part = _jev_judgment(conn, jev_client, runs) if jev_client else None
    report = search_eval.render_markdown(summary, unmet, current, proposed, saved, model, comparisons, jev_part)
    out = config.DATA_DIR / "eval" / "busqueda.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"Reporte en {out}")


def cmd_eval_typos(conn, args) -> None:
    from .embeddings.models import text_embedder
    from .eval import typo_eval

    embedder = text_embedder()
    report = typo_eval.render_markdown(
        typo_eval.run_typos(conn, embedder, typo_eval.load_typos()),
        typo_eval.run_negatives(conn, embedder),
        typo_eval.run_grouped_negatives(conn, embedder),
    )
    out = config.DATA_DIR / "eval" / "tipeo.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"Reporte en {out}")


def _adopted_jev_judge():
    """El juez de Jev para la evaluación semanal: solo con clave y con la adopción del piloto. Si falta algo, dice
    en una línea por qué la evaluación sigue sin Jev; nunca falla."""
    from . import jev

    adoption = jev.load_adoption()
    if not adoption.juez:
        print(
            "Jev no está adoptado como juez (falta eval/jev-adopcion.json o dice que no): la evaluación sigue sin Jev."
        )
        return None
    client = jev.client_or_none()
    if client is None:
        print("Sin TYPESAFE_API_KEY: la evaluación sigue sin Jev.")
        return None
    if adoption.model_version and adoption.model_version != client.model:
        print(
            f"La adopción es para {adoption.model_version} y JEV_MODEL dice {client.model}: la evaluación sigue sin"
            " Jev hasta repetir el piloto con ese modelo."
        )
        return None
    return client


def _jev_judgment(conn, client, runs) -> dict:
    """Jev juzga lo que devolvió cada modo (lo que ya juzgó, de la caché); las personas, si hay planilla juzgada."""
    from .eval import judge, sheets

    judgments = judge.judge_pairs(conn, client, judge.pairs_from_runs(runs))
    conn.commit()
    sheet = sheets.sheet_dir() / sheets.SEARCH_SHEET
    human = sheets.read_search_sheet(sheet) if sheet.exists() else {}
    print(f"Jev ({client.model}): {len(judgments)} pares juzgados, {client.stats.requests} llamadas")
    return judge.jev_report(runs, judgments, human, client.model)


def cmd_eval_sample(conn, args) -> None:
    from .embeddings.models import text_embedder
    from .eval import judgments, search_eval

    runs = search_eval.run_queries(conn, text_embedder(), search_eval.load_queries())
    sample = judgments.build_sample(runs)
    judgments.save_sample(sample)
    diff = sum(p["origen"] == "diferencia" for p in sample)
    print(f"{len(sample)} pares ({diff} donde el refuerzo cambia el top 10) en {judgments.SAMPLE_FILE}")


def cmd_eval_human(conn, args) -> None:
    import json

    from .eval import judgments, sheets

    sheet = sheets.sheet_dir() / sheets.SEARCH_SHEET
    if sheet.exists() and sheets.SEARCH_IDS_FILE.exists():
        counts: Counter = Counter()
        human = sheets.read_search_sheet(sheet, counts)
        if human or counts["invalidas"]:
            pairs = json.loads(sheets.SEARCH_IDS_FILE.read_text(encoding="utf-8"))["pares"]
            report = judgments.sheet_report(pairs, human)
            print(
                f"Planilla de búsqueda: {report['juzgados']} de {len(pairs)} pares juzgados"
                f" ({report['sin_juicio']} sin juicio, {counts['invalidas']} inválidas, {counts['vacias']} vacías,"
                f" {report['desconocidos']} desconocidos, {report['a_medias']} «a medias»)"
            )
            if report["juzgados"]:
                print(
                    f"Personas vs juez por concepto: acuerdo {report['acuerdo']} · κ {report['kappa']}"
                    f" («sirve» contra el resto) · κ ponderado {report['kappa_ponderado']} (tres valores)"
                )
            else:
                print(
                    "Ningún juicio coincide con un par de la muestra: revisa que `juicio` use solo los valores"
                    " permitidos (sirve, a medias, no sirve) y que no hayas cambiado la columna `id`."
                )
            for stratum, row in report["por_estrato"].items():
                print(f"  {stratum}: {row['n']} pares, acuerdo {row['acuerdo']}")
            if not judgments.JUDGMENTS_FILE.exists():
                return
    if not judgments.JUDGMENTS_FILE.exists():
        raise SystemExit(f"Todavía no hay juicios a mano ({judgments.JUDGMENTS_FILE} no existe).")
    sample = json.loads(judgments.SAMPLE_FILE.read_text(encoding="utf-8"))["pares"]
    given = json.loads(judgments.JUDGMENTS_FILE.read_text(encoding="utf-8"))["juicios"]
    report = judgments.human_report(sample, given)
    auto, bonus = report["juez_auto"], report["refuerzo"]
    print(f"Pares juzgados: {report['juzgados']} de {len(sample)} (más {report['no_se']} «no sé»)")
    print(
        f"Juez automático vs juicio a mano: precisión {auto['precision']} · recall {auto['recall']}"
        f" · acuerdo {auto['acuerdo']}"
    )
    for side, label in (("solo_con_refuerzo", "solo con refuerzo"), ("solo_sin_refuerzo", "solo sin refuerzo")):
        print(f"Ítems que aparecen {label}: {bonus[side]['n']}, relevantes {bonus[side]['relevantes']}")


def cmd_jev_planillas(conn, args) -> None:
    from .embeddings.models import text_embedder
    from .eval import search_eval, sheets

    runs = search_eval.run_queries(conn, text_embedder(), search_eval.load_queries(), modes=(search_eval.SHOWN,))
    try:
        summary = sheets.build_sheets(conn, runs, force=args.forzar)
    except sheets.SheetInUse as exc:
        log.error("%s", exc)
        sys.exit(1)
    groups = ", ".join(f"{n} {group.replace('_', ' ')}" for group, n in summary["categorias"].items())
    print(
        f"{summary['pares']} pares de búsqueda ({summary['pares_discrepantes']} donde el juez por concepto y la"
        f" posición discrepan) y {sum(summary['categorias'].values())} categorías ({groups}) en {sheets.sheet_dir()}"
    )
    if short := sheets.shortfalls(summary):
        log.warning("Bajo la meta (el catálogo no alcanza): %s", "; ".join(short))
    print(f"Cómo llenarlas: {sheets.sheet_dir() / sheets.README_FILE}")


def cmd_jev_piloto(conn, args) -> None:
    from . import jev
    from .eval import jev_pilot

    client = jev.client_or_none()
    blocking, warnings = jev_pilot.requirements(client is not None)
    if blocking:
        print("Falta para correr el piloto de Jev (no se llamó a Jev):")
        for item in blocking:
            print(f"  - {item}")
        return
    for warning in warnings:
        print(f"⚠ {warning}")
    result = jev_pilot.run_pilot(conn, client, load_taxonomy())
    conn.commit()  # los juicios nuevos quedan en caché para eval-search
    categories, judge, usage, proposal = result["categorias"], result["juez"], result["uso"], result["propuesta"]
    if categories["pasa"]:
        print(
            f"Categorías: cumple con la variante «{categories['variante']}» y"
            f" T_auto {jev_pilot.fmt_num(categories['t_auto'])}"
        )
    else:
        print("Categorías: no cumple")
    print(
        f"Juez: {'cumple' if judge['pasa'] else 'no cumple'} (κ Jev {jev_pilot.fmt_num(judge['kappa_jev'], 3)},"
        f" κ juez por concepto {jev_pilot.fmt_num(judge['kappa_concepto'], 3)})"
    )
    for reason in result["no_confiable"]:
        print(f"⚠ Las cifras no valen para adoptar: {reason}")
    print(
        f"{jev_pilot.fmt_int(usage['llamadas'])} llamadas, {jev_pilot.fmt_int(usage['tokens'])} tokens de entrada,"
        f" ~US$ {jev_pilot.fmt_num(usage['costo'], 4)}"
    )
    print(f"Reporte en {result['reporte']}")
    if proposal["categorias"] or proposal["juez"]:
        print(
            f"Propuesta en {result['archivo_propuesta']}: para adoptar, renómbrala a jev-adopcion.json y súbela a git."
        )
    else:
        print(f"Propuesta en {result['archivo_propuesta']}: no se adopta, todo sigue igual sin Jev.")


def cmd_purge(conn, args) -> None:
    from .events.store import QUERY_RETENTION_DAYS, purge_inactive_users, purge_old_queries

    n = purge_old_queries(conn, args.dias or QUERY_RETENTION_DAYS)
    days = config.PROTOTYPE_USER_RETENTION_DAYS
    users = purge_inactive_users(conn, days)
    conn.commit()
    print(f"Consultas de más de {args.dias or QUERY_RETENTION_DAYS} días borradas: {n}")
    print(f"Usuarios del prototipo sin actividad en {days} días borrados: {users}")


def cmd_synth(conn, args) -> None:
    from datetime import date

    from .analytics.queries import learn_edges
    from .events.synth import DEFAULT_USERS, generate

    until = date.fromisoformat(args.hasta) if args.hasta else None
    users = DEFAULT_USERS if args.usuarios is None else args.usuarios
    print(generate(conn, users=users, weeks=args.semanas, seed=args.semilla, until=until))
    print(f"Aristas aprendidas (simuladas, el agente no las usa): {learn_edges(conn, 'synthetic')}")


def cmd_analytics(conn, args) -> None:
    import json

    from .analytics import queries

    report = {
        "kpis": queries.kpis(conn, args.fuente),
        "oportunidades": queries.opportunities(conn, args.fuente)[:8],
        "tendencias": queries.trends(conn, args.fuente)[:8],
        "retencion_multi_vertical": queries.multi_vertical_retention(conn, args.fuente),
        "sugerencias": queries.suggestions(conn, args.fuente)[:8],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


def cmd_multivertical(conn, args) -> None:
    from .analytics import multivertical

    paths = (Path(args.salida),) if args.salida else multivertical.OUTPUTS
    data = multivertical.write(conn, *paths)
    shared = f"{len(data['concepts'])} conceptos, {len(data['shared'])} pares de verticales"
    print(f"Mapa multivertical: {shared} → {', '.join(map(str, paths))}")


def cmd_seed_demo(conn, args) -> None:
    """Abre su propia conexión (`conn` llega vacío): solo DATABASE_URL_TEST, nunca la base real."""
    try:
        url = database_url("DATABASE_URL_TEST")
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    ensure_test_database(url)
    with connect(url) as test_conn:
        reset_test_database(test_conn)
        counts = seed_demo(test_conn)
    print(f"Catálogo de prueba listo: {sum(counts.values())} ítems en {len(counts)} verticales")


def cmd_doctor(conn, args) -> None:
    """Abre su propia conexión (`conn` llega vacío): así un Postgres caído da el mensaje, no un traceback."""
    try:
        url = database_url()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    ready, message = check_database(url)
    print(message)
    if not ready:
        sys.exit(1)


def cmd_check_migrations(conn, args) -> None:
    """Va antes de `migrate` en `make mvp` y `make serve`. Abre su propia conexión (`conn` llega vacío)."""
    try:
        url = database_url()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    allowed, message = check_pending_migrations(url, force=os.environ.get("MIGRATE") == "1")
    if not allowed:
        print(message, file=sys.stderr)
        sys.exit(1)
    if message:
        print(message)


# Permisos del rol de la API (lo escribe el despliegue, deploy/db/): nombra el rol como `{api_role}`.
GRANTS_FILE = config.PROJECT_ROOT.parent / "deploy" / "db" / "grants.sql"
# Los respaldos de antes de migrar rotan aparte de los semanales de `rappi refresh` (`rappi_*.dump`).
PRE_MIGRATION_BACKUP = "pre-migracion"


def deploy_migrate(conn, backup: Callable[[], Path] | None, grants_file: Path = GRANTS_FILE) -> None:
    """Migrar como paso del despliegue (el servicio `migrate`): si hay migraciones pendientes, primero `backup` (si
    falla, no migra; `None` es --sin-respaldo); después `migrate` y, con DB_API_ROLE, los permisos de ese rol
    (`grants_file`, idempotente). Dice qué hizo; sale con un mensaje (sin traceback) si algo falla.

    Todo va con el candado de `migrate` (MIGRATE_LOCK, de sesión; `migrate` lo vuelve a tomar en la misma sesión): un
    segundo despliegue a la vez espera al primero y ya no encuentra nada que respaldar ni aplicar."""
    role = os.environ.get("DB_API_ROLE")
    if role and not grants_file.is_file():
        raise SystemExit(f"DB_API_ROLE={role} pide aplicar {grants_file}, pero ese archivo no existe: no migro.")
    conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATE_LOCK,))
    conn.commit()
    try:
        _deploy_migrate_locked(conn, backup, role, grants_file)
    finally:
        if not conn.closed:
            conn.rollback()
            conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATE_LOCK,))
            conn.commit()


def _deploy_migrate_locked(conn, backup: Callable[[], Path] | None, role: str | None, grants_file: Path) -> None:
    for name in changed_migrations(conn):
        log.warning("La migración %s cambió después de aplicarse", name)
    pending = pending_migrations(conn)
    # Sin transacción abierta durante el volcado: pg_dump ya tiene las tablas tomadas (ACCESS SHARE) mientras dura.
    conn.commit()
    if not pending:
        print("Sin migraciones pendientes: no hace falta respaldo.")
    elif backup is None:
        print(f"Migraciones pendientes ({', '.join(pending)}): sigo sin respaldo (--sin-respaldo).")
    else:
        print(f"Migraciones pendientes ({', '.join(pending)}): respaldo antes de aplicarlas…")
        try:
            path = backup()
        except Exception as exc:
            raise SystemExit(f"No se pudo respaldar la base ({exc}): no migro.") from exc
        print(f"Respaldo listo: {path}")
    try:
        applied = migrate(conn)
    except psycopg.errors.LockNotAvailable as exc:
        raise SystemExit(BUSY_TABLE) from exc
    except psycopg.Error as exc:
        log.error("Error al migrar: %s", exc)
        remaining = [] if conn.closed else pending_migrations(conn)  # las anteriores ya quedaron confirmadas
        failed = remaining[0] if remaining else "pendiente"
        raise SystemExit(
            f"La migración {failed} falló y no se aplicó ({type(exc).__name__}; el detalle quedó en el registro)."
        ) from exc
    print("Migraciones aplicadas: " + (", ".join(applied) if applied else "ninguna (al día)"))
    if role:
        conn.execute(sql.SQL(grants_file.read_text(encoding="utf-8")).format(api_role=sql.Identifier(role)))
        conn.commit()
        print(f"Permisos del rol de la API ({role}) aplicados desde {grants_file}")


def cmd_deploy_migrate(conn, args) -> None:
    def backup() -> Path:
        return backup_database(database_url(), prefix=PRE_MIGRATION_BACKUP)

    deploy_migrate(conn, None if args.sin_respaldo else backup)


def cmd_dump_entrega(conn, args) -> None:
    """Abre su propia conexión (`conn` llega vacío) y solo lee DATABASE_URL: ver `delivery.py`."""
    from .delivery import README_FILE, build_delivery

    try:
        target = build_delivery(database_url(), Path(args.salida) if args.salida else None)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    print((target / README_FILE).read_text(encoding="utf-8"))
    print(f"Respaldo de entrega en {target}")


def cmd_token(conn, args) -> None:
    """Para herramientas del operador que leen rutas de una persona (su perfil): no toca la base."""
    from .api.identity import sign

    try:
        print(sign(args.user_id))
    except RuntimeError as exc:  # sin API_SECRET en producción
        raise SystemExit(str(exc)) from exc


# Comandos que no usan la conexión de DATABASE_URL (la abren ellos, usan otra o no la necesitan).
OWN_CONNECTION = {"seed-demo", "doctor", "check-migrations", "token", "dump-entrega"}

COMMANDS = {
    "token": cmd_token,
    "check-migrations": cmd_check_migrations,
    "deploy-migrate": cmd_deploy_migrate,
    "dump-entrega": cmd_dump_entrega,
    "doctor": cmd_doctor,
    "seed-demo": cmd_seed_demo,
    "measures": cmd_measures,
    "brands": cmd_brands,
    "canonical": cmd_canonical,
    "relations": cmd_relations,
    "segments": cmd_segments,
    "motor": cmd_motor,
    "layer-sample": cmd_layer_sample,
    "layer-precision": cmd_layer_precision,
    "layer-report": cmd_layer_report,
    "attributes": cmd_attributes,
    "multivertical": cmd_multivertical,
    "synth": cmd_synth,
    "purge": cmd_purge,
    "analytics": cmd_analytics,
    "migrate": cmd_migrate,
    "concepts": cmd_concepts,
    "map-categories": cmd_map_categories,
    "embed-text": cmd_embed_text,
    "prune-embeddings": cmd_prune_embeddings,
    "search": cmd_search,
    "eval-search": cmd_eval_search,
    "eval-typos": cmd_eval_typos,
    "eval-sample": cmd_eval_sample,
    "eval-human": cmd_eval_human,
    "jev-planillas": cmd_jev_planillas,
    "jev-piloto": cmd_jev_piloto,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rappi-ia", description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="log detallado")
    sub = parser.add_subparsers(dest="command", required=True)
    mg = sub.add_parser("migrate", help="aplica migraciones pendientes (las de rappi-scraper)")
    mg.add_argument(
        "--solo-revisar",
        action="store_true",
        help="no aplica nada: falla si falta una (post-refresh en producción; las aplica el despliegue)",
    )
    concepts = sub.add_parser("concepts", help="capa 2: conceptos, complementos y mapeo de productos y platos")
    concepts.add_argument("--solo-reporte", action="store_true", help="solo muestra la cobertura actual")
    concepts.add_argument("--sin-knn", action="store_true", help="sin refinar con vecinos cercanos (embeddings)")
    sub.add_parser("attributes", help="capa de perfiles: atributos de cada ítem (sin gluten, vegano, familiar…)")
    lr = sub.add_parser("layer-report", help="reporte de calidad de las capas de perfiles (data/eval/capas.md)")
    lr.add_argument("--muestra", type=int, default=20, help="ítems de muestra por atributo")
    sub.add_parser("brands", help="capa de perfiles: marca canónica de cada ítem (declarada o deducida del nombre)")
    sub.add_parser(
        "canonical", help="capa de perfiles: el mismo producto (marca + nombre + tamaño) entre ids y verticales"
    )
    sub.add_parser(
        "relations", help="capa de perfiles: grafo de conocimiento (sustituye, conflicto, tiene_atributo, co-búsqueda…)"
    )
    ls = sub.add_parser("layer-sample", help="capa de datos: muestra fija de afirmaciones (atributo, marca, concepto)")
    ls.add_argument("--seed", type=int, default=7, help="semilla (7 = la muestra original)")
    ls.add_argument("--force", action="store_true", help="reemplaza una muestra que ya existe")
    lp = sub.add_parser("layer-precision", help="capa de datos: precisión por regla según los juicios de la muestra")
    lp.add_argument("--seed", type=int, default=7, help="semilla de la muestra juzgada")
    sg = sub.add_parser("segments", help="capa de perfiles: segmentos de usuario por comportamiento (con historia)")
    sg.add_argument("--source", choices=["synthetic", "prototype"], default="synthetic")
    sg.add_argument("--user", help="recalcula solo a esta persona")
    mt = sub.add_parser(
        "motor",
        help="motor multivertical: transiciones, combinaciones, compra cruzada, tendencias, afinidad y recompra",
    )
    mt.add_argument("--source", choices=["synthetic", "prototype"], help="solo esta fuente (sin él, las dos)")
    mt.add_argument(
        "--sin-evaluar",
        action="store_true",
        help="no evalúa por fechas ni vuelve a elegir los pesos (quedan los de la corrida anterior)",
    )
    sub.add_parser("measures", help="capa de perfiles: tamaño, unidad y pack normalizados de cada ítem")
    mc = sub.add_parser(
        "map-categories", help="exporta las categorías sin mapeo revisado, con concepto sugerido, a un CSV para revisar"
    )
    mc.add_argument(
        "--jev",
        action="store_true",
        help="Jev propone el concepto (solo con TYPESAFE_API_KEY y eval/jev-adopcion.json)",
    )
    mc.add_argument("--solo-nuevas", action="store_true", help="con --jev: solo las categorías sin ningún mapeo")
    mc.add_argument(
        "--exportar",
        action="store_true",
        help="con --jev: exporta los mapeos de Jev y su cola de revisión a un CSV para pasarlos a category_map.csv",
    )
    embed = sub.add_parser("embed-text", help="embeddings de texto de search_documents (incremental)")
    embed.add_argument("--limit", type=int, help="máximo de textos nuevos (para probar)")
    sub.add_parser("prune-embeddings", help="borra del caché de embeddings los vectores que ya nadie usa")
    search = sub.add_parser("search", help="búsqueda híbrida dentro de un vertical")
    search.add_argument("query")
    search.add_argument("--vertical", required=True)
    search.add_argument("--modo", choices=MODES, default="hibrido")
    search.add_argument("--precio-max", type=float)
    search.add_argument("--limit", type=int, default=10)
    ev = sub.add_parser("eval-search", help="evalúa la búsqueda con el set de src/rappi_ia/eval/queries.json")
    ev.add_argument("--solo-lexico", action="store_true", help="sin modelo de embeddings")
    ev.add_argument("--guardar-tau", action="store_true", help="guarda los τ calibrados en eval/thresholds.json")
    ev.add_argument("--juez-jev", action="store_true", help="agrega a Jev como juez (necesita TYPESAFE_API_KEY)")
    ev.add_argument(
        "--jev-auto",
        action="store_true",
        help="agrega a Jev como juez solo si hay clave y eval/jev-adopcion.json lo adoptó; si no, sigue sin él",
    )
    sub.add_parser("eval-typos", help="errores de tipeo de src/rappi_ia/eval/typos.json y negativas de queries.json")
    sub.add_parser("eval-sample", help="muestra de ~200 pares (consulta, producto) para juzgar a mano")
    sub.add_parser("eval-human", help="juez automático y refuerzo por concepto contra los juicios a mano, y κ")
    sheets_cmd = sub.add_parser("jev-planillas", help="planillas CSV para juzgar a mano la búsqueda y las categorías")
    sheets_cmd.add_argument("--forzar", action="store_true", help="reemplaza planillas que ya tienen juicios")
    sub.add_parser("jev-piloto", help="mide a Jev contra las planillas juzgadas y escribe la propuesta de adopción")
    synth = sub.add_parser("synth", help="genera usuarios y eventos SIMULADOS (source = synthetic)")
    synth.add_argument("--usuarios", type=int, help="personas (por defecto DEFAULT_USERS)")
    synth.add_argument("--semanas", type=int, default=26)
    synth.add_argument("--semilla", type=int, default=7)
    synth.add_argument("--hasta", help="fecha final AAAA-MM-DD (por defecto hoy)")
    purge = sub.add_parser(
        "purge",
        help="borra el texto de consultas más antiguas que la retención (90 días) y a las personas del prototipo sin "
        "actividad en PROTOTYPE_USER_RETENTION_DAYS (180)",
    )
    purge.add_argument("--dias", type=int)
    mv = sub.add_parser(
        "multivertical", help="mapa de productos y conceptos compartidos entre verticales (presentación)"
    )
    mv.add_argument("--salida", help="un solo archivo HTML (por defecto docs/mapas/ y el del panel)")
    analytics = sub.add_parser("analytics", help="resumen de métricas del panel")
    analytics.add_argument("--fuente", choices=("synthetic", "prototype"), default="synthetic")
    sub.add_parser(
        "seed-demo", help="reconstruye DATABASE_URL_TEST (debe terminar en _test) con un catálogo de prueba inventado"
    )
    sub.add_parser("doctor", help="revisa que la base (DATABASE_URL) tenga catálogo; no escribe nada")
    sub.add_parser(
        "check-migrations",
        help="se niega si la base rappi tiene migraciones pendientes y el código no está en origin/main (MIGRATE=1)",
    )
    dm = sub.add_parser(
        "deploy-migrate",
        help="paso del despliegue: si hay migraciones pendientes respalda la base y las aplica; después, con "
        "DB_API_ROLE, los permisos de la API (deploy/db/grants.sql)",
    )
    dm.add_argument("--sin-respaldo", action="store_true", help="migra sin respaldar antes")
    de = sub.add_parser(
        "dump-entrega",
        help="respaldo para entregar: catálogo, capas, embeddings y población simulada, sin las personas del "
        "prototipo; solo lee DATABASE_URL",
    )
    de.add_argument("--salida", help="carpeta donde dejarlo (por defecto data/entrega/)")
    token = sub.add_parser(
        "token", help="token (X-User-Token) de una persona para las herramientas del operador; no toca la base"
    )
    token.add_argument("user_id")
    return parser


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    # Las peticiones a huggingface.co al cargar un modelo (~20 por carga) tapaban los errores del log semanal.
    for noisy in ("httpx", "httpx2"):
        logging.getLogger(noisy).setLevel(logging.DEBUG if verbose else logging.WARNING)


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)
    try:
        if args.command in OWN_CONNECTION:
            COMMANDS[args.command](None, args)
        else:
            with connect() as conn:
                COMMANDS[args.command](conn, args)
    except KeyboardInterrupt:
        log.warning("Interrumpido.")
        sys.exit(130)
