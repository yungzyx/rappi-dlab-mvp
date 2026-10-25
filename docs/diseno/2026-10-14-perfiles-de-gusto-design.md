# Perfiles de gusto en el backend (diseño)

Fecha: 14-10-2026. Construido en el backend el 14-10-2026; desde el 17-10-2026 el buscador con Mochi muestra el perfil principal y su escalera (`prototipo-app/src/components/assistant/TasteProfile.jsx`). Cómo funciona hoy, en [diseno-ia.md](../diseno-ia.md) y [decisiones.md](../decisiones.md).

> **Lo que cambió al construirlo** (el texto de abajo es el diseño original):
> - Un peldaño sirve con 1 a 4 productos, no 2 a 4: la chocolatería asiática solo tiene un matcha. Con menos de 2 peldaños sigue sin haber escalera.
> - Cada peldaño puede llevar `evitar`, además de `palabras`: nombres que dicen la palabra sin ser lo que promete el peldaño («Limpia Ollas En Pasta», un juguete «Cafetera»). Las palabras calzan al comienzo de una palabra del nombre.
> - Mascotas es un perfil de perro: su peldaño del súper no trae `alimento-gato`.
> - Dos ajustes de segmentos y conceptos: el peldaño de chocolaterías del asiático suma `te` («Lindor Matcha» viene en la categoría «Tés») y el italiano suma el segmento `pizzero`.
> - La guardia de alcohol mira también el nombre del producto o del plato, porque la marca de la tienda puede estar mal («Soju Uva Verde 13» salía como fruta).
> - `mochi` suelto no es palabra clave de producto, porque es el nombre del agente.
> - El texto del momento dice «Como te gusta {gusto}…» con el campo opcional `gusto` de cada perfil (sin él, nombra al perfil). La `basis` de una oferta sin persona trae `{kind: "perfil", source: "contexto"}`; con persona, sus segmentos y lo que pidió y buscó, en la forma de `offers/personal.py`.
> - La consulta de un peldaño sin `palabras` son los nombres de sus conceptos y sus primeras palabras clave, para que la búsqueda por texto sirva aun sin embeddings. Una escalera no repite un nombre entre peldaños, no muestra tiendas cuyo nombre o marca dice «licor» o «botillería» («Turbo Licores») y en restaurantes pone un plato por cadena.

## Punto de partida (13-10)
- **Narrativa:** la demo deja de partir con «armar carrete» y parte con algo simple, el sushi. Cuando la persona pide mucho sushi o comida china, Mochi arma un perfil «🥢 Amante de lo asiático» y, con él, ofrece en otras verticales. El sushi es el principal. Café, italiano y mascotas son perfiles adicionales. Carrete se menciona también, como secundario y sin alcohol.
- **Enfoque A:** perfiles de gusto como capa propia, definidos en datos. Cada uno tiene una escalera de verticales que Mochi ofrece de a un peldaño, siempre con su «¿Por qué?» y con «Olvidar». Es un mecanismo general: el asiático va primero; agregar otro perfil es escribir datos, no código.
- **Parte 1 (datos):**
  - 3 conceptos nuevos: `despensa-asiatica`, `snacks-asiaticos` y `bebidas-asiaticas`, con reglas de nombre y `avoid`.
  - `perfiles.toml`.
  - Destinos curados, rotulados «Idea para RappiTravel», sin precios ni fechas, con 2 datos verificables con fuente.
  - Aristas nuevas en el grafo: sushi → despensa-asiatica, sushi → bebidas-asiaticas y asiatica → snacks-asiaticos.
- **Licores:** se mantiene la regla. Mochi no ofrece alcohol por iniciativa propia; si la persona lo busca, aparece con el aviso +18. Lo mismo vale para Farmacia, bebé, salud y lo sensible (`offers/guards.py`).
- **Demo previa:** una maqueta en HTML (`prototipo-sushi.html`, fuera del repositorio). Esta especificación lleva esa demo a la API de verdad, sin tocar la app.

## Alcance
**Dentro:**
- datos (conceptos, perfiles, destinos, aristas);
- motor (qué perfiles tiene una persona y la escalera de cada uno);
- API (`GET /profile/{user_id}/gustos` y el momento `perfil` en `/agent/offer`);
- persona simulada «asiático»;
- textos del backend que hoy empujan «carrete» primero (la ayuda del agente);
- documentación y contrato (fixtures).

