# Capa de perfiles: atributos, medidas, marcas, producto canónico, grafo y segmentos

> Especificación · 06-10-2026 · Construida en 5 etapas el 06-10-2026; cómo se usa hoy, en [capa-de-datos.md](../capa-de-datos.md).
> Contexto: [diseno-ia.md](../diseno-ia.md) (capas 1 y 2) · [decisiones.md](../decisiones.md)

## 1. Para qué

Hoy la base sabe **qué es** cada ítem (capa 2: un concepto por producto o plato) y **qué le interesa** a cada usuario
(perfil por concepto con decaimiento). No sabe **cómo es** un producto (sin gluten, familiar, premium), **cuánto trae**
de forma comparable, **de qué marca** es de verdad, si es **el mismo** producto en otra vertical, cómo se **relacionan**
las cosas más allá de «complementa», ni **qué tipo de cliente** es cada persona.

Esta capa agrega esos datos como **cimiento reutilizable**: el chat, la búsqueda, un recomendador, el panel o una
herramienta externa (BI, dbt, Neo4j) los leen sin reimplementar lógica. Cambiar cómo los usa el chat queda **fuera de
alcance** (ver §9).

### Criterios de éxito

1. Todo ítem del catálogo tiene medidas normalizadas, marca canónica (si tiene marca) y sus atributos con procedencia.
2. Todo usuario con actividad tiene sus segmentos con nivel, evidencia y fecha; la historia semanal permite tendencias.
3. Agregar un atributo, un segmento o un tipo de relación nuevo es **una fila en un TOML**, sin migración ni código.
4. Las herramientas externas leen el esquema `capa`, documentado, que no cambia de forma aunque cambien las tablas.
5. Cada corrida queda en `layer_runs`; correr dos veces deja lo mismo.
6. Lo sensible queda marcado y protegido en la base (§7), no depende de que cada consumidor se acuerde.

## 2. Principios

1. **Vocabularios en tablas.** Cada atributo, segmento y relación es una fila con id estable (`sin-gluten`), nombre,
   familia, sensibilidad y descripción. El TOML es la fuente; el comando la siembra en la base.
2. **Procedencia en cada fila.** `source` (`rappi` · `regla` · `aprendido` · `curado`), `confidence`, `evidence`
   (texto o JSON corto: la palabra que calzó, el campo de Rappi, los eventos que cuentan) y `rules_version`.
3. **Recalculable e idempotente.** Cada comando reemplaza lo que calcula su capa en una transacción y anota la corrida.
   Lo `curado` a mano nunca lo pisa un cálculo.
4. **Contrato estable.** Vistas en el esquema `capa`, con `COMMENT ON` en tablas y columnas; las internas pueden cambiar.
5. **Claves uniformes.** Ítem = `(entity_type, entity_id)` como en `item_concepts`; usuario = `user_id`; nodos del
   grafo = `(kind, id)`.
6. **Sin modelos de lenguaje en el cálculo.** Reglas y estadística reproducibles; los modelos siguen solo en la búsqueda.

## 3. Modelo de datos (migración 022 en adelante)

### 3.1 Linaje

| Tabla | Columnas clave |
|---|---|
| `layer_runs` | `run_id`, `layer` (`attributes`·`measures`·`brands`·`canonical`·`relations`·`segments`), `rules_version`, `started_at`, `finished_at`, `status`, `counts jsonb` |

### 3.2 Atributos de ítem

| Tabla | Columnas |
|---|---|
| `attribute_defs` | `attribute_id` (pk), `name`, `family`, `applies_to` (`catalog_item`·`menu_item`·ambos), `value_type` (`flag`·`text`), `description`, `rules_version` |
| `item_attributes` | `entity_type`, `entity_id`, `attribute_id`, `value` (null en los `flag`), `source`, `confidence`, `evidence`, `rules_version`, `run_id`; pk `(entity_type, entity_id, attribute_id)` |

Fuentes, en orden de confianza (gana la primera que responde; las demás no se guardan):

1. **Rappi** (`catalog_items.attributes`): `gluten_free`, `sugar_free`, `vegan`, `lactose_free`, `organic`, `is_light`,
   `salt_free`, `high_protein`, `is_zero_alcohol`, `cruelty_free`, `parabens_free`, `is_crafted_beer`, `gender`,
   `life_stage_human`, `dog_age`, `cat_age`, `pack_size`… (mapeo en el TOML). `confidence` 0,95. Un `false` explícito
   de Rappi **bloquea** la regla de texto para ese atributo.
