.PHONY: help install test lint mvp mvp-check dump-entrega build

.DEFAULT_GOAL := help

help:  ## Muestra esta ayuda
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-13s %s\n", $$1, $$2}'

# Los subproyectos tienen sus propios Makefile (rappi-scraper/ y rappi-ia/: install, test, lint, serve…); install, test
# y lint los recorren todos, con los mismos pasos que el CI. Las bases van aparte: `make db` (Homebrew) o
# `make db-docker` en rappi-scraper/, y `make db-test` en rappi-ia/.
install:  ## Instala los cuatro subproyectos: los .venv de rappi-scraper y rappi-ia (con el lock), la app y el panel
	$(MAKE) -C rappi-scraper install
	$(MAKE) -C rappi-ia install
	npm --prefix prototipo-app ci
	npm --prefix dashboard-empresa ci

test:  ## Todos los tests: rappi-scraper (rappi_test), rappi-ia (rappi_ia_test), la app y el panel
	$(MAKE) -C rappi-scraper test
	$(MAKE) -C rappi-ia test
	npm --prefix prototipo-app test
	npm --prefix dashboard-empresa test

lint:  ## Estilo de los cuatro subproyectos (ruff, eslint y prettier)
	$(MAKE) -C rappi-scraper lint
	$(MAKE) -C rappi-ia lint
	npm --prefix prototipo-app run lint
	cd prototipo-app && npx prettier --check src scripts
	npm --prefix dashboard-empresa run lint
	cd dashboard-empresa && npx prettier --check src scripts

mvp:  ## Demo local con servidores de desarrollo (base real, API :8000, app :5174, panel :5175; LAN=1 abre a la red local); para un servidor, ver docs/despliegue.md
	@LAN="$(LAN)" scripts/mvp.sh

mvp-check:  ## Recorre la app con Chrome contra un catálogo de prueba inventado (rappi_ia_test, :8010, :5184 y el panel en :5185)
	@scripts/mvp-check.sh

dump-entrega:  ## Respaldo de la base para entregar, sin las personas del prototipo (ver rappi-ia/README.md)
	$(MAKE) -C rappi-ia dump-entrega

# Dónde buscan la API las dos apps construidas: por defecto el mismo origen bajo /api (un proxy inverso la sirve).
VITE_API_URL ?= /api

build:  ## Construye la app y el panel para un servidor (VITE_API_URL=/api; VITE_DEMO=1 deja el interruptor de la demo; PANEL_BASE=/panel/) y revisa que dist/ no tenga rastros de desarrollo
	cd prototipo-app && npm ci && VITE_API_URL="$(VITE_API_URL)" npm run build
	cd dashboard-empresa && npm ci && VITE_API_URL="$(VITE_API_URL)" npm run build
	@scripts/check-dist.sh