**Fuera:**
- la UI de la app, porque la demo ya existía y llevarla al MVP era otra etapa (se hizo el 17-10-2026);
- volver a etiquetar la base real (`rappi-ia concepts` y `make layers` después de integrar el cambio);
- el panel. Si sobra tiempo: conteo por perfil en `/analytics`, rotulado como uso del MVP.

## Datos
- **`concepts/taxonomy.toml`:**
  - Los 3 conceptos van en grupos que ya existen: `despensa-asiatica` en `despensa`, `snacks-asiaticos` en `snacks` y `bebidas-asiaticas` en `bebidas`. Ninguno es sensible ni +18.
  - Palabras clave basadas en el catálogo real:
    - soya o soja, teriyaki, nori, sésamo, mirin, arroz para sushi, fideos de arroz, kimchi, gochujang, panko, jengibre para sushi, palitos para sushi;
    - ramen instantáneo, Buldak, Pepero, Pocky y mochi;
    - matcha, bubble tea y té con leche de estilo asiático.
  - `avoid` deja fuera shampoo, vapeo y útiles escolares (Staedtler «Noris»).
  - Se sube la `version`.
- **`concepts/complements.toml`:** las 3 aristas nuevas.
- **`offers/perfiles.toml` (nuevo):** un `[[perfil]]` por gusto, con estos campos:
  - `id`, `nombre`, `emoji`;
  - `principal` (true solo en el asiático);
  - `segmentos`: ids de `segments.toml` que lo activan;
  - `nivel_minimo` (`medio`);
  - `escalera`: una lista de peldaños `{vertical, conceptos, palabras?, texto}`;
  - `viaje`: el id de un destino, o nada.
  
  Los perfiles y sus escaleras son estos:

  | Perfil | Escalera | Viaje |
  |---|---|---|
  | asiatico | restaurantes (sushi, asiatica) → turbo (despensa-asiatica) → conveniencia (snacks-asiaticos, bebidas-asiaticas) → supermercado (despensa-asiatica, bebidas-asiaticas) → chocolateria (chocolates, palabras «matcha») | japon |
  | cafe | supermercado (cafe) → turbo (cafe) → conveniencia (cafe) → mall (electrohogar, cocina-menaje, palabras «cafetera», «molinillo», «prensa francesa») → chocolateria (chocolates, palabras «café») | colombia |
  | italiano | supermercado (pastas, quesos, salsas, aceites-condimentos) → conveniencia (pastas, salsas) → turbo (quesos, pastas) → mall (cocina-menaje, palabras «pizza», «rallador», «pasta») → chocolateria (postres, pasteleria, palabras «tiramis», «cannoli», «amaretti», «panettone») | italia |
  | mascotas | conveniencia (alimento-perro) → turbo (alimento-perro) → mall (accesorios-mascota) → supermercado (alimento-perro, alimento-gato) | ninguno |
  | carrete | turbo (hielo, gaseosas) → conveniencia (snacks-salados) → supermercado (frutos-secos, snacks-salados, salsas) → mall (decoracion, palabras «vaso», «guirnalda», «globo», «cotillón») → restaurantes (pizza, picoteo) | ninguno (sin alcohol) |

  Los ids de segmento se eligen de `segments.toml` (`sushi`, `asiatica`, `japonesa` y `china` para el asiático; los de café, italiana o pastas, mascotas y `fiestero` para los demás). El cargador valida que existan.
- **`offers/destinos.toml` (nuevo):** japon, colombia e italia, cada uno con `nombre`, `texto` (la pregunta, por ejemplo «¿Y si un día vas a Japón?») y 2 `hechos {texto, fuente, url}`. Son los mismos de la demo, ya verificados:
  - washoku, UNESCO 2013;
  - Fushimi Inari (Wikipedia);
  - Paisaje Cultural Cafetero, UNESCO 2011 (decisión 35 COM 8B.43);
  - 47 municipios (Wikipedia);
  - el arte del pizzaiolo napolitano, UNESCO 2017;
  - la margarita de 1889 (Wikipedia).

## Motor (`offers/profiles.py`, nuevo)
- **`load_profiles()` y `load_destinations()`** (en caché).
  - Validan que cada concepto exista en la taxonomía, que cada vertical sea una de las 8 y que cada segmento exista.
  - Ningún peldaño puede tener un concepto que `is_offerable` rechace. Por eso carrete nunca nombra alcohol.
