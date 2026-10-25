.PHONY: help install install-ml db-test migrate check-migrations verify-migrations deploy-migrate dump-entrega test lint format jev-categorias concepts embed eval synth analytics serve serve-lan warm warm-catalog probar-agente purge post-refresh prune-embeddings layers layer-report motor contract

PY := .venv/bin/python
# Python ≥ 3.13 para crear el .venv. En un macOS nuevo `python3` es el 3.9 del sistema: se prefiere python3.13
# (Homebrew: `brew install python@3.13`, que solo instala `python3.13`).
PYTHON ?= $(shell command -v python3.13 || command -v python3)
# Los comandos de Postgres: en macOS, los de postgresql@17 de Homebrew (no quedan en el PATH); sin brew (Linux, el
# contenedor jobs), los del PATH.
PG_BIN := $(if $(shell command -v brew),$(shell brew --prefix)/opt/postgresql@17/bin,$(patsubst %/,%,$(dir $(shell command -v createdb))))

help:  ## Muestra esta ayuda
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-17s %s\n", $$1, $$2}'

install:  ## Crea .venv con rappi-scraper (esquema) + API + dev (sin modelos)
	$(PYTHON) -m venv .venv
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -c requirements.lock.txt -e ../rappi-scraper -e ".[api,dev]"
	@test -f .env || cp .env.example .env

install-ml:  ## Agrega el modelo local de texto (e5, con torch) y Claude opcional (~1 GB de paquetes)
	$(PY) -m pip install -q -c requirements.lock.txt -e ".[ml,llm]"

db-test:  ## Crea la base de tests propia (rappi_ia_test)
	-$(PG_BIN)/createdb rappi_ia_test

migrate:  ## Aplica migraciones pendientes (viven en rappi-scraper)
	$(PY) -m rappi_ia migrate

deploy-migrate:  ## Paso del despliegue: respalda si hay migraciones pendientes, migra y da permisos (DB_API_ROLE)
	$(PY) -m rappi_ia deploy-migrate

dump-entrega:  ## Respaldo para entregar (data/entrega/): catálogo, capas, embeddings y simulados, sin el prototipo
	$(PY) -m rappi_ia dump-entrega

# Sin «##»: no sale en `make help` (la guardia de serve, serve-lan y make mvp; no se corre a mano). MIGRATE=1 la fuerza.
check-migrations:
	$(PY) -m rappi_ia check-migrations

test:  ## Tests (unitarios + integración contra rappi_ia_test)
	scripts/with-test-db-lock.sh $(PY) -m pytest

lint:  ## Revisa estilo y errores comunes
	$(PY) -m ruff check src tests
	$(PY) -m ruff format --check src tests

format:  ## Formatea el código
	$(PY) -m ruff check --fix src tests
	$(PY) -m ruff format src tests

contract:  ## Reescribe las respuestas de ejemplo de la API que usan la app (prototipo-app/src/api/fixtures) y el panel (uso del MVP)
	@$(PY) -c 'import os, sys, rappi_ia; os.environ.get("DATABASE_URL_TEST") or sys.exit("Falta DATABASE_URL_TEST: `make contract` no puede escribir los ejemplos")'
	RAPPI_CONTRACT_WRITE=1 scripts/with-test-db-lock.sh $(PY) -m pytest tests/integration/test_contract.py

jev-categorias:  ## Jev etiqueta las categorías nuevas (opcional: sin clave o sin adopción no hace nada; ver docs/jev.md)
	$(PY) -m rappi_ia map-categories --jev --solo-nuevas

concepts:  ## Capa 2: conceptos por producto y plato (con kNN si hay extra ml)
	$(PY) -m rappi_ia concepts

embed:  ## Embeddings de texto (incrementales) + índices HNSW por vertical
	$(PY) -m rappi_ia embed-text

prune-embeddings:  ## Borra del caché de embeddings los vectores sin uso (de más de 7 días)
	$(PY) -m rappi_ia prune-embeddings

# eval/thresholds.json está en git: `make eval` propone τ en el reporte y solo lo guarda con GUARDAR_TAU=1 (después,
# revisar el cambio y hacer commit). EVAL_ARGS suma otras opciones de `rappi-ia eval-search`.
GUARDAR_TAU ?=
EVAL_ARGS ?=

