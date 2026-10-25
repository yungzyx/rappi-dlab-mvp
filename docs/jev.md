# Jev en el proceso semanal

Guía para activar a Jev, el modelo «System One» de [TypeSafe](https://typesafe.ai) que da juicios tipados con probabilidad. Está construido y **apagado**: nada cambia hasta que pongas una clave, juzgues dos planillas y confirmes un piloto. Decisiones y motivos: [decisiones.md](decisiones.md#búsqueda-e-ia) (fila del 11-10-2026).

## Qué es y qué hace

Jev es **opcional y fuera de línea**. Solo trabaja dentro de `make post-refresh`, una vez por semana; nunca corre en la API ni reordena resultados en vivo. Hace dos cosas:

| Rol | Qué hace | Dónde se ve |
|---|---|---|
| **Etiquetar categorías** | Propone el concepto de las categorías nuevas del catálogo (las que ningún mapeo revisado cubre). Si está muy seguro lo aplica (`category_map` con método `jev`); si duda, la deja en una cola de revisión; si dice «ninguno» o la categoría mezcla cosas, no hace nada. Un concepto sensible o +18 nunca se asigna solo a una categoría cuyo resto dice lo contrario: va a revisión. | `make jev-categorias`, antes de `make concepts`; cola en `data/concepts/revision-jev.csv` |
| **Juzgar la búsqueda** | Suma un tercer juez (junto al juez por concepto y las personas) en el reporte `make eval`: dice si cada resultado sirve para la consulta. Sus juicios se guardan en `eval_judgments` con la versión del modelo: la segunda corrida no vuelve a preguntar lo mismo. | `data/eval/busqueda.md` |

## Qué datos salen

Solo datos públicos del catálogo y el set de evaluación:

- nombres de categorías y 8 nombres de producto de ejemplo por categoría;
- las consultas de `src/rappi_ia/eval/queries.json` y los nombres de lo que la búsqueda devolvió.

**Nunca** salen búsquedas, eventos, pedidos ni perfiles de personas. Sin `TYPESAFE_API_KEY` no se llama a nadie.

## Costo

Centavos de dólar por corrida. TypeSafe cobra por tokens de entrada (`JEV_PRICE_PER_MTOK_INPUT` en `rappi-ia/.env.example` guarda el precio con que el piloto estima el costo; confírmalo en tu cuenta). Cada corrida tiene un tope de llamadas, `JEV_MAX_REQUESTS` (3000 por defecto, los reintentos cuentan): si se llega, el resto queda para la semana siguiente y el comando lo avisa. La primera corrida del juez es la más cara, porque la caché empieza vacía.

## Cómo activarlo, paso a paso

1. **Clave.** Crea una cuenta en TypeSafe (typesafe.ai) y agrega a `rappi-ia/.env`:

   ```
   TYPESAFE_API_KEY=...
   ```

   La clave no se sube a git. `JEV_MODEL` (por defecto `jev-1.13.0`), `JEV_MAX_REQUESTS` y `JEV_PARALLEL` son opcionales.

2. **Planillas.** Desde `rappi-ia/`:

   ```bash
   .venv/bin/rappi-ia jev-planillas
   ```

   Deja en `rappi-ia/data/eval/` dos CSV, `planilla-busqueda.csv` (200 pares consulta-producto: «sirve», «a medias» o «no sirve») y `planilla-categorias.csv` (100 categorías: el concepto correcto o «ninguno»), y un `LEEME-planillas.md` que explica cómo llenarlas. Se abren en Numbers o Excel, se llena una sola columna de cada una y se guardan como CSV UTF-8 con el mismo nombre. Se puede juzgar de a ratos. Los textos quedan fuera de git; solo los ids van versionados. Con `.venv/bin/rappi-ia eval-human` ves cuánto coincide el juez por concepto con tu juicio.

3. **Piloto.** Con las dos planillas juzgadas (basta con el 90 % de cada una):

   ```bash
   .venv/bin/rappi-ia jev-piloto
   ```

   Mide a Jev contra tu juicio y escribe `rappi-ia/data/eval/jev-piloto.md`, que empieza con el resultado en palabras y trae un glosario. Si falta algo (la clave, una planilla), dice exactamente qué. Para etiquetar categorías, Jev debe acertar al menos el 90 % de lo que mapea, cubrir la mitad de las categorías sin mapear, coincidir en el 90 % del control y no mapear ni un concepto sensible o +18 a uno que no lo es. Para juzgar la búsqueda, su κ contra las personas debe ser al menos 0,6 y superar al del juez por concepto. Cada rol se adopta por separado; si ninguno pasa, no se propone nada.

4. **Adopción.** Si el piloto pasa, deja `rappi-ia/src/rappi_ia/eval/jev-adopcion.propuesta.json`. Para adoptar, renómbralo a `jev-adopcion.json` y haz commit. Es la única forma de activar a Jev: no se activa solo.

5. **Desde entonces**, `make post-refresh` (y la tarea semanal) usa a Jev: `make jev-categorias` va antes de `make concepts` y `make eval` suma el juez. Para revisar lo que hizo, `.venv/bin/rappi-ia map-categories --jev --exportar` lista sus mapeos y la cola de revisión en un CSV; cada fila que quieras conservar se pasa a «curado» y se copia a `category_map.csv`.

## Qué pasa si falta algo

Los dos pasos terminan siempre con código 0 y dicen en una línea por qué no hicieron nada:

- sin `TYPESAFE_API_KEY`;
- sin `jev-adopcion.json`, o con el rol en `false`;
- con una adopción hecha para otra versión del modelo (hay que repetir el piloto si cambias `JEV_MODEL`);
- con la API caída (401, 429, 529, tiempo agotado): lo que Jev no contestó se omite, no se escribe nada a medias y la evaluación sigue como siempre.

## Cómo apagarlo

Cualquiera de estas basta:

- en `jev-adopcion.json`, poner `"categorias": false` y/o `"juez": false` (o borrar el archivo);
- quitar `TYPESAFE_API_KEY` de `rappi-ia/.env`.

Lo ya aplicado sigue en la base (los mapeos con método `jev` y los juicios en `eval_judgments`, con su versión de modelo). `make concepts` conserva los mapeos de Jev; para quitar alguno, corrige la categoría en `category_map.csv` como «curado» o «ninguno».
