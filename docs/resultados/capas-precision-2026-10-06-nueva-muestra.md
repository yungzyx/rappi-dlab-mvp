<!-- Copia versionada de rappi-ia/data/eval/capas-precision-s11.md (que no se versiona). Generada el 06-10-2026 con
     `rappi-ia layer-precision --seed 11` sobre rappi-ia/src/rappi_ia/eval/capas-muestra-s11.json y sus juicios.
     Solo métricas: sin textos del catálogo ni filas por marca (los errores con nombre están en el reporte local).
     Los juicios son de modelos de lenguaje: es una estimación. Los agregados siguen el diseño de la muestra
     (prioriza reglas propias y platos), no la proporción de cada fuente en la base. -->

# Precisión de la capa de datos

Juicios: un modelo de lenguaje (claude-opus-5-5) como juez, en 10 instancias independientes sobre la muestra fija (06-10-2026); acuerdo entre jueces en 80 filas juzgadas dos veces: 76 de 80. Los «dudoso» no cuentan. «Mínimo» es el límite
inferior del intervalo de Wilson al 95 %: con pocas muestras, lo que se puede asegurar.

## Por tipo y fuente

| Tipo | Fuente | Juzgados | Precisión | Mínimo | Dudosos | Si los dudosos fueran errores |
|---|---|---|---|---|---|---|
| atributo | rappi | 72 | 86 % | 76 % | 21 | 67 % |
| atributo | regla | 697 | 92 % | 89 % | 48 | 86 % |
| concepto | embedding | 115 | 88 % | 81 % | 5 | 84 % |
| concepto | llm | 136 | 88 % | 81 % | 4 | 85 % |
| concepto | regla | 173 | 86 % | 80 % | 7 | 83 % |
| marca | rappi | 39 | 97 % | 87 % | 1 | 95 % |
| marca | regla | 99 | 98 % | 93 % | 1 | 97 % |

## Todas las reglas

