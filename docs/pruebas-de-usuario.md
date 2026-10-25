# Pruebas como usuario del agente

Mochi falla sobre todo con frases que nadie escribió en la evaluación: chilenismos («un completo», «copete»,
«pa»), faltas («serbesa», «nesecito shampu»), preguntas sobre la app («hacen delivery?»), estados de ánimo («estoy
triste») o encargos («que me compren algo en una ferretería»). Este proceso las encuentra y las deja como regresión.

## Una ronda

1. Con la API arriba (`make serve` en `rappi-ia/`), escribe 40 a 60 frases como las escribiría alguien real, en
   `rappi-ia/src/rappi_ia/eval/frases_usuarios/rondaN.txt`: perfiles distintos (mamá apurada, carrete, adulto mayor,
   estudiante, fitness), mayúsculas, faltas, frases largas y combinaciones. `frase|vertical` la manda desde esa vertical;
   `+ frase` sigue la conversación (manda el pedido anterior, como el prototipo: «cerveza» y luego «+ más barata»).
2. `make probar-agente FRASES=src/rappi_ia/eval/frases_usuarios/rondaN.txt` y lee cada respuesta buscando:
   productos que no tienen que ver, una vertical rara, un aviso que sobra (+18 en un cumpleaños infantil), «Lo anoté»
   para algo que sí existe, o una pregunta sobre la app tratada como búsqueda.
3. Agrupa los fallos por causa (palabra que falta, ocasión, intención) y arréglalos donde corresponde: palabras y
   ocasiones en `concepts/taxonomy.toml` (`query_keywords` si la palabra solo sirve para pedir y no para clasificar
   productos, como «completo»), intenciones en `agent/understand.py`.
4. Cada fallo queda como test en `rappi-ia/tests/unit/test_user_phrases.py` (o en `test_rappi_agent.py` si necesita la
   base), escrito antes del arreglo.
5. Repite la ronda completa (`make probar-agente` sin archivo corre todas) para ver que no se rompió lo anterior, y
   compárala con la corrida anterior: una frase vieja que cambia de vertical o de conceptos es una regresión hasta que
   se demuestre lo contrario (así se pillaron «pastillas para dormir» saltando a Licores en la ronda 7 y «pañales talla
   m» perdiendo la talla en la ronda 9).
6. Un test que pasa sin el arreglo no prueba nada: desactiva el arreglo un momento y comprueba que falla (mutación).
   Cuando la base de prueba no reproduce el fallo, simula la búsqueda real con `monkeypatch` (ver
   `test_few_results_are_completed_with_the_concept`).

## Rondas hechas

| Ronda | Fecha | Frases | Qué se arregló |
|---|---|---|---|
| 1 | 04-10-2026 | 55 | chilenismos y faltas, cumpleaños sin alcohol, antojo dulce, panorama en casa, preguntas sobre la app, «barato» |
| 2 | 04-10-2026 | 50 | «pa»/«pal», «sin X», «qué me recomiendas», un mimo («estoy triste»), regalo para un niño, leches vegetales |
| 3 | 04-10-2026 | 46 | «nesecito», cadenas de restaurantes, «café en grano», «pollo con papas fritas», partido, cena romántica |
| 4 | 04-10-2026 | 23 (10 conversaciones) | seguimientos: «talla g», «más barata», «de otra marca», «y en el súper?», «sin lactosa», «con papas»; si nada es del concepto nombrado, se busca por su nombre («algo más sano», «tofu», «comida china») |
| 5 | 04-10-2026 | 42 (3 conversaciones) | muletillas («eh quiero este una coca po»), emojis («🍕», «quiero un 🍔»), «beer», «pastillas para dormir», «cerveza de 2 lucas», fuera de tema («el clima», «eres tonto»: se contesta y no cuenta como demanda), horario y lugar («farmacia de turno»), «y de vainilla?» tras «de chocolate» reemplaza en vez de sumar |
| 6 | 04-10-2026 | 44 (3 conversaciones) | reclamos de un pedido («mi pedido no llega», «cancelar»: a Mis pedidos, sin anotar demanda), negaciones («no quiero pizza», «cualquier cosa menos sushi»), «algo sin carne», «para mi papá» no son papas, juguete para mascota, «amburgesa», «pisa familiar», Fiestas Patrias como ocasión, seguimientos con relleno («mejor no, algo más barato») y «uno más caro» |
| 7 | 04-10-2026 | 44 (3 conversaciones) | un detalle que no está en la vertical se busca donde sí está («pan sin gluten»: «En Express no hay "sin gluten", pero en el súper sí»), las personas no se buscan («de mi mamá» traía mamaderas), «la presión» es un tensiómetro y diabetes o colesterol son con receta, cigarro electrónico, almuerzo saludable, «no quiero cocinar», Nescafé se compra, Starbucks es restaurante |
| 8 | 04-10-2026 | 36 (2 conversaciones) | la regla del detalle de la ronda 7 se pasaba («protector solar factor 50» y «desodorante para hombre» saltaban al súper por un producto): ahora pide 2 y no cuenta «hombre», «niños» ni «factor»; con menos de 3 resultados se completa con el concepto («unos puchos»), salvo si se nombró cadena o vertical; preguntas de privacidad («olvida lo que te dije» traía un dije), útiles escolares, bebida isotónica, «cabros chicos», «no me gustó ninguno» |
| 9 | 04-10-2026 | 31 (2 conversaciones) | desde una vertical que casi no tiene lo pedido se va a la que sí y lo dice («vino» en Farmacia: «En Farmacia no hay "vino", pero en Licores sí»); «remedio para la tos» busca el síntoma y no la palabra «remedio»; letras estiradas («holaaaa»), risas, números solos y links; «farmasia»; la vertical nombrada no se busca («en el super…» traía comida para gatos Super); «entre 5 y 10 mil», «menos de mil»; «y para tomar?» |
| 10 | 04-10-2026 | 35 (2 conversaciones) | ronda de convergencia (un día cualquiera: oficinista, mamá, estudiante, adulto mayor, fitness): casi todo ya respondía bien; «sushi sin palta» deja fuera lo que nombra la palta, «para llevar» es restaurante, noche de estudio como ocasión, «un energético», toallas húmedas, «ver una película» |

Tras la ronda 10 los fallos que quedan son sobre todo de vocabulario o de la muestra del catálogo (no hay jarabes
para la tos ni bolsas de basura; «Tempera 250ml» viene marcada +18). Las próximas rondas rinden más con perfiles
nuevos o probando el flujo en el prototipo (botones, «También en», seguimientos de varios turnos) que con más frases
sueltas.

Límite conocido: la muestra pública del catálogo no tiene algunas cosas (jarabes para la tos, tofu, bolsas de basura).
Ahí Mochi lo dice o muestra lo más cercano; no se arregla con palabras.
