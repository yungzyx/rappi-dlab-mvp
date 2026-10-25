## Qué cambia y por qué

<!-- Qué ve distinto una persona (o qué cambia en la base, la API o el despliegue) y el motivo. Si cambia una decisión, la fila nueva de docs/decisiones.md. -->

## Cómo se verificó

<!-- Marca lo que corriste. Ver CONTRIBUTING.md. -->

- [ ] `make test` y `make lint` en `rappi-scraper/`
- [ ] `make test` y `make lint` en `rappi-ia/`
- [ ] `make contract` en `rappi-ia/` (si cambió una respuesta de la API)
- [ ] `npm test`, `npm run lint` y `npx prettier --check src scripts` en `prototipo-app/`
- [ ] `npm test`, `npm run lint` y `npx prettier --check src scripts` en `dashboard-empresa/`
- [ ] `make mvp-check` en la raíz
- [ ] `python3 scripts/check-doc-links.py` (si cambió documentación)
- [ ] Revisado en el navegador, a 375 px y en escritorio (si cambió la app o el panel)

## Antes de fusionar

- [ ] Las migraciones nuevas son archivos nuevos; ninguna migración ya aplicada cambió.
- [ ] No hay datos descargados, respaldos ni secretos en el diff.
- [ ] Las cifras que cambian están en `docs/resultados/` y en el README, con su tipo de dato (real, evaluación, estimación o simulado).
- [ ] Lo que ofrece Mochi por su cuenta sigue pasando por las guardias (sin alcohol, +18, Farmacia, bebé ni salud).

## Qué queda fuera

<!-- Lo que no hace este PR y por qué. -->