2. **Regla de texto** sobre nombre + categoría + descripción hasta las advertencias del prospecto (la misma frontera de
   `tools._treats`): frases positivas («sin gluten», «libre de gluten», «gluten free») y **negaciones que anulan**
   («contiene gluten», «puede contener trazas»). `confidence` 0,8.
3. **Derivada** (estadística): `economico` (precio ≤ percentil 25 de su concepto en su vertical), `con-descuento`
   (precio < precio real en la última foto). `confidence` 0,9. Se recalcula con cada descarga.

### 3.3 Medidas

| Tabla | Columnas |
|---|---|
| `item_measures` | `entity_type`, `entity_id`, `quantity` (por unidad), `unit` (`g`·`ml`·`und`·`cm`), `pack` (≥ 1), `total` (= quantity × pack, en la unidad base), `size_label` (`talla g`, `familiar`, `para 2`…), `source`, `evidence`, `run_id` |

Base: `catalog_items.quantity`/`unit_type` (normalizados: `gr`→`g`, `kg`→`g`×1000, `cc`→`ml`, `l`→`ml`×1000), corregidos
por el nombre cuando se contradicen («Coca-Cola 3 L» con `1 und`). `pack` sale de `pack_size` o del nombre («x6»,
«six pack», «pack 4»). Platos: `size_label` y personas («para 2», «familiar», «XL») desde el nombre.
Vista `capa.item_unit_prices`: precio vigente ÷ `total` → `$/kg`, `$/L`, `$/und`.

### 3.4 Marcas

| Tabla | Columnas |
|---|---|
| `product_brands` | `brand_key` (pk, slug: `coca-cola`), `name` (la escritura más común), `is_store_brand` (marca propia: Líder, Great Value, Nuestra Cocina, Cuisine & Co…), `curated` |
| `brand_aliases` | `alias` (normalizado, pk), `brand_key`, `source` (`rappi`·`curado`), `items` |
| `item_brands` | `entity_type`, `entity_id`, `brand_key`, `source` (`rappi` `trademark` · `regla` sobre el nombre · `cadena` para platos), `run_id` |

Agrupación: `normalize(trademark)` sin signos ni sufijos societarios («S.A.», «Ltda»); escrituras que solo difieren en
espacios o guiones se unen («coca cola» = «cocacola» = «coca-cola»). Los alias curados mandan (TOML `brands.toml`).
Los platos toman la cadena del local (`stores.brand_id`) como marca.

### 3.5 Producto canónico

| Tabla | Columnas |
|---|---|
| `canonical_products` | `canonical_id` (pk), `brand_key`, `name_key` (nombre normalizado sin marca, tamaño ni pack), `total`, `unit`, `label` |
| `item_canonical` | `master_product_id` (pk), `canonical_id`, `method` (`exacto`·`regla`·`curado`), `confidence`, `run_id` |

Clave: `(brand_key, name_key, total, unit)`. Une productos con distinto `master_product_id` que son el mismo (pasa
entre cadenas); nunca une tamaños distintos ni marcas distintas. Ante la duda **no une** (unir mal es peor que no unir).
De aquí sale «el mismo producto en N verticales» sin la inflación de las tiendas con doble etiqueta.

### 3.6 Grafo de conocimiento

| Tabla | Columnas |
|---|---|
| `relation_defs` | `relation` (pk), `name`, `from_kinds`, `to_kinds`, `symmetric`, `description` |
| `knowledge_edges` | `from_kind`, `from_id`, `relation`, `to_kind`, `to_id`, `weight` (0 a 1), `method` (`curado`·`coocurrencia`·`derivado`; `coocurrencia` es el nombre que ya usa la base para lo aprendido de pedidos), `data_source` (`curado`·`synthetic`·`prototype`·`catalogo`), `support`, `evidence`, `run_id`; pk `(from_kind, from_id, relation, to_kind, to_id, method, data_source)` |

Tipos de nodo: `concept`, `group`, `attribute`, `segment`, `brand`, `vertical`, `occasion`, `service`, `canonical`.