# --jev-auto suma a Jev como tercer juez solo con clave y adopción (docs/jev.md); si no, evalúa igual que siempre
eval:  ## Evalúa la búsqueda (léxico vs vectorial vs híbrido) y propone τ; GUARDAR_TAU=1 lo guarda en eval/thresholds.json
	$(PY) -m rappi_ia eval-search $(if $(filter 1,$(GUARDAR_TAU)),--guardar-tau) $(EVAL_ARGS) --jev-auto

synth:  ## Usuarios y eventos SIMULADOS para el panel y el motor (reemplaza los anteriores)
	$(PY) -m rappi_ia synth

analytics:  ## Resumen de métricas del panel
	$(PY) -m rappi_ia analytics

# Con el peso ya descargado, la API no consulta huggingface.co al cargarlos (~20 peticiones por arranque).
# Mira el modelo por defecto: con otro en .env que no está en caché, la API arranca sin esa capacidad (/health lo
# dice en «faltantes»); `make serve HF_OFFLINE=` lo descarga la primera vez.
HF_CACHE := $(or $(HF_HUB_CACHE),$(HOME)/.cache/huggingface/hub)
HF_MODELS := intfloat--multilingual-e5-base
HF_OFFLINE := $(shell for m in $(HF_MODELS); do test -d "$(HF_CACHE)/models--$$m" || exit 0; done; echo HF_HUB_OFFLINE=1)

# serve y serve-lan migran antes: tras un `git pull`, el código puede necesitar una migración nueva (sin la 019, todo
# lo que muestra productos respondía 500). Antes de migrar, check-migrations se niega a aplicar a la base real las
# migraciones de una rama sin fusionar (se registran por nombre de archivo: una editada después no se vuelve a aplicar).
# Con API_ENV=production (en el entorno o en el archivo que lee la API: RAPPI_ENV_FILE o .env) no hacen nada de eso:
# migrar es un paso del despliegue (`make deploy-migrate`, que respalda antes) y, mientras falte, /health da 503.
DOTENV ?= $(or $(RAPPI_ENV_FILE),.env)
API_ENV ?= $(shell sed -n 's/^API_ENV=//p' $(DOTENV) 2>/dev/null | tr -d "\"'" | tail -n 1)
SERVE_PREP := $(if $(filter production,$(API_ENV)),,check-migrations migrate)

serve: $(SERVE_PREP)  ## API en http://localhost:8000, solo este equipo (docs en /docs)
	$(HF_OFFLINE) $(PY) -m uvicorn rappi_ia.api.app:app --no-access-log --host 127.0.0.1 --port 8000

serve-lan: $(SERVE_PREP)  ## API en la red local (iPhone). Sin puerta de acceso (cada persona, su token firmado): solo red de confianza
	$(HF_OFFLINE) API_ALLOW_LAN=1 $(PY) -m uvicorn rappi_ia.api.app:app --no-access-log --host 0.0.0.0 --port 8000

# Las frases del guion (docs/demo.md) sin user_id: no se registran. Frío, «una hamburguesa» tarda 2 a 5 s; caliente, 0,3 s.
API ?= http://localhost:8000
DEMO_PHRASES := "sushi" "una hamburguesa" "vino tinto" "algo para el carrete" "tengo fiebre" \
	"me voy de vacaciones a la playa" "se me quedaron las llaves en la oficina"
ANALYTICS := kpis weekly opportunities trends funnel cohorts rhythm at-risk suggestions services multi-vertical \
	affinity assortment
# Los perfiles de gusto (sus `id` en offers/perfiles.toml): la escalera de cada uno, sin persona. En frío, la primera
# tardaba 4 a 5 s (el tope de la app para una oferta es 5 s); caliente, unos 0,2 a 0,3 s.
PROFILES := $(shell sed -n 's/^id = "\(.*\)"$$/\1/p' src/rappi_ia/offers/perfiles.toml)
# Las listas del catálogo viven en la caché de la API (catalog/cache.py): en frío, /catalog/home tardaba 2,7 s y las
# tiendas de una vertical, 0,5 a 0,8 s; calientes, 1 a 2 ms. Los restaurantes, con el orden y largo que piden la Home
# (6) y Favoritos (4).
CATALOG_LISTS := /catalog/home /catalog/deals "/catalog/restaurants?sort=rating&limit=6" \
	"/catalog/restaurants?sort=rating&limit=4"

