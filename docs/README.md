# Documentación

Índice de la documentación de rappi-dlab. Qué es el proyecto y cómo correrlo está en el [README principal](../README.md); las cifras vigentes, en [README.md#resultados](../README.md#resultados) (si un documento muestra otra cifra, manda el README).

## 1. Propuesta

| Si quieres… | Lee | Tiempo |
|---|---|---|
| Entender el problema, la tabla de Rappi y por qué existe el proyecto | [contexto-y-problema.md](contexto-y-problema.md) | 5 min |
| Entender la propuesta en una página: el motor multivertical, la Home dinámica y Mochi | [README principal](../README.md#la-propuesta) | 5 min |
| Ver el prototipo final: la Home que aprende, Mochi en la Home y el buscador con Mochi | [prototipo-app/README.md](../prototipo-app/README.md) | 5 min |
| Mostrarlo a alguien del negocio (guion de unos 12 minutos) | [demo.md](demo.md) | 3 min |
| Saber qué se decidió y por qué | [decisiones.md](decisiones.md) | 5 min |

## 2. Cómo funciona

| Si quieres… | Lee | Tiempo |
|---|---|---|
| Ver el sistema de un vistazo | [Diagramas y mapas](#diagramas-y-mapas) | 2 min |
| Entender el diseño del RAG, del agente Mochi y del panel | [diseno-ia.md](diseno-ia.md) | 20 min |
| Conocer el modelo de datos (capas 1 a 3) | [ecosistema-rappi.md §3](ecosistema-rappi.md#3-modelo-de-datos-del-ecosistema-propuesta) | 5 min |
| Usar desde otra herramienta lo que la base le suma al catálogo (atributos, marcas, grafo, segmentos y el motor multivertical) | [capa-de-datos.md](capa-de-datos.md) | 8 min |
| Conocer la capa de IA, su API y cómo se evalúa | [rappi-ia/README.md](../rappi-ia/README.md) | 10 min |
| Usar o modificar el scraper | [rappi-scraper/README.md](../rappi-scraper/README.md) | 10 min |
| Activar a Jev (opcional y apagado: etiqueta categorías y juzga la búsqueda) | [jev.md](jev.md) | 5 min |

### Diseños

Las especificaciones con que se construyeron las piezas grandes. Cada una dice al principio qué cambió después; lo que rige hoy está en [decisiones.md](decisiones.md) y en los documentos de arriba.

| Diseño | Fecha | Qué cubre |
|---|---|---|
| [Capa de perfiles](diseno/2026-10-06-capa-perfiles-design.md) | 06-10-2026 | Atributos, medidas, marcas, producto canónico, grafo de conocimiento y segmentos (migraciones 022 a 026) |
| [MVP integrado](diseno/2026-10-10-mvp-integrado-design.md) | 10-10-2026 | La app conectada a la API: catálogo real, buscador y ofertas de Mochi sobre el RAG, panel y Jev, en 7 etapas |
| [Perfiles de gusto](diseno/2026-10-14-perfiles-de-gusto-design.md) | 14-10-2026 | Escaleras de verticales por gusto (el sushi como narrativa), en datos |
| [Motor multivertical y Home dinámica](diseno/2026-10-16-motor-multivertical-design.md) | 16-10-2026 | Afinidad, transiciones, combinaciones, compra cruzada, tendencias y recompra (migración 036), con la tabla de Rappi completa |

Las migraciones 022 a 026, 036 y 037 citan en su primera línea la carpeta anterior de estos diseños: los archivos son los mismos de [diseno/](diseno/), y lo de la escalera fina (037) está en [capa-de-datos.md](capa-de-datos.md#la-escalera-fina).

### Diagramas y mapas

GitHub muestra las imágenes; las versiones interactivas (HTML) hay que descargarlas y abrirlas en el navegador.

| Qué | Qué muestra | Imagen | Interactivo |
|---|---|---|---|
| Motor multivertical | De las señales y pedidos de la persona, y de la tabla de Rappi, a la Home dinámica y las ofertas de Mochi | [motor-flujo.png](diagramas/motor-flujo.png) | [motor-flujo.html](diagramas/motor-flujo.html) |
| Flujo de datos | Las etapas de punta a punta: descarga → Postgres → IA offline → consulta → prototipo y panel | [rag-datos.png](diagramas/rag-datos.png) | [rag-datos.html](diagramas/rag-datos.html) |
| Arquitectura de la IA | Catálogo y agente Mochi por carriles: datos offline, consulta online y entre verticales | [arquitectura-ia.png](diagramas/arquitectura-ia.png) | [arquitectura-ia.html](diagramas/arquitectura-ia.html) |
| Scraper | Cómo `rappi refresh` descubre, descarga y guarda el catálogo | [scraper-flujo.png](diagramas/scraper-flujo.png) | [scraper-flujo.html](diagramas/scraper-flujo.html) |
| Despliegue | El servidor: Caddy con la puerta, la API, Postgres, `migrate` y los trabajos con sus respaldos | [despliegue.png](diagramas/despliegue.png) | [despliegue.html](diagramas/despliegue.html) |
| Mapa multivertical | Qué productos y conceptos comparten las verticales, con complementos, sustitutos y «nunca junto»; se regenera con `rappi-ia multivertical` | — | [mapa-multivertical.html](mapas/mapa-multivertical.html) |
| Mapa de conceptos | Cada concepto junto a la vertical donde es más típico (la regla de Mochi) | [mapa-conceptos.jpg](mapas/mapa-conceptos.jpg) | — |

Las fuentes JSON de los diagramas están en [diagramas-fuente/](diagramas-fuente/). El HTML y el PNG se generaron a partir de ellas con Archify, una herramienta de diagramas que no es parte del repositorio.

## 3. Resultados

| Si quieres… | Lee |
|---|---|
| Las cifras vigentes, con qué tipo de dato es cada una | [README.md#resultados](../README.md#resultados) |
| La evaluación de la búsqueda vigente (set del 22-10-2026: nDCG@10 y «sin resultado») | [resultados/busqueda-2026-10-22.md](resultados/busqueda-2026-10-22.md) |
| La corrección de errores de tipeo (24-10-2026) | [resultados/busqueda-2026-10-24.md](resultados/busqueda-2026-10-24.md) |
| Los reportes anteriores de la búsqueda, uno por fecha (con otros sets: no se comparan con los de arriba) | [resultados/](resultados/) (`busqueda-2026-09-30.md` a `busqueda-2026-10-06.md`) |
| La evaluación del motor multivertical sobre datos simulados (16-10-2026) | [resultados/motor-2026-10-16.md](resultados/motor-2026-10-16.md) |
| Los datos simulados recalibrados a la mezcla de la tabla de Rappi: antes y después (17-10-2026) | [resultados/simulados-2026-10-17.md](resultados/simulados-2026-10-17.md) |
| La revisión (QA) de las ofertas del motor sobre el catálogo real, en solo lectura (16-10-2026) | [resultados/qa-motor-2026-10-16.md](resultados/qa-motor-2026-10-16.md) |
| La precisión medida de conceptos, atributos y marcas | [resultados/capas-precision-2026-10-06.md](resultados/capas-precision-2026-10-06.md) y [la muestra nueva](resultados/capas-precision-2026-10-06-nueva-muestra.md) |

## 4. Operación

| Si quieres… | Lee | Tiempo |
|---|---|---|
| Instalar el proyecto, cargar la base y dejarlo actualizándose cada semana | [instalacion.md](instalacion.md) | 10 min de lectura |
| Levantar el MVP (`make mvp`), probarlo (`make mvp-check`) y qué hacer con «Sin conexión con Mochi» | [instalacion.md §5](instalacion.md#5-el-mvp) | 5 min |
| Desplegar el MVP en un servidor (Docker Compose, Caddy con TLS y puerta, respaldos con restic) | [despliegue.md](despliegue.md) | 20 min |
| Consultar la base con SQL | [sql/README.md](sql/README.md) y [consultas.sql](sql/consultas.sql) | 5 min |
| Probar a Mochi (API) como usuario y dejar cada fallo como test | [pruebas-de-usuario.md](pruebas-de-usuario.md) | 3 min |
| Usar el panel de negocio (parte del MVP, para la gerencia y RappiAds: 3 vistas alrededor de 4 preguntas) | [dashboard-empresa/README.md](../dashboard-empresa/README.md) | 5 min |
| Contribuir: cómo correr los tests, convenciones y commits | [CONTRIBUTING.md](../CONTRIBUTING.md) y las convenciones del repositorio en [CLAUDE.md](../CLAUDE.md) | 10 min |

### Reportes generados (fuera de git)

| Reporte | Dónde | Cómo se genera |
|---|---|---|
| Evaluación del motor multivertical (uno por fuente) | `rappi-ia/data/eval/motor-{fuente}.md` | `make motor` en `rappi-ia/`. La copia versionada está en [resultados/](resultados/) |
| Evaluación de la búsqueda | `rappi-ia/data/eval/busqueda.md` | `make eval` en `rappi-ia/` (propone τ en el reporte; `make eval GUARDAR_TAU=1` lo guarda en `eval/thresholds.json`). La copia versionada está en [resultados/](resultados/) |
| Piloto de Jev (si se corrió) | `rappi-ia/data/eval/jev-piloto.md` | `rappi-ia jev-piloto`, con la clave y las planillas juzgadas (ver [jev.md](jev.md)) |
| Calidad de cada corrida del scraper | `rappi-scraper/data/reports/` | Al terminar cada corrida, o con `rappi report` |
| Logs de las corridas | `rappi-scraper/data/logs/` y `rappi-ia/data/logs/` | Automático |

## 5. Documentos históricos

Reflejan el estado a su fecha y no se actualizan con cada corrida.

| Documento | Fecha | Qué conserva |
|---|---|---|
| [historial/decisiones-reemplazadas.md](historial/decisiones-reemplazadas.md) | 26-09 al 24-10-2026 | Las decisiones que ya no rigen (los modos anteriores del prototipo, el pasaporte y el juego de verticales, el chat con voz y foto), cada una con la que la reemplazó |
| [ecosistema-rappi.md](ecosistema-rappi.md) §1 y §2 | Investigación con fuentes públicas al 26-09-2026 | Los servicios de Rappi en Chile y cómo modelan sus datos otras super-apps comparables. El modelo de datos (§3) sigue vigente |

Bigotes es el nombre anterior de Mochi (hasta el 09-10-2026); los documentos fechados conservan el nombre de su fecha.