`concept_edges` se migra a `knowledge_edges` (`relation = 'complementa'`) y queda como **vista de compatibilidad** con
sus columnas actuales, para que quienes **leen** (`suggest_complement`, el panel, `exportar_red.py`) no cambien.
Quienes **escriben** (la siembra de `complements.toml` y `learn_edges`) pasan a escribir en `knowledge_edges`: una
vista no recibe inserciones sin reglas, y esconderlas sería peor que cambiar dos funciones.

### 3.7 Segmentos

| Tabla | Columnas |
|---|---|
| `segment_defs` | `segment_id` (pk), `name`, `family`, `sensitive`, `description`, `rule jsonb` (la regla sembrada), `rules_version` |
| `user_segments` | `user_id`, `segment_id`, `score`, `level` (`bajo`·`medio`·`alto`), `signals` (señales distintas que cuentan), `evidence jsonb` (top conceptos/atributos/días), `first_seen`, `last_signal`, `source` (`regla`·`curado`), `run_id`; pk `(user_id, segment_id)` |
| `user_segment_history` | `week` (lunes), `user_id`, `segment_id`, `score`, `level`; pk `(week, user_id, segment_id)` |

`app_users.segment` (la persona del simulador) no cambia de significado; queda como dato de origen del simulado.

## 4. Catálogos

Los ids son slugs estables; los nombres, en español. **S** = sensible.

### 4.1 Atributos (≈ 75)

| Familia | Atributos |
|---|---|
| `dieta` | sin-gluten · sin-lactosa · sin-azucar · vegano · vegetariano · pescetariano (platos) · keto · alto-proteina · integral · alto-fibra · bajo-sodio · light · organico · sin-cafeina · sin-alcohol · natural (sin preservantes ni colorantes) · kosher · halal |
| `alergenos` | sin-mani · sin-frutos-secos · sin-huevo · sin-soya · sin-mariscos |
| `publico` | bebe (0 a 3 años) · ninos · adolescentes · adulto-mayor · embarazo-lactancia · hombre · mujer · perro · gato · otras-mascotas · cachorro · mascota-senior |
| `formato` | familiar · individual · pack · granel · congelado · refrigerado · listo-para-comer · para-preparar · recargable · desechable · lata · vidrio · retornable · tamano-viaje · en-polvo · capsulas · instantaneo |
| `precio` | premium · marca-propia · economico (derivado) · con-descuento (derivado) |
| `origen` | chileno · importado · artesanal · casero (platos) |
| `sustentable` | biodegradable · reciclable · cruelty-free · sin-parabenos · eco |
| `ocasion` | para-regalo · navidad · fiestas-patrias · halloween · san-valentin · cumpleanos |
| `platos` | picante · combo · para-compartir · saludable · frito · a-la-parrilla · al-horno · crudo (sushi, ceviche) · con-acompanamiento · bebida-incluida · desayuno · postre-incluido |

### 4.2 Segmentos (≈ 110)

| Familia | Segmentos |
|---|---|
| `dieta` | compra-sin-gluten **S** · compra-sin-lactosa **S** · compra-sin-azucar **S** · bajo-sodio **S** · alergia-frutos-secos **S** · vegetariano · vegano · pescetariano · keto · fitness · saludable · organico · sin-cafeina · natural |
| `comida` | hamburguesero · pizzero · sushi · asiatica · china · japonesa · thai · india · mexicana · peruana · arabe · italiana · pastas · chilena · empanadas · completos · sandwiches · pollo · parrilla · mariscos · ensaladas · comida-rapida · gourmet · picante · desayuno-brunch · veggie-restaurantes |
| `dulces` | chocolatero · goloso · heladero · pastelero · galletas · snacks-salados · frutos-secos |
| `bebidas` | cafetero · cafe-de-especialidad · tetero · cervecero · cerveza-artesanal · vinero · espumante · whisky · pisco · destilados · cocteles · sin-alcohol · energeticas · gaseosas · jugos · agua |
| `hogar` | mama-papa-bebe **S** · embarazo **S** · familia-con-ninos · familia-con-adolescentes · tiene-perro · tiene-gato · otras-mascotas · mascota-premium · adulto-mayor **S** · vive-solo · pareja · hogar-grande · cocina-en-casa · no-cocina · anfitrion |
| `cuidado` | belleza · maquillaje · dermocosmetica · cuidado-cabello · cuidado-masculino · fragancias · higiene-bebe · salud-sexual **S** · farmacia-frecuente **S** · cuidado-cronico **S** · tabaco **S** · vapeo **S** |
| `intereses` | deportista · gamer · tecnologia · lector · hogar-deco · jardineria · bricolaje · estudiante · oficinista · viajero · regalador · fiestero · aire-libre · arte-manualidades · musica |
| `momentos` | madrugador · almuerzo-oficina · once · nocturno · trasnoche · fin-de-semana · dia-de-pago (fin/inicio de mes) · compra-mensual · reposicion-rapida · impulsivo · recurrente · planificador · celebraciones · temporada-navidad · temporada-fiestas-patrias |
| `valor` | cazaofertas · sensible-al-precio · premium · fiel-a-marca · explorador · marca-propia · gasto-alto · gasto-bajo · ticket-creciente |
| `relacion` | nuevo · activo · leal · en-riesgo · dormido · reactivado · multivertical · una-vertical · alto-abandono · receptivo-a-sugerencias · ignora-sugerencias · usa-chat · usa-voz · usa-foto |
| `servicios` | usa-rappitravel · usa-rappifavor |
| `geografia` | santiago · regiones (por `app_users.city`) |

