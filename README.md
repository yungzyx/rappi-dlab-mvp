# rappi-dlab · Un motor que conecta las verticales de Rappi

Prototipo para Rappi Chile: un **motor multivertical** en la base de datos que aprende, de cada persona y de la población, qué verticales usa, cuál conviene sumarle y qué le toca pedir de nuevo, y un **prototipo navegable de la app** que lo muestra. La Home ordena sus accesos según el uso de cada persona, y Mochi, la mochila de Rappi con bigote, propone la siguiente vertical siguiendo la escalera Restaurantes → Turbo → Retail (que parte de la tabla de combinaciones que compartió el equipo de Rappi), recuerda lo que toca repetir y responde lo que se le pide desde el buscador. Detrás hay datos reales: el catálogo público de rappi.cl en Postgres + pgvector, una búsqueda híbrida evaluada y una capa de datos que entiende qué es cada producto. Un panel de negocio le muestra a la gerencia y a RappiAds qué decidir con eso.

Lo hizo Yung Chung con el equipo Rappitouille en el programa dLab, junto con Rappi Chile, entre septiembre y noviembre de 2026. Es un prototipo con una demo cerrada, no un producto oficial de Rappi ni un sistema en producción: las personas, los pedidos y los pagos son simulados o de prueba.

[![CI](https://github.com/yungzyx/rappi-dlab-mvp/actions/workflows/ci.yml/badge.svg)](https://github.com/yungzyx/rappi-dlab-mvp/actions/workflows/ci.yml)

<img src="prototipo-app/docs/screenshots/00-modo-demo.jpg" width="320" alt="Prototipo final: la Home con la barra de búsqueda de Mochi, los accesos Restaurantes y Turbo, la fila de verticales y Mochi saludando">

*El prototipo final. El interruptor de arriba (tecla **D**) alterna con la app como es hoy.*

## Cómo revisarlo

Tres caminos, de lo más rápido a lo más completo:

1. **La demo en línea:** [dlab-mvp.com](https://dlab-mvp.com) (la app) y [dlab-mvp.com/panel/](https://dlab-mvp.com/panel/) (el panel de negocio). Pide un usuario y una clave, que el equipo entrega aparte. Corre sobre el catálogo real con personas de prueba.
2. **La presentación sin conexión:** "Mochi MVP - Presentación.html" (y su versión para iPhone y iPad), un solo archivo que el equipo entrega aparte: la app, el panel, las personas de prueba y un recorrido automático por 9 capítulos. Abre sin internet. Cómo se arma: [presentacion/README.md](presentacion/README.md).
3. **El código**, en este orden: el motor multivertical ([`rappi-ia/src/rappi_ia/motor/`](rappi-ia/src/rappi_ia/motor/), con la tabla de Rappi en [`combos.toml`](rappi-ia/src/rappi_ia/motor/combos.toml)); las ofertas de Mochi, con su razón y sus guardias ([`offers/`](rappi-ia/src/rappi_ia/offers/)); la búsqueda híbrida ([`retrieval/`](rappi-ia/src/rappi_ia/retrieval/)); Mochi en la app ([`prototipo-app/src/components/assistant/`](prototipo-app/src/components/assistant/)) y el panel ([`dashboard-empresa/src/`](dashboard-empresa/src/)). Por qué se decidió cada cosa: [docs/decisiones.md](docs/decisiones.md). Para correrlo: [Probarlo](#probarlo).

**Stack:** Python 3.13 con FastAPI y un modelo local de embeddings (`intfloat/multilingual-e5-base`), Postgres 17 + pgvector, React 19 + Vite 8 (Node 22.22+ o 24.15+), y Docker Compose con Caddy en el servidor. Un LLM (Claude, por la API de Anthropic) es opcional y solo redacta.

## El problema

Vista desde fuera, cada vertical de Rappi parece un silo: lo que una persona compra en el supermercado no cambia lo que se le recomienda en licores, farmacia o restaurantes. La tabla que compartió el equipo de Rappi apunta a que la mayoría usa una sola vertical en el mes, y quienes combinan más vuelven más:

| Verticales usadas en el mes | % de usuarios | Pedidos por usuario | Vuelven al mes siguiente |
|---|---:|---:|---:|
| Solo Restaurantes | 62,6 % | 1,9 | 47 % |
| Restaurantes + Turbo | 6,6 % | 5,5 | 82 % |
| Restaurantes + Retail | 5,4 % | 4,7 | 76 % |
| Restaurantes + Turbo + Retail | 4,7 % | 10,5 | 93 % |
| Todo Chile | 100 % | 3,0 | 55 % |

*Dato compartido por Rappi: cohortes de enero a junio de 2026, agrupación gruesa de verticales. Tabla completa y contexto en [docs/contexto-y-problema.md](docs/contexto-y-problema.md).*

Es una **correlación, no un efecto**: quien ya pide mucho usa más verticales y además vuelve más. Solo un experimento con grupo de control mide si sumar una vertical retiene.

## La propuesta

**Buscar dentro de la vertical, entender a través de las verticales, e invitar a descubrir las que la persona no usa.** La búsqueda responde en las verticales que corresponden a la consulta, sin mezclar sus índices; los intereses se guardan como conceptos comunes a todas (cerveza, snacks salados, pañales…); y la tabla de Rappi es el punto de partida para elegir qué vertical sumar, mezclada con lo que el motor aprende de la población (hoy simulada). Cada sugerencia dice por qué.

| Pieza | Qué hace |
|---|---|
| **Motor multivertical** | Siete tablas en la base, con vistas estables en el esquema `capa`: la afinidad de cada persona por cada vertical, las transiciones y combinaciones con su retención, la compra cruzada, lo más pedido y la recompra (qué pide cada persona con ritmo y cuándo le toca). Se evalúa por fechas y elige sus pesos en validación. Lo personal sale de la persona; lo de la población, de una fuente declarada en cada oferta. |
| **Home que aprende el orden** | Los seis accesos pequeños se ordenan según lo que cada persona pide y abre ("Ordenadas según lo que más usas"); Mochi dice cuál movió y por qué. Restaurantes y Turbo no se mueven, Lealtad y Pro van al final y "Rappi hoy" no aprende. |
| **Mochi en la Home** | Saluda, acompaña el plan del día (un kit de varias verticales) y propone la siguiente vertical de la escalera con su porqué. Cuando toca, propone repetir ("¿Repetimos …? Pides cada N días.") o volver ("¿Volvemos a …?"). Se puede ocultar. |
| **Buscador con Mochi** | La única entrada de texto. Lo que parece un pedido ("¿qué llevo para un asado de 6?") se le pide a Mochi, que responde con una tarjeta de productos reales y su razón, refinable con chips ("Más barato", "Sin carne"). Muestra lo aprendido (con "Olvidar") y el perfil de gusto con su escalera. Sin chat ni consejo médico. |
| **El pedido como en la app de Rappi** | Un pedido por tienda, con envío y compra mínima del catálogo (o supuestos rotulados "de ejemplo"), Pro, créditos, cupón, +18 y "Deshacer pedido"; después, seguimiento, calificación, cancelar con rescate, cambios en vivo y ayuda. Con permiso, Mochi pide solo "lo de siempre" ("Pedir por mí"), con tope y las mismas guardias. |
| **Eventos con el sobre de Rappi** | Cada evento lleva id, hora y orden del cliente, pantalla, origen, posición y el `request_id` de la respuesta que lo originó; las listas cuentan lo que quedó a la vista y hay experimentos declarados con grupo de control. `capa.v_eventos_amplitude` los traduce al plan de tracking de Rappi. |
| **Panel de negocio** | Cuatro vistas para la gerencia y RappiAds: dónde está la venta cruzada, a quién estamos perdiendo, si funciona lo que ofrece Mochi, qué buscan y no encuentran, y los experimentos ([más abajo](#panel-de-negocio)). |

| La Home que aprende | Mochi propone una vertical | "¿Repetimos?" | El buscador con Mochi |
|:---:|:---:|:---:|:---:|
| <img src="prototipo-app/docs/screenshots/03-home-dinamica.jpg" width="170" alt="Home con los accesos reordenados: Chocolates y Rappi Mall primero, con la leyenda &quot;Ordenadas según lo que más usas&quot;"> | <img src="prototipo-app/docs/screenshots/22-vertical-por-probar.jpg" width="170" alt="Mochi en la Home pregunta &quot;¿Y si pruebas algo de Súper?&quot; y, en &quot;¿Por qué?&quot;, dice &quot;Porque aún no pides en el súper&quot;, con los botones Abrir el súper y Después"> | <img src="prototipo-app/docs/screenshots/21-recompra.jpg" width="170" alt="Bloque de ejemplo &quot;¿Repetimos café? Pides cada 7 días.&quot; con un café molido del catálogo, Ver producto y Después"> | <img src="prototipo-app/docs/screenshots/20-asistente.jpg" width="170" alt="Buscador con Mochi tras tocar &quot;Arma un carrete&quot;: snacks y bebidas de Express, y la sugerencia de sumar jugos del Súper"> |

**Cómo cruza las verticales.** Una recomendación cruzada va concepto → complemento → búsqueda en la otra vertical: quien pide cerveza en Licores ve snacks salados de Express ("Porque llevas 🍺 cerveza"); quien pide pizza ve bebidas gaseosas, porque su primer complemento (cerveza) Mochi no lo ofrece; quien busca pañales no ve nada, porque sus complementos son de bebé y salud. Para elegir la vertical, el motor parte de la tabla de Rappi y la mezcla con la retención aprendida, vertical por vertical, con RappiFavor y RappiTravel al final; dentro de ella, mezcla lo más pedido con las reglas aprendidas con un peso λ elegido en validación (hoy 0). Reglas de confianza: una sugerencia cruzada por respuesta, con su razón; nunca productos sensibles por iniciativa propia (medicamentos, salud sexual, tabaco, alcohol, bebé); Farmacia y Licores solo suben por señales de la propia persona; lo aprendido se ve y se borra.

## Cómo funciona

![Motor multivertical: señales y pedidos de la persona, y la tabla de Rappi, pasan por afinidad, recompra, paso de combinación y compra cruzada hasta la Home dinámica y las ofertas de Mochi](docs/diagramas/motor-flujo.png)

1. **Descarga (semanal).** `rappi refresh` lee las páginas públicas de rappi.cl y guarda catálogo, menús y precios con historial, respetando robots.txt.
2. **Postgres + pgvector.** El catálogo y `search_documents`, una partición por vertical.
3. **IA offline.** Cada producto recibe un concepto y un embedding de un modelo local (e5); una capa de datos suma atributos, marcas, grafo y segmentos, y al final el motor multivertical (`make layers`), todo en el esquema `capa` ([docs/capa-de-datos.md](docs/capa-de-datos.md)). Jev (TypeSafe) es opcional y viene apagado ([docs/jev.md](docs/jev.md)).
4. **Consulta.** Búsqueda híbrida por vertical (palabras + significado, combinadas por posición y reforzadas por el concepto); si nada calza, corrige el tipeo con el vocabulario del catálogo. Mochi entiende la consulta con reglas y datos, sin LLM; con clave de API, el LLM solo redacta sobre lo recuperado.
5. **API y prototipo.** FastAPI (:8000) atiende a la app (:5174) y al panel (:5175): el orden de la Home (`GET /profile/{id}/verticales`), las ofertas (`POST /agent/offer`), lo que se le pide a Mochi (`POST /agent/ask`) y el catálogo real (`/catalog`). Tras cada pedido recalcula la afinidad y la recompra de esa persona. La app no abre sin la API.

Diseño completo: [docs/diseno-ia.md](docs/diseno-ia.md). Diagramas interactivos, mapas de conceptos y del despliegue: [docs/README.md → Diagramas y mapas](docs/README.md#diagramas-y-mapas).

## Resultados

Cada cifra dice qué tipo de dato es. El detalle, con los reportes de cada fecha, está en [docs/resultados/](docs/resultados/README.md).

| Qué | Cifra | Tipo de dato |
|---|---|---|
| Catálogo | 253.945 documentos de búsqueda (84.024 productos, 165.623 platos y 4.298 tiendas), todos con embedding | Real (catálogo público): contado el 05-10 sobre la descarga del 04-10-2026; las descargas posteriores no se recontaron |
| Búsqueda | nDCG@10: híbrido 0,905 · sin refuerzo por concepto 0,842 · vectorial 0,835 · léxico 0,765 | Evaluación automática: 131 consultas en las 8 verticales ([22-10-2026](docs/resultados/busqueda-2026-10-22.md)) |
| Búsqueda: juicio LLM | 95 % de los 3 primeros resultados sirven o sirven a medias (66 % "sirve"); el juez por concepto coincide en el 70 % (κ 0,32) | Juicio LLM doble ciego de 200 pares, no humano ([25-10-2026](docs/resultados/juicio-llm-busqueda-2026-10-25.md)) |
| Búsqueda: juez de tres niveles | Lo que ve la persona, nDCG@10 0,906 → 0,952 y P@3 "sirve" 0,75 → 0,81; necesidades ("algo para la once") 0,80 → 0,91 y Rappi Mall 0,83 → 0,96 | Juicio LLM, no humano: 88 consultas con todo lo mostrado juzgado, antes y después de los cambios del 25-10 ([25-10-2026](docs/resultados/busqueda-2026-10-25.md)) |
| "Sin resultado" | precisión 1,00 (0 falsas alarmas) · recall 0,93 (54 de 58 negativas) | Evaluación automática ([22-10-2026](docs/resultados/busqueda-2026-10-22.md)) |
| Errores de tipeo | 53 de 53 recuperados en la búsqueda de la app (37 sin corregir), 52 por vertical y 48 por Mochi (31 sin corregir) | Evaluación automática ([25-10-2026](docs/resultados/busqueda-2026-10-25.md), [04-11-2026](docs/resultados/tipeo-2026-11-04.md)) |
| Seguimientos de Mochi (chips) | 25 conversaciones de 2 o 3 turnos: 21 bien, 4 a medias, 0 mal (antes 7, 8 y 10); las 40 preguntas libres, bien | Juicio propio sobre una copia de la base, no humano externo, medido el 25-10 con el campo de seguimiento; desde el 26-10 los mismos seguimientos van por chips, con la misma API ([25-10-2026](docs/resultados/mochi-conversacion-2026-10-25.md)) |
| Guardias de ofertas | 0 casos de alcohol, Farmacia, bebé, salud o sensibles en 2.851 productos ofrecidos | QA sobre el catálogo real con personas simuladas ([16-10-2026](docs/resultados/qa-motor-2026-10-16.md)) |
| Motor: próxima vertical | nDCG@8 0,980 frente a 0,918 del orden fijo | Simulado: prueba la mecánica, no el efecto ([04-11-2026](docs/resultados/simulados-2026-11-04.md)) |
| Conceptos | 86 a 88 % de precisión en la asignación de conceptos | Estimación con jueces LLM ([06-10-2026](docs/resultados/capas-precision-2026-10-06-nueva-muestra.md)) |
| Tests | rappi-ia 3.315 (y 2 omitidos) · scraper 281 · prototipo 996 · panel 130 | Al 02-11-2026: CI de main en `1752318`; no se recontaron con los PR posteriores |

> [!IMPORTANT]
> **Qué no es evidencia**
>
> - **Usuarios y eventos simulados.** El motor, los segmentos y las métricas de negocio usan personas simuladas (`source = 'synthetic'`): muestran la mecánica, no un resultado.
> - **La tabla de Rappi** es una correlación: no dice que sumar una vertical retenga.
> - **La ventaja del híbrido.** La relevancia se juzga por concepto y el híbrido recibe un refuerzo por ese mismo concepto; sin él, no se distingue del vectorial (0,842 frente a 0,835). El juicio LLM del 25-10 muestra que ese juez es generoso, así que el nDCG es optimista; el juez de tres niveles tampoco es humano. Falta el juicio humano.
> - **Las precisiones de la capa 2 y de la capa de datos** son estimaciones con jueces LLM.
> - **Lo que Mochi aprende de la persona** es de demo: se guarda bajo un id seudónimo del navegador, sin cuenta, y se borra con "Borrar mis datos".
> - **"No está en el catálogo"** no significa "Rappi no lo vende": en tiendas el catálogo es una muestra.

## Probarlo

Requisitos: Python 3.13, Node 22.22+ o 24.15+ y Postgres 17 con pgvector. Paso a paso, con la base y la actualización semanal: [docs/instalacion.md](docs/instalacion.md).

```bash
make install                                    # desde la raíz: los .venv de rappi-scraper y rappi-ia, la app y el panel
cd rappi-scraper && make db && cd ..            # Postgres 17 + pgvector con Homebrew (o `make db-docker`, con Docker)
cd rappi-ia && make install-ml db-test && cd .. # los modelos de IA (~1 GB) y la base rappi_ia_test
make mvp-check                                  # sin la base: siembra un catálogo inventado y recorre el MVP con Chrome (9 revisiones)
make mvp                                        # con el catálogo real: API (:8000), app (:5174) y panel (:5175); LAN=1 lo abre a la red local
```

`make mvp` necesita la base `rappi`. La forma rápida de tenerla es el **respaldo de entrega** (`make dump-entrega`), que el equipo entrega por un canal acordado, nunca por git: trae el catálogo, la capa de IA, el motor y las personas simuladas, sin el uso del MVP ([restaurarlo](docs/instalacion.md#3-base-de-datos)). Revisa dependencias, puertos y base, aplica las migraciones pendientes (no las de una rama sin fusionar) y no descarga nada de rappi.cl. La tecla **D** alterna "Prototipo final" y "Rappi hoy"; guion de demo en [docs/demo.md](docs/demo.md).

- **Demos sin conexión:** la app y el panel en un solo HTML cada uno, y `make presentacion` los junta con un recorrido automático ([prototipo-app/README.md](prototipo-app/README.md#demo-sin-conexión-prototipo-mvphtml), [dashboard-empresa/README.md](dashboard-empresa/README.md#panel-en-un-solo-html), [presentacion/README.md](presentacion/README.md)).
- **En un servidor:** demo cerrada con Docker Compose, Caddy con TLS y puerta de usuario y clave, identidad firmada, roles separados en la base y respaldos ([docs/despliegue.md](docs/despliegue.md)); o desde un Mac con Cloudflare Tunnel ([deploy/macos/README.md](deploy/macos/README.md)).

## Qué es real y qué es simulado

- **Real:** el catálogo, los precios y los menús (de rappi.cl), los conceptos, la capa de datos, la búsqueda y las respuestas de Mochi. Lo que muestran las pantallas sale de la API; su diseño (títulos, banners) sigue siendo de recortes de capturas de la app. El envío y la compra mínima salen del catálogo cuando la descarga los trae; si no, son supuestos rotulados "de ejemplo".
- **Simulado:** el pago, el seguimiento del pedido (llega a los 20 s) y las personas, eventos y pedidos de los que el motor aprende la población y con los que se calculan segmentos y métricas.
- **Supuestos rotulados "de ejemplo"** (`prototipo-app/src/screens/checkout/pricing.js` y `screens/tracking/`): Rappi Pro, créditos, cupones, tipos de entrega, costo de cancelar, garantía de Turbo, atraso, agotado en vivo y plazos de la ayuda. Ninguno es una tarifa ni una política de Rappi.
- **Compartido por Rappi:** la tabla de combinaciones de verticales y su retención (`rappi-ia/src/rappi_ia/motor/combos.toml`). Una correlación, no un efecto.
- **Uso del MVP:** lo que hicieron en la app las pocas personas que la probaron (`source = 'prototype'`). El panel lo rotula "uso del MVP, pocas personas: no es evidencia".
- **Uso responsable:** solo páginas públicas sin barreras técnicas, una descarga a la vez con pausas de 1,5 a 3 s, una actualización por semana, User-Agent propio y robots.txt respetado. Sin datos personales: los usuarios son simulados o del prototipo (id seudónimo). Los datos descargados no se versionan. Fines de investigación y demostración; un uso comercial requeriría autorización de Rappi.

## Límites

- **El motor aprende de una población simulada** (`MOTOR_POBLACION`; con datos de Rappi se cambia la fuente, no el mecanismo). λ quedó en 1, pero las reglas aprendidas llegan a pocas personas (17 de 505) y en la prueba la mezcla acierta lo mismo que lo más pedido: en la práctica, Mochi ofrece lo más pedido.
- **La escalera parte de una correlación**, y la agrupación en `rest`, `turbo` y `retail` y el rendimiento decreciente de la escalera fina son supuestos propios. El efecto solo se mide con datos de Rappi y un grupo de control.
- **Cobertura parcial en tiendas:** hasta 24 productos por sub-pasillo y una sucursal por marca o formato; sin Mascotas. Las opciones obligatorias de un plato ("Elige 1 salsa") no están. Turbo tiene precios del 27-09-2026.
- **Mochi no ofrece por su cuenta alcohol, farmacia, bebé ni salud:** menos complementos ("playa" no sugiere protector solar). Entiende los pedidos con reglas, no con un LLM; no es un chat y la API no guarda historial.
- **Evaluación automática:** sin juicio humano; el refuerzo por concepto favorece al híbrido; el umbral de "sin resultado" se calibró sobre el mismo set.
- **Demo cerrada:** sin cuentas ni lanzamiento abierto. Si rappi.cl cambia su frontend, hay que ajustar los parsers.

Detalle y porqués en [docs/decisiones.md](docs/decisiones.md).

## Panel de negocio

[`dashboard-empresa/`](dashboard-empresa/) lee las métricas de la API (`/analytics`) y `make mvp` lo levanta junto a la app, en `http://localhost:5175/`. Para la gerencia y RappiAds, en cuatro vistas, cada una con su cifra, su comparación y una acción sugerida: **Resumen** (venta cruzada, a quién estamos perdiendo, si funciona lo que ofrece Mochi, qué buscan y no encuentran), **Retención y venta cruzada** (la escalera de Rappi, a quién invitar a volver, Pro y sin Pro), **Mochi y búsquedas** (ofertas por momento, el motor contra una regla simple, qué se ve y qué se toca, demanda no satisfecha, "¿Mochi molesta?") y **Experimentos** (cada experimento por variante, y cuál mide un efecto y cuál solo describe). Ningún pedido cancelado cuenta. La fuente se elige y nunca se mezcla: **Simulados** (por defecto; muestran la mecánica) o **Prototipo** (uso de pocas personas, rotulado "no es evidencia"; personas contadas, nunca nombradas).

## Dónde está cada cosa

```text
.
├── prototipo-app/          el prototipo final (Vite + React): la Home que aprende, Mochi y el buscador con Mochi
├── rappi-ia/               conceptos, embeddings, búsqueda, capa de datos, motor multivertical, Mochi y API (comando `rappi-ia`)
├── rappi-scraper/          descarga del catálogo público → Postgres + pgvector (comando `rappi`; migraciones de toda la base)
├── dashboard-empresa/      panel de negocio (Vite + React; lee la API) y la página de presentación
├── presentacion/           la presentación del MVP sin conexión (app, panel y recorrido automático en un solo HTML)
├── docs/                   contexto, diseño, decisiones, demo, instalación, despliegue, cambios y resultados (índice en docs/README.md)
├── deploy/                 despliegue en un servidor (compose, Caddy, roles, respaldos, timers) y macos/ (la demo desde un Mac)
├── Makefile, scripts/      `make mvp`, `make mvp-check`, `make presentacion` y revisiones del repositorio
├── .github/                CI (los cuatro subproyectos, `make mvp-check`, el stack de Docker, gitleaks), Dependabot y plantillas
└── CLAUDE.md               convenciones e invariantes del repositorio (para el equipo y para asistentes de código)
```

**Fuera del repositorio:** la base Postgres `rappi`, `rappi-scraper/data/` y `rappi-ia/data/`.

## Cambios desde el 25-10-2026

El repositorio de la entrega partió de un solo commit y siguió con PR revisados, uno por cambio: diez fases salidas de comparar el MVP con la app de Rappi, dos revisiones integrales, la presentación sin conexión, Mochi en la Home, la búsqueda en frío y la prueba con usuarios. La tabla completa, PR por PR y con sus migraciones: [docs/cambios.md](docs/cambios.md).

## Documentación

Índice por lo que buscas: [docs/README.md](docs/README.md). Decisiones con su porqué: [docs/decisiones.md](docs/decisiones.md). Para contribuir: [CONTRIBUTING.md](CONTRIBUTING.md). Seguridad: [SECURITY.md](SECURITY.md).

## Autor y licencia

Yung Chung ([yungzyx](https://github.com/yungzyx)) y el equipo Rappitouille, programa dLab (2026).

Todos los derechos reservados, con permiso de uso, copia y modificación internos para Rappi S.A.S. y sus filiales: ver [LICENSE](LICENSE). El repositorio incluye capturas, marcas y contenido de Rappi y de sus comercios, que pertenecen a sus dueños.
