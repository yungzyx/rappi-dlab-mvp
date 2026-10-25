.PHONY: help install db db-docker migrate test test-unit test-integration lint format status report refresh backup schedule unschedule schedule-status

PY := .venv/bin/python
# Python ≥ 3.13 para crear el .venv. En un macOS nuevo `python3` es el 3.9 del sistema: se prefiere python3.13
# (Homebrew: `brew install python@3.13`, que solo instala `python3.13`).
PYTHON ?= $(shell command -v python3.13 || command -v python3)
PLIST := $(HOME)/Library/LaunchAgents/cl.rappi.refresh.plist
# `make schedule` es de macOS (launchd); en Linux remite a los timers de systemd (deploy/systemd/).
UNAME ?= $(shell uname -s)
# postgresql@17 de Homebrew no agrega sus comandos al PATH
PG_BIN := $(shell brew --prefix 2>/dev/null)/opt/postgresql@17/bin

help:  ## Muestra esta ayuda
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-17s %s\n", $$1, $$2}'

install:  ## Crea .venv e instala el proyecto con dependencias de desarrollo (versiones del lock, como el CI)
	$(PYTHON) -m venv .venv
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -c ../rappi-ia/requirements.lock.txt -e ".[dev]"
	@test -f .env || cp .env.example .env

db:  ## Instala y levanta Postgres 17 + pgvector (Homebrew) y crea las bases
	brew install postgresql@17 pgvector
	brew services start postgresql@17
	-$(PG_BIN)/createdb rappi
	-$(PG_BIN)/createdb rappi_test

# Sin Homebrew (Linux, o macOS sin brew): la misma imagen que el CI y el despliegue, publicada solo en 127.0.0.1. Espera
# por TCP: mientras la imagen inicializa la base, su servidor temporal solo escucha en el socket interno.
PG_IMAGE := pgvector/pgvector:0.8.7-pg17-trixie
DB_DOCKER_PORT ?= 5432
db-docker:  ## Postgres 17 + pgvector en Docker (sin Homebrew), con rappi, rappi_test y rappi_ia_test; ver .env.example
	docker start rappi-postgres 2>/dev/null || docker run -d --name rappi-postgres -e POSTGRES_PASSWORD=postgres \
	  -p 127.0.0.1:$(DB_DOCKER_PORT):5432 -v rappi-pgdata:/var/lib/postgresql/data $(PG_IMAGE)
	until docker exec rappi-postgres pg_isready -h 127.0.0.1 -U postgres -q; do sleep 1; done
	for db in rappi rappi_test rappi_ia_test; do \
	  docker exec rappi-postgres psql -U postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$$db'" | grep -q 1 \
	    || docker exec rappi-postgres createdb -U postgres $$db; done
	@echo "En .env: DATABASE_URL=postgresql://postgres:postgres@localhost:$(DB_DOCKER_PORT)/rappi (y …/rappi_test)"

migrate:  ## Aplica migraciones pendientes
	$(PY) -m rappi_scraper migrate

test:  ## Corre todos los tests
	$(PY) -m pytest

test-unit:  ## Solo tests unitarios (sin base de datos)
	$(PY) -m pytest tests/unit

test-integration:  ## Solo tests contra la base rappi_test
	$(PY) -m pytest tests/integration

lint:  ## Revisa estilo y errores comunes
	$(PY) -m ruff check src tests
	$(PY) -m ruff format --check src tests

format:  ## Formatea el código
	$(PY) -m ruff check --fix src tests
	$(PY) -m ruff format src tests

status:  ## Estado de las corridas y resumen por vertical
	$(PY) -m rappi_scraper status

report:  ## Reporte de calidad de la última corrida de tiendas
	$(PY) -m rappi_scraper report

refresh: migrate  ## Actualización completa: tiendas, restaurantes, búsqueda, reportes y respaldo
	$(PY) -m rappi_scraper refresh

backup:  ## Respaldar la base en data/backups/
	$(PY) -m rappi_scraper backup

schedule:  ## Programar la tarea semanal (descarga + capa de IA) los domingos 03:00 (launchd, en macOS)
ifeq ($(UNAME),Linux)
	@echo "En Linux la tarea semanal es un timer de systemd del despliegue: ver deploy/systemd/ y docs/despliegue.md."
	@exit 1
endif
	mkdir -p data/logs $(dir $(PLIST))
	sed "s#__PROJECT__#$(CURDIR)#g" scripts/launchd/cl.rappi.refresh.plist.template > $(PLIST)
	plutil -lint $(PLIST)
	-launchctl bootout gui/$$(id -u) $(PLIST) 2>/dev/null
	launchctl bootstrap gui/$$(id -u) $(PLIST)
	@echo "Programado: domingos 03:00. Estado: make schedule-status"

unschedule:  ## Quitar la programación semanal
	-launchctl bootout gui/$$(id -u) $(PLIST)
	rm -f $(PLIST)

schedule-status:  ## Ver si la programación semanal está activa y cómo terminaron las últimas ejecuciones
	@launchctl print gui/$$(id -u)/cl.rappi.refresh 2>/dev/null | grep -E "state =|runs =|last exit code" || echo "No programado en este equipo"
	@echo "Últimas ejecuciones (data/logs/ultimo-estado.txt):"
	@tail -n 5 data/logs/ultimo-estado.txt 2>/dev/null || echo "  ninguna todavía"
	@echo "Respaldo más nuevo (data/backups/):"
	@newest=$$(ls -t data/backups/rappi_*.dump 2>/dev/null | head -n 1); echo "  $${newest:-ninguno todavía}"
	@echo "Final del log de la corrida (data/logs/launchd.err.log; ahí quedan también los errores):"
	@grep -v "HTTP Request:" data/logs/launchd.err.log 2>/dev/null | tail -n 20 || echo "  sin log todavía"