### 4.3 Relaciones (`relation_defs`)

| Relación | De → a | Método | Para qué |
|---|---|---|---|
| `complementa` | concepto → concepto | curado (`complements.toml`) + aprendido (co-compra) | sugerencia cruzada (ya existe) |
| `co_busqueda` | concepto → concepto | aprendido (misma sesión) | ampliar consultas, panel |
| `sustituye` | concepto ↔ concepto | curado | si no hay aquí, ofrecer el sustituto en otra vertical |
| `es_tipo_de` | concepto → grupo | derivado (taxonomía) | navegar por grupo |
| `de_ocasion` | concepto → ocasión | derivado (taxonomía) | consultas por ocasión |
| `se_vende_en` | concepto → vertical | derivado (`concept_assortment`) | dónde buscar |
| `tiene_atributo` | concepto → atributo | derivado (% de ítems del concepto con el atributo, si ≥ 5 %) | qué conceptos tienen opción sin gluten, vegana… |
| `marca_de` | marca → concepto | derivado (ítems de la marca) | marcas por concepto |
| `afin_a` | segmento → concepto/atributo/vertical | derivado de la regla del segmento | qué mirar primero para cada segmento |
| `equivale` | canónico → vertical | derivado (`item_canonical`) | mismo producto en varias verticales |
| `conflicto` | concepto ↔ concepto / segmento ↔ concepto | curado | nunca sugerir juntos (alcohol con bebé, tabaco con niños) |
| `sinonimo` | término → concepto | derivado (`query_keywords`) | vocabulario de consulta para otras herramientas |

## 5. Reglas de segmento

Cada segmento en `segments.toml` combina piezas genéricas; el motor no conoce segmentos por nombre:

```toml
[[segment]]
id = "compra-sin-gluten"
name = "Compra sin gluten"
family = "dieta"
sensitive = true
description = "Compra o busca productos sin gluten de forma repetida."
signals = { attributes = ["sin-gluten"], query_words = ["celiaco", "sin gluten", "libre de gluten"] }
events = { order_line = 3.0, cart_add = 1.5, search = 1.0, chat = 1.0, product_view = 0.3 }
window_days = 120
half_life_days = 45
min_signals = 3          # eventos distintos que calzan
levels = { bajo = 2.0, medio = 5.0, alto = 10.0 }
share_of = "all"         # opcional: puntaje relativo al total de actividad (para «una-vertical», «premium»)
```

Piezas disponibles: `concepts`, `groups`, `attributes`, `verticals`, `brands`, `occasions`, `services`,
`query_words`, `hours`, `weekdays`, `days_of_month`, `price_percentile` (≤ / ≥), `discount`, `basket_size`
(≥ ítems o monto), `modality` (texto, voz, foto), `from_suggestion`, `exclude` (señales que restan). Los de
`relacion` usan métricas calculadas (días desde el último pedido, verticales distintas, tasa de abandono, aceptación
de sugerencias) declaradas como `metric = "dias_sin_pedido"` con rangos, para no esconder lógica en código.

Puntaje = Σ peso(evento) × decaimiento(edad) sobre los eventos que calzan alguna señal; nivel por umbral; sin
`min_signals` no hay segmento. La evidencia guarda los 3 conceptos/atributos que más aportan y las fechas extremas.
`rappi-ia segments --user <id>` recalcula un usuario al momento (prototipo).

