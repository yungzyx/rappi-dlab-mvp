# Cómo contribuir

Guía corta para cambiar el código de rappi-dlab. Las convenciones e invariantes del repositorio (migraciones, bases de test, guardias de ofertas, poblaciones de datos, nombres) están en [CLAUDE.md](CLAUDE.md): es la guía de convenciones del repo, escrita para que la lea cualquier persona del equipo y también un asistente de código. Léela antes del primer cambio.

## Instalar

Instalación completa, con la base y la actualización semanal: [docs/instalacion.md](docs/instalacion.md). En corto, desde la raíz:

```bash
make install                                    # los .venv de rappi-scraper y rappi-ia (con el lock), la app y el panel
cd rappi-scraper && make db && cd ..            # Postgres 17 + pgvector con Homebrew (o `make db-docker`, con Docker)
cd rappi-ia && make install-ml db-test && cd .. # los modelos de IA (~1 GB) y la base rappi_ia_test
```

Requisitos: Python 3.13, Node 22.22+ o 24.15+ (`.nvmrc`) y Postgres 17 con pgvector.

## Antes de abrir un PR

Corre lo que corresponde a lo que cambiaste; `make test` y `make lint` en la raíz corren todo lo de los cuatro subproyectos. El CI corre todo esto en cada PR, además de gitleaks sobre los archivos versionados.

| Si tocaste… | Corre |
|---|---|
| `rappi-scraper/` | `make test` y `make lint` en `rappi-scraper/` (integración contra `rappi_test`) |
| `rappi-ia/` | `make test` y `make lint` en `rappi-ia/` (integración contra `rappi_ia_test`) |
| Una respuesta de la API | además, `make contract` en `rappi-ia/`: reescribe las respuestas de ejemplo de `prototipo-app/src/api/fixtures/`, y el CI falla si quedan desactualizadas |
| `prototipo-app/` o `dashboard-empresa/` | `npm test`, `npm run lint` y `npx prettier --check src scripts` en esa carpeta |
| El recorrido de la app con la API | `make mvp-check` en la raíz: recorre el MVP con Chrome contra un catálogo inventado (8 revisiones) |
| Documentación | `python3 scripts/check-doc-links.py` en la raíz: revisa que los enlaces relativos de los `.md` (archivos y anclas) existan |

`make test` de rappi-ia, `make contract` y `make mvp-check` borran y siembran `rappi_ia_test` y comparten un candado: si otra prueba la está usando, salen de inmediato con un aviso. Nunca apuntes los tests a la base `rappi`.

## Reglas que el CI no revisa

- **Migraciones:** una migración nueva es un archivo nuevo con el número siguiente en `rappi-scraper/src/rappi_scraper/storage/migrations/` (un solo historial para toda la base). Una migración ya aplicada no se edita: se registra con el md5 de su archivo y `migrate` avisa si cambió. `make mvp` se niega a migrar la base `rappi` desde una rama sin fusionar; para probar, usa una copia (`createdb -T rappi rappi_staging`).
- **Datos:** las personas son solo simuladas (`source = 'synthetic'`) o del prototipo (`'prototype'`), nunca se mezclan en una cifra y lo simulado nunca se presenta como evidencia. Los datos descargados de rappi.cl y los respaldos de la base no van a git.
- **Idioma:** código (funciones, módulos, variables) en inglés; lo que ve una persona (textos de la app, logs, CLI, documentación, columnas) en español.
- **Ofertas:** todo lo que Mochi propone por su cuenta pasa por `rappi-ia/src/rappi_ia/offers/guards.py` (nunca alcohol, +18, Farmacia, bebé ni salud). Un cambio que lo afecte lleva su test.
- **Descargas:** nunca dos a la vez contra rappi.cl. Los comandos que descargan comparten un candado; no lo saltes.

## Commits y PR

- **Commits** en español, con el formato convencional `tipo(ámbito): qué cambia`:
  - tipos: `feat`, `fix`, `perf`, `refactor`, `test`, `docs`, `chore`, `ci`;
  - ámbitos frecuentes: `scraper`, `búsqueda`, `conceptos`, `motor`, `ofertas`, `api`, `app`, `panel`, `demo`, `deploy`, `deps`;
  - por ejemplo: `fix(ofertas): un trago sin concepto no se ofrece` o `docs: el respaldo de entrega en la instalación`.
- **Un PR por cambio**, contra `main`, con la plantilla: qué cambia y por qué, cómo se verificó (los comandos de arriba) y qué queda fuera. Si cambia una decisión de diseño, suma una fila a [docs/decisiones.md](docs/decisiones.md) con su motivo.
- **Cifras:** si un cambio mueve una cifra publicada (búsqueda, motor, tests), actualiza el reporte en `docs/resultados/` y el resumen del [README](README.md#resultados), diciendo qué tipo de dato es.

## Seguridad

Un problema de seguridad no se reporta en un issue: ver [SECURITY.md](SECURITY.md).