# Sin Claude ni registros: solo lee el catálogo. `make mvp` lo corre en segundo plano cuando la API responde.
warm-catalog:  ## Calienta solo las listas del catálogo de la API (Home, ofertas, restaurantes y tiendas de cada vertical)
	@for path in $(CATALOG_LISTS) $$($(PY) -c 'from rappi_scraper.storage.search import VERTICALS; \
	  print(" ".join(f"/catalog/verticals/{v}/stores" for v in VERTICALS))'); do \
	  curl -s -o /dev/null -w "  %{http_code}  %{time_total}s  $$path\n" "$(API)$$path" || exit 1; done

warm: warm-catalog  ## Calienta la API antes de una demo (con la API ya corriendo; repetirlo tras un rato sin uso)
	@for q in $(DEMO_PHRASES); do \
	  curl -s -o /dev/null -w "  %{http_code}  %{time_total}s  $$q\n" -X POST $(API)/agent/ask -H 'Content-Type: application/json' \
	    -d "{\"message\": \"$$q\"}" || exit 1; done
	@for p in $(PROFILES); do \
	  curl -s -o /dev/null -w "  %{http_code}  %{time_total}s  perfil $$p\n" -X POST $(API)/agent/offer \
	    -H 'Content-Type: application/json' -d "{\"moment\": \"perfil\", \"context\": {\"perfil\": \"$$p\"}}" \
	    || exit 1; done
	@for m in $(ANALYTICS); do for s in synthetic prototype; do \
	  curl -s -o /dev/null $(API)/analytics/$$m?source=$$s; done; done
	@curl -s -o /dev/null $(API)/analytics/catalog && echo "Lista: API caliente."

FRASES ?=
probar-agente:  ## Prueba al agente con las frases de usuarios (con la API corriendo; ver docs/pruebas-de-usuario.md)
	@$(PY) scripts/probar_agente.py $(FRASES)

purge:  ## Borra el texto de consultas con más de 90 días (docs/diseno-ia.md §2) y a las personas del prototipo sin actividad en 180
	$(PY) -m rappi_ia purge

layers:  ## Capa de datos: medidas, marcas, atributos, grafo, segmentos y motor
	$(PY) -m rappi_ia measures
	$(PY) -m rappi_ia brands
	$(PY) -m rappi_ia canonical
	$(PY) -m rappi_ia attributes
	$(PY) -m rappi_ia relations
	$(PY) -m rappi_ia segments --source synthetic
	$(PY) -m rappi_ia segments --source prototype
	$(PY) -m rappi_ia motor

motor:  ## Motor multivertical: transiciones, combinaciones, compra cruzada, tendencias, afinidad y recompra (las dos fuentes)
	$(PY) -m rappi_ia motor

layer-report:  ## Reporte de calidad de las capas de perfiles (data/eval/capas.md)
	$(PY) -m rappi_ia layer-report

# Sin «##»: lo usa post-refresh en producción, donde migrar sin respaldo no corresponde (lo hace deploy-migrate).
verify-migrations:
	$(PY) -m rappi_ia migrate --solo-revisar

# purge va primero, para que la retención de 90 días se cumpla aunque falle un paso posterior, y otra vez al final
# para los eventos simulados que synth acaba de generar: también si falla un paso (p. ej. el motor, al final de
# layers), y entonces post-refresh sale con error. En producción (API_ENV=production) no migra: solo revisa.
# prune-embeddings va al final: si la limpieza falla, conceptos, embeddings, evaluación y capas ya quedaron al día.
post-refresh: $(if $(filter production,$(API_ENV)),verify-migrations,migrate) purge  ## Todo lo que sigue a un `rappi refresh`
	$(MAKE) jev-categorias concepts embed eval synth layers prune-embeddings || { $(MAKE) purge; exit 1; }
	$(MAKE) purge
	@echo "Listo: conceptos, embeddings, evaluación y datos simulados al día."