## 6. Cálculo

Comandos de `rappi-ia`, en este orden dentro de `make post-refresh` (después de `concepts`):

1. `measures` → `item_measures`
2. `brands` → `product_brands`, `brand_aliases`, `item_brands`
3. `attributes` → `attribute_defs`, `item_attributes` (usa medidas y marcas para `familiar`, `marca-propia`)
4. `canonical` → `canonical_products`, `item_canonical`
5. `relations` → `relation_defs`, `knowledge_edges` (salvo `curado`, que siembra el TOML)
6. `segments` → `segment_defs`, `user_segments`, `user_segment_history` (foto de la semana)

`make layers` corre los seis. Cada uno: una transacción, `layer_runs` con conteos, idempotente. Se recalcula todo en
cada corrida (≈ 250 mil ítems); si algún día tarda más de 5 minutos, `attributes` pasa a incremental por
`content_hash` de `search_documents`.

Fuera del repo de reglas no hay nada: `attributes.toml`, `brands.toml`, `segments.toml`, `relations.toml` viven junto
a `taxonomy.toml` y llevan `version` (fecha), que se copia a `rules_version`.

**Simulador.** `synth` suma personas que ejerciten los segmentos (sin gluten, vegana, mamá con bebé, dueña de perro,
fitness, oficinista, nocturno, cazaofertas, gamer…) para que el panel y los tests tengan datos; siguen siendo `synthetic`.

## 7. Privacidad y sensibles

- `segment_defs.sensitive` y los nombres por comportamiento («compra sin gluten», nunca «celíaco»).
- Vistas `capa`: los agregados de segmentos sensibles solo muestran grupos con **≥ 5 usuarios**; las filas por usuario
  de segmentos sensibles no se exponen en `capa` (solo en la tabla interna, para el chat de esa persona).
- `forget(user)` borra `user_segments` y `user_segment_history`; `forget(user, concept)` recalcula sus segmentos.
- Nunca se calculan segmentos con eventos de modo «Rappi hoy» (ya no traen concepto) ni se mezclan fuentes
  (`synthetic`, `prototype`) en un mismo cálculo.
- Conflictos (`relation = 'conflicto'`) siembran las prohibiciones que el chat ya respeta (sensibles, edad).

## 8. Calidad y pruebas

- **Unitarias** por regla: frases positivas, negaciones («contiene gluten»), medidas («x6», «1,5 L», «3 L» con `1 und`),
  alias de marca, clave canónica (no une tamaños distintos), motor de segmentos (umbrales, decaimiento, `min_signals`,
  `exclude`, métricas de relación).
- **Integración** contra `rappi_ia_test`: cada comando idempotente, `layer_runs`, vista de compatibilidad
  `concept_edges` igual a antes, `forget` en cascada, k ≥ 5 en `capa`.
- **Reporte** `rappi-ia layer-report` (y en `data/eval/capas.md`): cobertura por atributo y vertical, fuente
  (rappi / regla), medidas inconsistentes, marcas con más alias, canónicos en varias verticales, distribución de
  segmentos. Con una **muestra revisable** de 20 ítems por atributo para estimar precisión a ojo.
- **Base real:** cada etapa termina corriendo su comando en `rappi` y revisando el reporte.

## 9. Fuera de alcance

- Cambiar cómo el chat, la búsqueda o la sugerencia usan esta capa (después, con su propio diseño).
- Segmentos descubiertos por agrupamiento (la tabla ya admite `source` distinto de `regla`).
- Sinónimos aprendidos de consultas reales y popularidad por eventos (con datos simulados no son evidencia).
- Extracción con modelos de lenguaje.

## 10. Etapas

| Etapa | Contenido |
|---|---|
| 1 | Migración 022 (`layer_runs`, `attribute_defs`, `item_attributes`, `item_measures`, esquema `capa`); `measures` y `attributes` (Rappi + reglas + derivados); reporte |
| 2 | Marcas (`product_brands`, `brand_aliases`, `item_brands`) y producto canónico |
| 3 | `knowledge_edges` (migrando `concept_edges` a vista), `relation_defs`, `relations` |
| 4 | Segmentos: `segment_defs`, `user_segments`, historia, motor de reglas, personas nuevas del simulador, `forget` |
| 5 | Vistas `capa.*` completas con `COMMENT ON`, documentación (`docs/capa-de-datos.md`), corrida completa en la base real |