- **`active_profiles(conn, user_id) -> list[ActiveProfile]`:**
  - Solo para usuarios `source='prototype'`, igual que `personal.py`.
  - Toma `user_segments` de la persona y queda con los perfiles que tienen algún segmento en un nivel igual o mayor al mínimo.
  - El nivel es el máximo; el puntaje, la suma.
  - `por_que` se arma desde los pedidos y búsquedas recientes que cuentan, contados por concepto en la ventana de los segmentos (120 días) desde `app_order_lines` y `app_events`. Por ejemplo: «Pediste 🍣 sushi 2 veces y 🥡 comida asiática 1 vez».
  - `basis` usa el mismo formato que `reason.basis`.
  - Orden: primero el principal, luego por puntaje.
- **`ladder(conn, embedder, profile, exclude_stores=None) -> list[Step]`:**
  - Por peldaño: `search_products(conn, vertical, <consulta del peldaño>, conceptos, embedder, k=…, offer=True)`, filtrado por concepto y, si el peldaño las tiene, por `palabras` en el nombre.
  - Quedan 2 a 4 productos por peldaño. El peldaño de restaurantes excluye los locales donde la persona ya pidió.
  - Se salta un peldaño sin productos. Si quedan menos de 2 peldaños, no hay oferta.
  - Pasan todas las guardias de oferta (`offer=True`: nada +18, ni tiendas Farmacia, Sex shop o Smoking shop).

## API
- **`GET /profile/{user_id}/gustos`:**
  - Con `owner_in_path` (identidad firmada). Devuelve `{"perfiles": [{id, nombre, emoji, nivel, principal, por_que, basis}]}`; la lista va vacía si no hay perfil.
  - «Olvidar» (`DELETE /profile/{user_id}`) ya borra los segmentos, así que el perfil desaparece solo.
- **`POST /agent/offer` con `moment: "perfil"`:**
  - `context: {"perfil": <id> | null}`.
  - Con `user_id` (dueño validado) y sin `perfil`, usa el primer perfil activo. Con `perfil` explícito y sin `user_id`, devuelve la escalera sin «por qué» personal: la demo y el contrato la usan.
  - Respuesta: `{moment, text, perfil{id, nombre, emoji, nivel?, por_que?}, escalera: [{vertical, prototype_vertical, texto, products[]}], viaje: {id, nombre, texto, hechos[], etiqueta: "Idea para RappiTravel", route: ["travel"]} | null, reason{text, basis}, actions[]}`.
  - Devuelve 204 si no hay perfil o escalera, igual que los otros momentos.
- Ejemplos nuevos en `prototipo-app/src/api/fixtures/` vía `make contract` (`profile-gustos.json` y `agent-offer-perfil.json`).

## Simulados y textos
- **`events/synth.py`:** nueva persona `asiatico` (sushi, asiatica, despensa-asiatica, bebidas-asiaticas en Restaurantes, Súper, Turbo y Express). Su participación sale de `carrete`, que baja.
- **Ayuda del agente:** la acción «🎉 Arma un carrete» pasa a «🍣 Algo de sushi» (consulta «sushi»). Carrete queda más abajo en la lista, no se borra. `compose.py` usa ejemplos de sushi. La ocasión `carrete` sigue existiendo.
- **Documentación:**
  - una línea en las convenciones del repositorio (`CLAUDE.md`);
  - una sección en `docs/diseno-ia.md`;
  - una fila en `docs/decisiones.md`;
  - `rappi-ia concepts` y `make layers` en la base real.

## Pruebas
- **Cargador:**
  - los ids existen;
  - carrete sin alcohol;
  - ningún concepto de peldaño queda bloqueado por las guardias;
  - cada viaje tiene 2 hechos con url.
- **Matcher:** los conceptos nuevos calzan con nombres reales y no con shampoo, vape ni «Noris».
- **Motor** (`rappi_ia_test`, `seed-demo` ampliado con productos asiáticos y un usuario `prototype` con segmentos):
  - un usuario con el segmento `sushi` en nivel medio tiene el perfil asiático;
  - sin segmentos, no hay perfil;
  - «Olvidar» lo quita;
  - la escalera salta los peldaños vacíos;
  - restaurantes excluye locales ya pedidos;
  - ningún producto +18 en ningún perfil.
- **API:**
  - 403 con el id de otra persona;
  - 401 sin token;
  - 204 sin perfil;
  - el momento `perfil` anónimo con `perfil` explícito;
  - contrato.
- **Generales:** `make mvp-check` sigue en 7 de 7 (no se agrega ni quita ningún chequeo).
