# Instalación y operación

Cómo montar el proyecto completo en un Mac (Apple Silicon, macOS con [Homebrew](https://brew.sh)) y dejarlo actualizándose solo cada semana. Para un servidor Linux con Docker, ver [despliegue.md](despliegue.md).

Después de clonar (paso 2), **todos los comandos parten de la raíz del repositorio**.

## Qué viaja por dónde

| Qué | Cómo llega |
|---|---|
| Código (scraper, rappi-ia, prototipo, panel, docs) | Este repositorio (privado): `git clone` o `gh repo clone` |
| Base de datos (catálogo, precios, menús, conceptos, embeddings) | El respaldo de entrega (`make dump-entrega`), otro respaldo de Postgres (`.dump`) o una descarga nueva. **No va al repositorio:** contiene datos de rappi.cl y de sus comercios, que se usan solo con fines de investigación y demostración |
| Configuración (`.env`) | Se crea sola desde `.env.example` al instalar. `ANTHROPIC_API_KEY` y `TYPESAFE_API_KEY` son opcionales y se agregan a mano en `rappi-ia/.env` |
| Modelo de IA (e5; ~1 GB) | Se descarga de Hugging Face la primera vez que se usa |
| `node_modules`, `.venv` | Se instalan con los comandos de abajo; no se copian entre equipos |

## 1. Requisitos

```bash
brew install git gh python@3.13 node
python3.13 --version   # 3.13.x (el `python3` de macOS es 3.9 y no sirve; los Makefiles usan python3.13)
node --version         # 22.22+ o 24.15+
gh auth login          # GitHub.com → HTTPS → "Authenticate Git with your GitHub credentials": Yes
```

Sin Homebrew (Linux, o un Mac sin él): Python 3.13, Node y Docker; Postgres va en Docker con `make db-docker` (sección 3).

## 2. Código

```bash
gh repo clone yungzyx/rappi-dlab
cd rappi-dlab
```

Si este equipo va a correr la actualización semanal, clona el repositorio **fuera** de Documentos, Escritorio y Descargas (por ejemplo, directamente en tu carpeta de usuario). macOS no deja que las tareas programadas (launchd) lean esas carpetas, y la actualización fallaría sin avisar.

Desde la raíz, `make install` instala los cuatro subproyectos (los `.venv` de `rappi-scraper` y `rappi-ia` con el lock, la app y el panel), y `make test` y `make lint` los recorren todos con los mismos pasos del CI. Las bases van aparte (sección 3), y los modelos de IA con `make install-ml` en `rappi-ia/` (sección 4).

## 3. Base de datos

```bash
cd rappi-scraper
make db        # Postgres 17 + pgvector (Homebrew), bases rappi y rappi_test
make install   # .venv del scraper y .env
```

**Sin Homebrew:** `make db-docker` (en `rappi-scraper/`) levanta Postgres 17 + pgvector en Docker, con la misma imagen del CI y del despliegue, en `127.0.0.1:5432`, con las bases `rappi`, `rappi_test` y `rappi_ia_test`. Después, en `rappi-scraper/.env` y `rappi-ia/.env`, `DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rappi` y `DATABASE_URL_TEST` con `rappi_test` y `rappi_ia_test`, respectivamente. Los comandos de abajo (`createdb`, `pg_restore`, `psql`) se corren con el cliente de Postgres 17 del equipo o dentro del contenedor (`docker exec -i rappi-postgres …`).

`postgresql@17` no deja sus comandos (`psql`, `pg_restore`…) en el PATH. Para dejarlos siempre disponibles:

```bash
echo 'export PATH="$(brew --prefix)/opt/postgresql@17/bin:$PATH"' >> ~/.zprofile
source ~/.zprofile
```

**Desde el respaldo de entrega** (recomendado para un equipo nuevo). El equipo del proyecto lo arma con `make dump-entrega` en la raíz y lo entrega por un canal acordado, nunca por git. Es una carpeta `entrega_<fecha>/` con `catalogo.dump`, `poblacion-simulada.sql` y un `LEEME.txt` con los conteos. Trae el catálogo descargado con sus precios, los conceptos, las capas de datos (también el motor), los embeddings y documentos de búsqueda, y la población simulada; deja fuera el uso del MVP (las personas `prototype`, sus eventos, búsquedas y pedidos, y lo que el motor y el grafo aprendieron de ellas), así que el panel con la fuente del prototipo parte vacío. Detalle en [rappi-ia/README.md](../rappi-ia/README.md#respaldo-de-entrega).

Se restaura en Postgres 17 con pgvector 0.8, en tres pasos y en este orden: las tablas y el catálogo, la población simulada, y al final los índices, las claves foráneas y los triggers (así se validan juntos). Desde la carpeta del respaldo:

```bash
dropdb --if-exists rappi && createdb rappi
pg_restore --no-owner --no-privileges --section=pre-data --section=data --dbname=rappi catalogo.dump
psql --dbname=rappi --file=poblacion-simulada.sql
pg_restore --no-owner --no-privileges --section=post-data --dbname=rappi catalogo.dump
vacuumdb --analyze-only --dbname=rappi
```

Con un rol que no es superusuario, el primer `pg_restore` se salta los comentarios de las extensiones: `pg_restore --list catalogo.dump | grep -v 'COMMENT - EXTENSION' > lista.txt` y `--use-list=lista.txt`. Como la base ya trae los embeddings y la capa de IA calculados, `make post-refresh` (sección 4) recién hace falta después de una descarga nueva.

**Desde un respaldo del equipo de origen.** `make backup` en `rappi-scraper/` deja `data/backups/rappi_<fecha>.dump`, un solo archivo que sí trae el uso del MVP. Cópialo a este equipo y restáuralo:

```bash
dropdb --if-exists rappi && createdb rappi
pg_restore --no-owner -d rappi ruta/al/rappi_<fecha>.dump
```

En los dos casos, después, desde `rappi-scraper/`:

```bash
.venv/bin/rappi migrate    # migraciones nuevas, si las hay
.venv/bin/rappi status     # corridas y resumen por vertical
make test
```

**Opcional:** la restauración reconstruye los índices vectoriales (HNSW) y lo hace más rápido con más memoria de mantenimiento. Para darle 1 GB solo a esa sesión de Postgres, antepón `PGOPTIONS='-c maintenance_work_mem=1GB'` al `pg_restore` que arma los índices (el de `--section=post-data` en el respaldo de entrega, o el único en un respaldo de `make backup`). No cambia la configuración de Postgres. Si el equipo tiene poca memoria, usa un valor menor.

**Sin respaldo:** `.venv/bin/rappi migrate` crea las tablas y `.venv/bin/rappi refresh` descubre y descarga todo desde cero. Son días de descarga (la primera descarga completa tomó del 24 al 27-09-2026), porque va una página a la vez con pausas de 1,5–3 s. Se puede cortar y retomar con el mismo comando.

## 4. Capa de IA

```bash
cd rappi-ia
make install install-ml db-test migrate   # .venv, paquetes de los modelos (~1 GB), base de tests
make test
caffeinate -i make post-refresh           # purga, categorías nuevas con Jev (si está adoptado), conceptos, embeddings (y limpieza de los que ya no se usan), evaluación, datos simulados y capa de datos al día con la base, y otra purga
```

- **Con un respaldo al día** (como el de entrega), `make post-refresh` puede esperar a la próxima descarga: la base ya trae los conceptos, los embeddings y la capa de datos. Basta con `make install install-ml db-test migrate` y `make test`.
- **τ:** `make post-refresh` evalúa la búsqueda y propone τ en el reporte, pero no lo guarda: `src/rappi_ia/eval/thresholds.json` está en el repositorio. Para recalibrar, `make eval GUARDAR_TAU=1` en `rappi-ia/` (solo cambia las verticales con negativas que dependen de τ); después, revisar el cambio y hacer commit.
- **Evaluación:** el reporte queda en `data/eval/busqueda.md` (dentro de `rappi-ia/`).
- **Jev (opcional):** `post-refresh` corre primero `make jev-categorias` (Jev etiqueta las categorías nuevas) y `make eval` suma a Jev como juez, **solo** si `rappi-ia/.env` tiene `TYPESAFE_API_KEY` y el repositorio tiene `src/rappi_ia/eval/jev-adopcion.json` (se crea tras un piloto aprobado). Sin la clave o sin ese archivo ambos pasos no hacen nada, lo dicen en una línea y terminan bien, así que no hace falta instalar ni configurar nada para el flujo de siempre. Cómo ponerlo en marcha: [jev.md](jev.md).
- **Memoria de los índices:** `make embed` (parte de `post-refresh`) construye un índice HNSW por vertical con 1 GB de `maintenance_work_mem`, solo durante esa transacción. Se ajusta con `HNSW_MAINTENANCE_WORK_MEM` en `rappi-ia/.env` (ver `.env.example`); bájalo si el equipo tiene poca memoria.

## 5. El MVP

```bash
(cd prototipo-app && npm ci)
(cd dashboard-empresa && npm ci)
make mvp                  # desde la raíz del repositorio
```

`make mvp` es la **demo local**: levanta la API (:8000), la app (:5174) y el panel (:5175) sobre la base `rappi`, con el registro de cada uno prefijado (`[api]`, `[app]`, `[panel]`). No es para un servidor: migra la base sin respaldo (en un servidor, ver [despliegue.md](despliegue.md)):

1. Revisa que estén instalados `rappi-ia/.venv` y los `node_modules` de la app y del panel, y que los puertos 8000, 5174 y 5175 estén libres. Si falta algo, dice qué comando correr.
2. Revisa la base con `rappi-ia doctor` (solo lectura): si Postgres no responde, si la base `rappi` no existe o si no tiene catálogo, explica qué falta (sección 3) y termina.
3. Revisa las migraciones pendientes (`rappi-ia check-migrations`, solo lectura). Las migraciones se registran por nombre de archivo: una de rama que se aplica y después se edita nunca se vuelve a aplicar. Por eso, si la base `rappi` tiene pendientes y el código no está en `origin/main`, se niega: lista las pendientes y dice cómo seguir, con una copia de la base (`createdb -T rappi rappi_staging` con la API detenida y `DATABASE_URL=postgresql:///rappi_staging make mvp`) o a sabiendas con `MIGRATE=1 make mvp`. `make serve` y `make serve-lan` hacen la misma revisión. Con otra base (como la copia) o sin pendientes no pregunta nada.
4. Aplica las migraciones pendientes (`make migrate` en `rappi-ia/`) y arranca los tres. Si el paso 3 se negó, el script ya terminó y no escribe nada en la base.
5. Cuando responden, imprime «MVP listo: app http://localhost:5174 · panel http://localhost:5175 · API http://localhost:8000/docs». La API tarda en quedar lista porque carga el modelo de texto: la primera vez lo descarga (~1 GB) y puede tardar varios minutos. Mientras siga viva el script la espera y avisa cada 15 s («[mvp] La API sigue arrancando (cargando modelos)…»); solo termina si el proceso se cae.

Ctrl-C detiene los tres; si uno se cae solo, detiene el resto. No descarga nada de rappi.cl.

**Desde un celular:** `make mvp LAN=1` abre la API, la app y el panel a la red local (`make serve-lan` y `--host`); cada uno busca la API en el host desde el que se abrió la página. Solo en una red de confianza: la API no tiene puerta de acceso (los datos de cada persona sí piden su token de sesión).

- La app busca la API en el mismo host desde el que se abrió (puerto 8000), así que no hace falta configurarla.
- Sirve en una wifi local (192.168.x, 10.x), con el hotspot de un iPhone (el Mac queda en 172.20.10.x) y con el nombre Bonjour del Mac (`http://nombre-del-mac.local:5174`).
- macOS pide permiso de red la primera vez.

**Si aparece «Sin conexión con Mochi»:** la app no corre sin la API y no tiene respaldo local.

- ¿Está corriendo `make mvp`? Si no, levántalo desde la raíz.
- ¿La API terminó de cargar? Espera a «MVP listo» (o a «Application startup complete» en el registro `[api]`): la pantalla vuelve a probar sola cada 2 s y entra cuando responde; **Reintentar** prueba al instante.
- ¿Se abrió desde otro dispositivo? Entonces el MVP tiene que haberse levantado con `LAN=1`.
- ¿La API está en otro puerto o equipo? Crea `prototipo-app/.env.local` con `VITE_API_URL=http://localhost:8001` y reinicia la app.
- ¿La API se cayó? Mira el registro `[api]`: con Postgres caído responde 503.

**`make mvp-check`** recorre el MVP con Chrome (Playwright, usa el Google Chrome instalado) contra un catálogo de prueba **inventado**, sin tocar la base `rappi`. Siembra `rappi_ia_test` (`rappi-ia seed-demo`, que se niega con cualquier base que no termine en `_test`), levanta una API liviana en :8010, la app en :5184 y el panel en :5185 (que pide sus datos a esa API), y revisa:

1. **En línea:** la app abre en la Home, conectada (la primera visita muestra el aviso de privacidad y la prueba lo cierra).
2. **Compra:** Home → Súper → la primera tienda → agregar un producto → carrito → pagar. En `rappi_ia_test` (solo lectura) queda un pedido `prototype` cuyas líneas son productos sembrados.
3. **Kit de Mochi:** «cerveza» en el buscador con Mochi muestra un grupo por vertical; el kit «Carrete» de la Home, agregado y pagado, deja un pedido con productos sembrados y al menos una `suggestion_accepted` con origen `agent-plan` en `app_events`.
4. **Preguntarle a Mochi:** en el buscador con Mochi, «¿qué es un completo?» trae primero la fila «Pregúntale a Mochi» resaltada; Enter se lo pregunta y la tarjeta de Mochi muestra «Preguntaste «…»», la ficha del completo y el completo del catálogo de prueba. Después, «mi hijo tiene fiebre, ¿qué le doy?»: Mochi no da consejo médico, nombra al químico farmacéutico y ofrece «Ir a Farmacia».
5. **Home dinámica:** una persona nueva ve los 6 accesos en el orden fijo, con Lealtad y Beneficios Pro al final y sin el texto «Ordenadas según lo que más usas»; toca «Rappi Mall» tres veces, volviendo a la Home cada vez, espera hasta 30 s a que la API acepte los toques (`vertical_open`; al volver a la Home la app los manda y vuelve a pedir el orden) y, sin recargar, Rappi Mall queda primero y el texto aparece.
6. **Combinación:** una persona nueva pide en Restaurantes (Home → Restaurantes → el primer restaurante → agregar un plato → pagar), la app se recarga y Mochi, al tocarlo, propone **Turbo** (el siguiente peldaño de la escalera desde Restaurantes, con la tabla de Rappi como punto de partida) con su «¿Por qué?», que muestra la razón. Solo mira la vertical y que haya una razón: el texto exacto depende de lo que haya aprendido el motor.
7. **Panel:** abierto en «Mochi y búsquedas» con la fuente del prototipo, la tabla «Ofertas del agente por momento» muestra «Plan» con al menos una oferta aceptada (la del kit) y el rótulo «uso del MVP, pocas personas: no es evidencia», sin el aviso de datos guardados. Espera hasta 30 s a que la API ya cuente los eventos de las revisiones anteriores (la app los manda en lotes cada 5 s).
8. **Sin API:** al detener la API, la app muestra «Sin conexión con Mochi».

Mientras la API está en marcha, también falla ante un error de la página o de la consola o una respuesta 4xx/5xx (solo se ignoran las imágenes de prueba, que no existen). Termina con «MVP check: 8 de 8 bien» y no deja nada escuchando. Necesita libres los puertos 8010, 5184 y 5185. **Borra y vuelve a sembrar `rappi_ia_test`:** comparte con `make test` y `make contract` de `rappi-ia/` un candado (`.git/rappi-ia-test-db.lock`, en la carpeta común de git, así que también entre worktrees; fuera de git, `rappi-ia/.test-db.lock`), así que si otra prueba está corriendo sale de inmediato con «Otra prueba está usando rappi_ia_test»; si el proceso que lo tenía murió (kill -9, apagón), el siguiente comando toma el candado solo; si el aviso persiste y nada usa la base, el mensaje dice cómo borrarlo (`rm -rf` con la ruta del candado). Funciona igual en Linux (sin `lsof`; con `CHROME_PATH` o `PLAYWRIGHT_CHANNEL` se elige otro Chrome) y es el job `mvp-check` del CI (que sube capturas de las revisiones que fallen).

También: `make contract` en `rappi-ia/` reescribe las respuestas de ejemplo de la API que usa la app (`prototipo-app/src/api/fixtures/`; el CI falla si quedan desactualizadas), y `npm run screenshots` en `prototipo-app/` necesita la API corriendo y, como paga una compra, deja un pedido y sus eventos (`source = 'prototype'`) en la base que use la API. Para no tocar la base real, apunta la API a una copia: `DATABASE_URL=postgresql:///rappi_staging make mvp` (así se tomaron las capturas del 16-10-2026). Por eso el script se niega a correr sin la variable `SCREENSHOTS_ALLOW_WRITES=1` (`SCREENSHOTS_ALLOW_WRITES=1 npm run screenshots`). «¿Repetimos?» sale de la respuesta de ejemplo del contrato (`agent-offer-recompra.json`) con un café real del catálogo: es una ilustración, no un hábito medido. Las capturas del panel (`npm run screenshots` en `dashboard-empresa/`) usan la API si está arriba y, si no, los datos guardados de `src/fixtures/` (y lo avisan); no escriben en la base.

## 6. Actualización semanal

Va en **un solo** equipo: uno que quede siempre encendido. Programarla en dos equipos duplicaría las descargas sobre rappi.cl.

```bash
cd rappi-scraper
make schedule          # domingos 03:00: descarga y, al terminar, capa de IA
make schedule-status   # ¿está activa? ¿cómo terminó la última vez?
```

- **Qué corre:** `rappi-scraper/scripts/refresh-semanal.sh`.
  - Primero `rappi migrate` (las migraciones que haya traído un `git pull`) y `rappi refresh`: tiendas, restaurantes, búsqueda, reportes y respaldo en `data/backups/` (quedan los últimos 4).
  - Si termina bien (o solo fallaron el respaldo o los restaurantes: códigos 3, 5 y 6 de `rappi refresh`, ver [rappi-scraper/README.md](../rappi-scraper/README.md)), `make post-refresh` de rappi-ia: purga (primero, para cumplir la retención aunque falle otro paso), categorías nuevas con Jev (solo con clave y adopción), conceptos, embeddings (y limpieza de los que ya no se usan, `make prune-embeddings`), evaluación (con Jev como juez si está adoptado), datos simulados, capa de datos (`make layers`) y otra purga.
  - Nunca corren dos descargas a la vez: los comandos que descargan comparten el candado `rappi-scraper/data/scraper.lock`, que el sistema suelta aunque el proceso muera. Además, la tarea semanal tiene su propio candado, que se borra aunque la corten con una señal (Ctrl-C, cerrar la terminal).
- **τ:** la evaluación semanal no guarda τ, porque `thresholds.json` está en el repositorio. Para recalibrar: `make eval GUARDAR_TAU=1` en `rappi-ia/` y commit.
- **Dormido o apagado:** si a esa hora el equipo estaba **dormido**, la tarea corre al despertar; si estaba **apagado**, esa semana se salta. Por eso conviene:
  - que no se duerma (Ajustes del Sistema → Energía → evitar el reposo automático);
  - que se encienda solo tras un corte de luz (misma pantalla); `sudo pmset -a autorestart 1 sleep 0` deja ambas cosas;
  - que quede con la sesión de macOS iniciada, porque launchd corre la tarea en la sesión de quien la programó.
- **FileVault:** en el equipo de la tarea semanal se mantiene activo ([decisiones.md](decisiones.md#operación)). Tras un corte de luz el equipo se reenciende pero espera la clave: hasta escribirla no corren Postgres ni la tarea, y si pasa el domingo 03:00 esa semana se salta.
- **Después de cada semana:** `make schedule-status` debe mostrar `last exit code = 0`. En «Últimas ejecuciones» (sale de `rappi-scraper/data/logs/ultimo-estado.txt`) hay una línea por ejecución:
  - `exit=0`: terminó bien;
  - «omitida»: otra descarga estaba en curso;
  - «interrumpida»: la anterior se cortó (apagado, corte de luz) y se retoma en la etapa donde quedó, sin volver a bajar tiendas ya terminadas; si el corte fue después de las descargas (en la búsqueda, el respaldo o la capa de IA), `./scripts/refresh-semanal.sh --resume-only` termina esos pasos sin descargar de nuevo;
  - «respaldo fallido»: la descarga y la capa de IA terminaron, pero no hay respaldo nuevo (se conservan los anteriores); el error está en `launchd.err.log`, y «Respaldo más nuevo» muestra de cuándo es el último;
  - «restaurantes sin actualizar»: falló el descubrimiento de restaurantes y no había una corrida anterior terminada de la que usar la lista; las tiendas, la búsqueda, el respaldo y la capa de IA sí se hicieron, y la semana siguiente se descubre de nuevo (si además falló el respaldo, la línea dice las dos cosas). Con un sitemap caído o bloqueado y esa lista, los restaurantes se bajan igual y la línea dice `exit=0`, con la nota siguiente;
  - «restaurantes con la lista de la corrida anterior»: el sitemap de restaurantes no respondió y se bajaron los restaurantes de la última corrida terminada (sin los nuevos); el detalle («⚠ sitemap bloqueado o caído: se usó la lista de la corrida N») está en el reporte de restaurantes, y la semana siguiente se descubre de nuevo. Si se repite varias semanas, revisar el error del sitemap en el reporte;
  - `exit=4` «detenida: posible bloqueo»: ver el punto siguiente;
  - `exit=7` «detenida: robots.txt no permite una página o no respondió»: el scraper consulta robots.txt antes de cada página y no se salta una prohibida; la corrida queda abierta y, mientras robots.txt no cambie, la próxima se detiene en la misma página. Hay que revisar qué página es (está en el log) y decidir qué hacer con ella; no se corre la capa de IA;
  - un código distinto de 0: falló; el detalle está en `rappi-scraper/data/logs/launchd.err.log`.
- **Posible bloqueo:** si 20 requests seguidos son rechazados (403, 429, página de desafío) o 10 jobs seguidos fallan sin respuesta útil de rappi.cl (403, 429, red), la descarga se detiene, el reporte de la corrida lo marca con ⛔ y la corrida queda abierta, salvo si fue al descubrir: la próxima actualización la retoma. No hay que hacer nada salvo revisar el reporte. Si el ⛔ se repite semana tras semana con los mismos jobs, no es un bloqueo sino un error fijo de esos jobs (por ejemplo, rappi.cl cambió esas páginas): hay que revisar su error. Mientras tanto no se actualiza nada; después de unas semanas (4 intentos) esos jobs quedan fallidos y la corrida sigue.
- **Reportes:** la salida completa queda en `rappi-scraper/data/logs/launchd.*.log` y el reporte de calidad en `rappi-scraper/data/reports/`.
- **`rappi refresh` lanzado a mano:** `./scripts/despues-del-refresh.sh` en `rappi-ia/` espera a que termine y corre `make post-refresh`, igual que la tarea semanal (tampoco guarda τ).

## 7. Operación

- **Jobs fallidos en una corrida** (el reporte los lista; a veces Rappi entrega páginas incompletas por un rato):

  ```bash
  cd rappi-scraper
  .venv/bin/rappi retry-failed --kind stores
  .venv/bin/rappi retry-failed --kind restaurants
  ./scripts/refresh-semanal.sh --resume-only
  ```

  Con `--resume-only` el script retoma solo las corridas que `retry-failed` reabrió, arma la búsqueda, respalda y actualiza la capa de IA. Sin esa opción, si uno de los dos `retry-failed` no reencoló nada (no había fallidos o ya llevan 4 intentos), esa corrida sigue cerrada y el script empezaría una nueva: por ejemplo, volvería a bajar todos los restaurantes (unas 5,5 h). Así se recuperaron el 28-09-2026 los fallidos de la primera descarga completa; farmacia, por ejemplo, pasó de 5 a 13 tiendas descargadas.
- **Después de un `git pull`:** `make migrate` en `rappi-scraper/` (aplica las migraciones nuevas del scraper y de rappi-ia, que comparten historial). La tarea semanal también las aplica antes de descargar, y `make serve`, `make serve-lan` y `make refresh` también. `rappi refresh` y `rappi build-search` lanzados a mano no corren con migraciones pendientes: piden `rappi migrate`.
- **Respaldo a mano:** `make backup` en `rappi-scraper/`.
- **Mover la carpeta del proyecto** rompe los `.venv` (guardan rutas absolutas): recréalos con `make install` en `rappi-scraper/` y `make install install-ml` en `rappi-ia/`. No la muevas con una descarga en curso.
- **Ver la base desde otro equipo**, sin abrir Postgres a la red:
  - en el equipo de la base, activa Ajustes del Sistema → General → Compartir → **Sesión remota** (SSH);
  - en TablePlus, crea una conexión **Over SSH** con ese equipo como servidor y la base en `127.0.0.1:5432`, `rappi`;
  - como comando de inicio, `SET default_transaction_read_only = on;`.

  Consultas de ejemplo: [sql/](sql/).

## 8. Despliegue

En un servidor Linux (Docker Compose, Caddy con TLS y puerta de acceso, roles de base separados, respaldos fuera del equipo): [despliegue.md](despliegue.md).