| Tipo | Clave | Fuente | Juzgados | Precisión | Mínimo |
|---|---|---|---|---|---|
| atributo | adolescentes | regla | 10 | 60 % | 31 % |
| atributo | adulto-mayor | rappi | 1 | 0 % | 0 % |
| atributo | adulto-mayor | regla | 10 | 100 % | 72 % |
| atributo | alto-fibra | rappi | 3 | 67 % | 21 % |
| atributo | alto-fibra | regla | 9 | 78 % | 45 % |
| atributo | alto-proteina | rappi | 2 | 100 % | 34 % |
| atributo | alto-proteina | regla | 8 | 88 % | 53 % |
| atributo | artesanal | rappi | 1 | 100 % | 21 % |
| atributo | artesanal | regla | 10 | 90 % | 60 % |
| atributo | bajo-sodio | rappi | 2 | 0 % | 0 % |
| atributo | bajo-sodio | regla | 9 | 100 % | 70 % |
| atributo | bebe | rappi | 3 | 100 % | 44 % |
| atributo | bebe | regla | 9 | 89 % | 56 % |
| atributo | bebida-incluida | regla | 10 | 100 % | 72 % |
| atributo | biodegradable | rappi | 2 | 50 % | 10 % |
| atributo | biodegradable | regla | 8 | 100 % | 68 % |
| atributo | cachorro | rappi | 3 | 100 % | 44 % |
| atributo | cachorro | regla | 9 | 89 % | 56 % |
| atributo | capsulas | regla | 10 | 80 % | 49 % |
| atributo | casero | regla | 9 | 100 % | 70 % |
| atributo | chileno | rappi | 3 | 100 % | 44 % |
| atributo | chileno | regla | 9 | 100 % | 70 % |
| atributo | combo | regla | 10 | 100 % | 72 % |
| atributo | con-acompanamiento | regla | 10 | 100 % | 72 % |
| atributo | congelado | rappi | 3 | 100 % | 44 % |
| atributo | congelado | regla | 10 | 100 % | 72 % |
| atributo | crudo | regla | 9 | 89 % | 56 % |
| atributo | cruelty-free | rappi | 0 | — | — |
| atributo | cruelty-free | regla | 6 | 100 % | 61 % |
| atributo | cumpleanos | regla | 10 | 90 % | 60 % |
| atributo | desayuno | regla | 10 | 80 % | 49 % |
| atributo | desechable | regla | 10 | 90 % | 60 % |
| atributo | eco | regla | 9 | 100 % | 70 % |
| atributo | embarazo-lactancia | regla | 10 | 100 % | 72 % |
| atributo | en-polvo | regla | 10 | 90 % | 60 % |
| atributo | familiar | regla | 10 | 100 % | 72 % |
| atributo | fiestas-patrias | regla | 9 | 100 % | 70 % |
| atributo | frito | regla | 10 | 100 % | 72 % |
| atributo | gato | rappi | 3 | 100 % | 44 % |
| atributo | gato | regla | 10 | 90 % | 60 % |
| atributo | granel | regla | 10 | 100 % | 72 % |
| atributo | halal | regla | 7 | 100 % | 65 % |
| atributo | halloween | regla | 10 | 70 % | 40 % |
| atributo | hombre | rappi | 3 | 100 % | 44 % |
| atributo | hombre | regla | 10 | 100 % | 72 % |
| atributo | horno | regla | 7 | 71 % | 36 % |
| atributo | importado | regla | 9 | 100 % | 70 % |
| atributo | individual | regla | 10 | 90 % | 60 % |
| atributo | instantaneo | regla | 10 | 100 % | 72 % |
| atributo | integral | regla | 10 | 100 % | 72 % |
| atributo | keto | rappi | 3 | 100 % | 44 % |
| atributo | keto | regla | 8 | 100 % | 68 % |
| atributo | kosher | rappi | 2 | 100 % | 34 % |
| atributo | kosher | regla | 10 | 100 % | 72 % |
| atributo | lata | regla | 10 | 100 % | 72 % |
| atributo | light | rappi | 3 | 67 % | 21 % |
| atributo | light | regla | 10 | 100 % | 72 % |
| atributo | listo-para-comer | regla | 10 | 80 % | 49 % |
| atributo | mascota-senior | rappi | 3 | 100 % | 44 % |
| atributo | mascota-senior | regla | 1 | 100 % | 21 % |
| atributo | mujer | rappi | 2 | 100 % | 34 % |
| atributo | mujer | regla | 7 | 71 % | 36 % |
| atributo | natural | rappi | 1 | 100 % | 21 % |
| atributo | natural | regla | 9 | 78 % | 45 % |
| atributo | navidad | regla | 9 | 100 % | 70 % |
| atributo | ninos | rappi | 2 | 100 % | 34 % |
| atributo | ninos | regla | 10 | 80 % | 49 % |
| atributo | organico | rappi | 2 | 50 % | 10 % |
| atributo | organico | regla | 10 | 90 % | 60 % |
| atributo | otras-mascotas | rappi | 1 | 100 % | 21 % |
| atributo | otras-mascotas | regla | 10 | 70 % | 40 % |
| atributo | pack | regla | 9 | 67 % | 35 % |
| atributo | para-compartir | regla | 10 | 100 % | 72 % |
| atributo | para-preparar | regla | 9 | 67 % | 35 % |
| atributo | para-regalo | regla | 9 | 100 % | 70 % |
| atributo | parrilla | regla | 9 | 78 % | 45 % |
| atributo | perro | rappi | 3 | 100 % | 44 % |
| atributo | perro | regla | 10 | 80 % | 49 % |
| atributo | pescetariano | regla | 1 | 100 % | 21 % |
| atributo | picante | regla | 10 | 100 % | 72 % |
| atributo | postre-incluido | regla | 10 | 100 % | 72 % |
| atributo | premium | regla | 10 | 100 % | 72 % |
| atributo | recargable | regla | 10 | 60 % | 31 % |
| atributo | reciclable | regla | 8 | 100 % | 68 % |
| atributo | refrigerado | regla | 10 | 100 % | 72 % |
| atributo | retornable | regla | 7 | 86 % | 49 % |
| atributo | saludable | regla | 10 | 100 % | 72 % |
| atributo | san-valentin | regla | 4 | 100 % | 51 % |
| atributo | sin-alcohol | rappi | 3 | 100 % | 44 % |
| atributo | sin-alcohol | regla | 10 | 100 % | 72 % |
| atributo | sin-azucar | rappi | 2 | 100 % | 34 % |
| atributo | sin-azucar | regla | 9 | 89 % | 56 % |
| atributo | sin-cafeina | rappi | 3 | 100 % | 44 % |
| atributo | sin-cafeina | regla | 8 | 100 % | 68 % |
| atributo | sin-frutos-secos | regla | 5 | 80 % | 38 % |
| atributo | sin-gluten | rappi | 2 | 100 % | 34 % |
| atributo | sin-gluten | regla | 9 | 100 % | 70 % |
| atributo | sin-huevo | regla | 10 | 90 % | 60 % |
| atributo | sin-lactosa | rappi | 3 | 67 % | 21 % |
| atributo | sin-lactosa | regla | 9 | 100 % | 70 % |
| atributo | sin-parabenos | rappi | 2 | 100 % | 34 % |
| atributo | sin-parabenos | regla | 8 | 100 % | 68 % |
| atributo | sin-soya | regla | 10 | 100 % | 72 % |
| atributo | tamano-viaje | regla | 5 | 80 % | 38 % |
| atributo | vegano | rappi | 3 | 67 % | 21 % |
| atributo | vegano | regla | 8 | 100 % | 68 % |
| atributo | vegetariano | rappi | 3 | 67 % | 21 % |
| atributo | vegetariano | regla | 10 | 90 % | 60 % |
| atributo | vidrio | regla | 10 | 90 % | 60 % |
| concepto | accesorios-fumador | llm | 1 | 100 % | 21 % |
| concepto | accesorios-fumador | regla | 14 | 100 % | 78 % |
| concepto | accesorios-mascota | llm | 2 | 100 % | 34 % |
| concepto | accesorios-mascota | regla | 2 | 100 % | 34 % |
| concepto | accesorios-moda | llm | 3 | 67 % | 21 % |
| concepto | accesorios-moda | regla | 1 | 0 % | 0 % |
| concepto | aceites-condimentos | llm | 3 | 100 % | 44 % |
| concepto | alimento-gato | embedding | 1 | 100 % | 21 % |
| concepto | alimento-gato | llm | 1 | 100 % | 21 % |
| concepto | alimento-perro | embedding | 1 | 0 % | 0 % |
| concepto | alimento-perro | llm | 1 | 0 % | 0 % |
| concepto | arroz-legumbres | llm | 2 | 50 % | 10 % |
| concepto | arroz-legumbres | regla | 1 | 100 % | 21 % |
| concepto | articulos-bebe | llm | 2 | 100 % | 34 % |
| concepto | articulos-deportivos | llm | 1 | 100 % | 21 % |
| concepto | asiatica | llm | 1 | 0 % | 0 % |
| concepto | asiatica | regla | 8 | 100 % | 68 % |
| concepto | audio | embedding | 3 | 67 % | 21 % |
| concepto | audio | llm | 1 | 100 % | 21 % |
| concepto | automotriz | regla | 1 | 100 % | 21 % |
| concepto | azucar | llm | 1 | 100 % | 21 % |
| concepto | bienestar-sexual | embedding | 1 | 100 % | 21 % |
| concepto | bienestar-sexual | llm | 1 | 100 % | 21 % |
| concepto | bienestar-sexual | regla | 1 | 100 % | 21 % |
| concepto | cafe | llm | 2 | 50 % | 10 % |
| concepto | cafe | regla | 1 | 100 % | 21 % |
| concepto | calzado | embedding | 1 | 0 % | 0 % |
| concepto | carnes | regla | 3 | 67 % | 21 % |
| concepto | celulares | embedding | 5 | 100 % | 57 % |
| concepto | celulares | llm | 2 | 100 % | 34 % |
| concepto | cerveza | embedding | 2 | 50 % | 10 % |
| concepto | cerveza | regla | 1 | 100 % | 21 % |
| concepto | chocolates | llm | 1 | 100 % | 21 % |
| concepto | chocolates | regla | 3 | 67 % | 21 % |
| concepto | cigarrillos | embedding | 1 | 0 % | 0 % |
| concepto | cocina-menaje | llm | 1 | 100 % | 21 % |
| concepto | cocina-menaje | regla | 1 | 100 % | 21 % |
| concepto | conservas | regla | 1 | 0 % | 0 % |
| concepto | cuidado-cabello | llm | 3 | 100 % | 44 % |
| concepto | cuidado-oral | llm | 2 | 100 % | 34 % |
| concepto | decoracion | llm | 4 | 100 % | 51 % |
| concepto | decoracion | regla | 1 | 100 % | 21 % |
| concepto | dermocosmetica | llm | 1 | 100 % | 21 % |
| concepto | dermocosmetica | regla | 2 | 100 % | 34 % |
| concepto | empanadas | embedding | 1 | 0 % | 0 % |
| concepto | empanadas | regla | 4 | 100 % | 51 % |
| concepto | ensaladas-bowls | embedding | 1 | 100 % | 21 % |
| concepto | ensaladas-bowls | llm | 2 | 100 % | 34 % |
| concepto | ensaladas-bowls | regla | 7 | 100 % | 65 % |
| concepto | ferreteria | llm | 7 | 100 % | 65 % |
| concepto | ferreteria | regla | 1 | 100 % | 21 % |
| concepto | flores-regalos | llm | 1 | 100 % | 21 % |
| concepto | flores-regalos | regla | 1 | 0 % | 0 % |
| concepto | frutas | embedding | 1 | 0 % | 0 % |
| concepto | frutos-secos | regla | 1 | 0 % | 0 % |
| concepto | galletas | embedding | 1 | 100 % | 21 % |
| concepto | galletas | regla | 1 | 100 % | 21 % |
| concepto | gaseosas | embedding | 3 | 0 % | 0 % |
| concepto | gaseosas | llm | 5 | 80 % | 38 % |
| concepto | gaseosas | regla | 15 | 93 % | 70 % |
| concepto | hamburguesa | embedding | 5 | 80 % | 38 % |
| concepto | hamburguesa | llm | 3 | 100 % | 44 % |
| concepto | hamburguesa | regla | 6 | 100 % | 61 % |
| concepto | helados | llm | 1 | 100 % | 21 % |
| concepto | helados | regla | 2 | 50 % | 10 % |
| concepto | higiene-personal | llm | 2 | 100 % | 34 % |
| concepto | joyeria | llm | 1 | 100 % | 21 % |
| concepto | joyeria | regla | 4 | 50 % | 15 % |
| concepto | juegos-mesa | embedding | 1 | 100 % | 21 % |
| concepto | jugos | regla | 1 | 100 % | 21 % |
| concepto | juguetes-infantiles | regla | 1 | 0 % | 0 % |
| concepto | lacteos | embedding | 1 | 100 % | 21 % |
| concepto | lacteos | llm | 1 | 100 % | 21 % |
| concepto | latina | regla | 7 | 100 % | 65 % |
| concepto | libros | embedding | 1 | 100 % | 21 % |
| concepto | limpieza | embedding | 1 | 0 % | 0 % |
| concepto | limpieza | llm | 2 | 100 % | 34 % |
| concepto | limpieza | regla | 1 | 0 % | 0 % |
| concepto | manualidades | embedding | 3 | 100 % | 44 % |
| concepto | manualidades | regla | 3 | 100 % | 44 % |
| concepto | maquillaje | llm | 2 | 100 % | 34 % |
| concepto | medicamentos | embedding | 1 | 100 % | 21 % |
| concepto | medicamentos | llm | 1 | 100 % | 21 % |
| concepto | mexicana | regla | 1 | 100 % | 21 % |
| concepto | muebles | embedding | 1 | 100 % | 21 % |
| concepto | muebles | llm | 1 | 0 % | 0 % |
| concepto | panaderia | regla | 1 | 100 % | 21 % |
| concepto | panales | llm | 1 | 100 % | 21 % |
| concepto | pastas | llm | 2 | 100 % | 34 % |
| concepto | pastas | regla | 1 | 100 % | 21 % |
| concepto | pasteleria | embedding | 2 | 100 % | 34 % |
| concepto | pasteleria | llm | 12 | 58 % | 32 % |
| concepto | pasteleria | regla | 1 | 100 % | 21 % |
| concepto | peruana | regla | 1 | 100 % | 21 % |
| concepto | pescados-mariscos | regla | 6 | 83 % | 44 % |
| concepto | picoteo | llm | 2 | 100 % | 34 % |
| concepto | picoteo | regla | 2 | 100 % | 34 % |
| concepto | pisco | embedding | 2 | 50 % | 10 % |
| concepto | pizza | embedding | 1 | 100 % | 21 % |
| concepto | pizza | llm | 16 | 75 % | 50 % |
| concepto | pizza | regla | 6 | 100 % | 61 % |
| concepto | platos-listos | embedding | 17 | 100 % | 82 % |
| concepto | platos-listos | llm | 4 | 100 % | 51 % |
| concepto | platos-listos | regla | 3 | 100 % | 44 % |
| concepto | pollo | regla | 8 | 38 % | 14 % |
| concepto | pollo-preparado | regla | 1 | 100 % | 21 % |
| concepto | postres | embedding | 5 | 100 % | 57 % |
| concepto | postres | llm | 3 | 100 % | 44 % |
| concepto | postres | regla | 2 | 100 % | 34 % |
| concepto | primeros-auxilios | llm | 1 | 100 % | 21 % |
| concepto | quesos | llm | 3 | 100 % | 44 % |
| concepto | quesos | regla | 1 | 100 % | 21 % |
| concepto | reposteria | regla | 4 | 100 % | 51 % |
| concepto | ropa | embedding | 2 | 100 % | 34 % |
| concepto | ropa | llm | 1 | 100 % | 21 % |
| concepto | ropa-interior | embedding | 2 | 100 % | 34 % |
| concepto | salsas | embedding | 1 | 100 % | 21 % |
| concepto | salsas | llm | 2 | 100 % | 34 % |
| concepto | salsas | regla | 3 | 67 % | 21 % |
| concepto | sandwiches | embedding | 13 | 100 % | 77 % |
| concepto | sandwiches | llm | 1 | 100 % | 21 % |
| concepto | sandwiches | regla | 11 | 100 % | 74 % |
| concepto | snacks-salados | llm | 2 | 100 % | 34 % |
| concepto | snacks-salados | regla | 3 | 67 % | 21 % |
| concepto | sopas | embedding | 1 | 0 % | 0 % |
| concepto | sopas | llm | 1 | 100 % | 21 % |
| concepto | sopas | regla | 1 | 100 % | 21 % |
| concepto | sushi | embedding | 32 | 100 % | 89 % |
| concepto | sushi | llm | 13 | 92 % | 67 % |
| concepto | sushi | regla | 14 | 100 % | 78 % |
| concepto | textil-hogar | llm | 1 | 100 % | 21 % |
| concepto | tv-video | embedding | 1 | 100 % | 21 % |
| concepto | tv-video | regla | 1 | 0 % | 0 % |
| concepto | utiles | llm | 1 | 100 % | 21 % |
| concepto | vapeo | regla | 3 | 100 % | 44 % |
| concepto | vegano | regla | 2 | 0 % | 0 % |
| concepto | verduras | llm | 1 | 100 % | 21 % |
| concepto | verduras | regla | 1 | 0 % | 0 % |
| concepto | vino | llm | 1 | 100 % | 21 % |
| concepto | vitaminas | llm | 3 | 100 % | 44 % |

## Después de los cambios de reglas (sin volver a juzgar)

Lo ya juzgado que la base sigue afirmando hoy: los errores eliminados y los aciertos perdidos miden el
cambio; la precisión «después» es la de lo que sigue afirmándose.

| Tipo | Fuente | Precisión antes | Después | Errores eliminados | Aciertos perdidos |
|---|---|---|---|---|---|
| atributo | rappi | 86 % | 86 % | 0 de 10 | 0 de 62 |
| atributo | regla | 92 % | 92 % | 0 de 58 | 0 de 639 |
| concepto | embedding | 88 % | 88 % | 0 de 14 | 0 de 101 |
| concepto | llm | 88 % | 88 % | 0 de 17 | 0 de 119 |
| concepto | regla | 86 % | 86 % | 0 de 24 | 0 de 149 |
| marca | rappi | 97 % | 97 % | 0 de 1 | 0 de 38 |
| marca | regla | 98 % | 98 % | 0 de 2 | 0 de 97 |
