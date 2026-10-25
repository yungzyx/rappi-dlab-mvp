<!-- Copia versionada de rappi-ia/data/eval/capas-precision.md (que no se versiona). Generada el 06-10-2026 con
     `rappi-ia layer-precision --seed 7` sobre rappi-ia/src/rappi_ia/eval/capas-muestra.json y sus juicios.
     Solo métricas: sin textos del catálogo ni filas por marca (los errores con nombre están en el reporte local).
     Los juicios son de modelos de lenguaje: es una estimación. Los agregados siguen el diseño de la muestra
     (prioriza reglas propias y platos), no la proporción de cada fuente en la base. -->

# Precisión de la capa de datos

Juicios: un modelo de lenguaje (claude-opus-5-5) como juez, en 10 instancias independientes sobre la muestra fija (06-10-2026); acuerdo entre jueces en 80 filas juzgadas dos veces: 77 de 80. Los «dudoso» no cuentan. «Mínimo» es el límite
inferior del intervalo de Wilson al 95 %: con pocas muestras, lo que se puede asegurar.

## Por tipo y fuente

| Tipo | Fuente | Juzgados | Precisión | Mínimo | Dudosos | Si los dudosos fueran errores |
|---|---|---|---|---|---|---|
| atributo | rappi | 64 | 86 % | 75 % | 29 | 59 % |
| atributo | regla | 690 | 92 % | 90 % | 61 | 84 % |
| concepto | embedding | 115 | 57 % | 48 % | 5 | 55 % |
| concepto | llm | 134 | 82 % | 75 % | 6 | 79 % |
| concepto | regla | 172 | 81 % | 75 % | 8 | 78 % |
| marca | rappi | 38 | 97 % | 86 % | 2 | 92 % |
| marca | regla | 99 | 99 % | 94 % | 1 | 98 % |

## Todas las reglas

| Tipo | Clave | Fuente | Juzgados | Precisión | Mínimo |
|---|---|---|---|---|---|
| atributo | adolescentes | regla | 1 | 0 % | 0 % |
| atributo | adulto-mayor | rappi | 1 | 0 % | 0 % |
| atributo | adulto-mayor | regla | 10 | 90 % | 60 % |
| atributo | alto-fibra | rappi | 2 | 50 % | 10 % |
| atributo | alto-fibra | regla | 10 | 30 % | 11 % |
| atributo | alto-proteina | rappi | 3 | 100 % | 44 % |
| atributo | alto-proteina | regla | 10 | 100 % | 72 % |
| atributo | artesanal | rappi | 2 | 100 % | 34 % |
| atributo | artesanal | regla | 10 | 90 % | 60 % |
| atributo | bajo-sodio | rappi | 1 | 0 % | 0 % |
| atributo | bajo-sodio | regla | 10 | 100 % | 72 % |
| atributo | bebe | rappi | 3 | 100 % | 44 % |
| atributo | bebe | regla | 10 | 80 % | 49 % |
| atributo | bebida-incluida | regla | 10 | 100 % | 72 % |
| atributo | biodegradable | rappi | 1 | 0 % | 0 % |
| atributo | biodegradable | regla | 6 | 100 % | 61 % |
| atributo | cachorro | rappi | 3 | 100 % | 44 % |
| atributo | cachorro | regla | 10 | 80 % | 49 % |
| atributo | capsulas | regla | 10 | 90 % | 60 % |
| atributo | casero | regla | 10 | 100 % | 72 % |
| atributo | chileno | rappi | 3 | 100 % | 44 % |
| atributo | chileno | regla | 10 | 90 % | 60 % |
| atributo | combo | regla | 10 | 100 % | 72 % |
| atributo | con-acompanamiento | regla | 10 | 100 % | 72 % |
| atributo | congelado | rappi | 3 | 100 % | 44 % |
| atributo | congelado | regla | 10 | 100 % | 72 % |
| atributo | crudo | regla | 10 | 80 % | 49 % |
| atributo | cruelty-free | rappi | 0 | — | — |
| atributo | cruelty-free | regla | 7 | 100 % | 65 % |
| atributo | cumpleanos | regla | 10 | 100 % | 72 % |
| atributo | desayuno | regla | 9 | 78 % | 45 % |
| atributo | desechable | regla | 9 | 89 % | 56 % |
| atributo | eco | regla | 8 | 100 % | 68 % |
| atributo | embarazo-lactancia | regla | 9 | 100 % | 70 % |
| atributo | en-polvo | regla | 10 | 90 % | 60 % |
| atributo | familiar | regla | 10 | 100 % | 72 % |
| atributo | fiestas-patrias | regla | 9 | 100 % | 70 % |
| atributo | frito | regla | 9 | 100 % | 70 % |
| atributo | gato | rappi | 3 | 100 % | 44 % |
| atributo | gato | regla | 10 | 100 % | 72 % |
| atributo | granel | regla | 10 | 100 % | 72 % |
| atributo | halal | regla | 5 | 100 % | 57 % |
| atributo | halloween | regla | 10 | 80 % | 49 % |
| atributo | hombre | rappi | 3 | 100 % | 44 % |
| atributo | hombre | regla | 9 | 89 % | 56 % |
| atributo | horno | regla | 9 | 89 % | 56 % |
| atributo | importado | regla | 10 | 100 % | 72 % |
| atributo | individual | regla | 10 | 100 % | 72 % |
| atributo | instantaneo | regla | 10 | 60 % | 31 % |
| atributo | integral | regla | 9 | 100 % | 70 % |
| atributo | keto | rappi | 3 | 100 % | 44 % |
| atributo | keto | regla | 10 | 100 % | 72 % |
| atributo | kosher | rappi | 2 | 100 % | 34 % |
| atributo | kosher | regla | 9 | 100 % | 70 % |
| atributo | lata | regla | 10 | 100 % | 72 % |
| atributo | light | rappi | 1 | 100 % | 21 % |
| atributo | light | regla | 10 | 100 % | 72 % |
| atributo | listo-para-comer | regla | 10 | 100 % | 72 % |
| atributo | mascota-senior | rappi | 3 | 100 % | 44 % |
| atributo | mascota-senior | regla | 1 | 100 % | 21 % |
| atributo | mujer | rappi | 2 | 100 % | 34 % |
| atributo | mujer | regla | 10 | 100 % | 72 % |
| atributo | natural | rappi | 0 | — | — |
| atributo | natural | regla | 7 | 100 % | 65 % |
| atributo | navidad | regla | 10 | 90 % | 60 % |
| atributo | ninos | rappi | 3 | 100 % | 44 % |
| atributo | ninos | regla | 9 | 100 % | 70 % |
| atributo | organico | rappi | 1 | 100 % | 21 % |
| atributo | organico | regla | 7 | 57 % | 25 % |
| atributo | otras-mascotas | rappi | 2 | 0 % | 0 % |
| atributo | otras-mascotas | regla | 10 | 80 % | 49 % |
| atributo | pack | regla | 9 | 89 % | 56 % |
| atributo | para-compartir | regla | 10 | 100 % | 72 % |
| atributo | para-preparar | regla | 8 | 88 % | 53 % |
| atributo | para-regalo | regla | 10 | 100 % | 72 % |
| atributo | parrilla | regla | 8 | 38 % | 14 % |
| atributo | perro | rappi | 3 | 100 % | 44 % |
| atributo | perro | regla | 10 | 90 % | 60 % |
| atributo | pescetariano | regla | 1 | 100 % | 21 % |
| atributo | picante | regla | 10 | 100 % | 72 % |
| atributo | postre-incluido | regla | 10 | 100 % | 72 % |
| atributo | premium | regla | 10 | 100 % | 72 % |
| atributo | recargable | regla | 10 | 100 % | 72 % |
| atributo | reciclable | regla | 6 | 100 % | 61 % |
| atributo | refrigerado | regla | 10 | 100 % | 72 % |
| atributo | retornable | regla | 7 | 86 % | 49 % |
| atributo | saludable | regla | 8 | 62 % | 31 % |
| atributo | san-valentin | regla | 8 | 75 % | 41 % |
| atributo | sin-alcohol | rappi | 3 | 67 % | 21 % |
| atributo | sin-alcohol | regla | 10 | 80 % | 49 % |
| atributo | sin-azucar | rappi | 2 | 100 % | 34 % |
| atributo | sin-azucar | regla | 10 | 100 % | 72 % |
| atributo | sin-cafeina | rappi | 3 | 100 % | 44 % |
| atributo | sin-cafeina | regla | 10 | 100 % | 72 % |
| atributo | sin-frutos-secos | regla | 7 | 86 % | 49 % |
| atributo | sin-gluten | rappi | 2 | 100 % | 34 % |
| atributo | sin-gluten | regla | 9 | 100 % | 70 % |
| atributo | sin-huevo | regla | 10 | 90 % | 60 % |
| atributo | sin-lactosa | rappi | 1 | 0 % | 0 % |
| atributo | sin-lactosa | regla | 9 | 100 % | 70 % |
| atributo | sin-parabenos | rappi | 0 | — | — |
| atributo | sin-parabenos | regla | 8 | 100 % | 68 % |
| atributo | sin-soya | regla | 9 | 100 % | 70 % |
| atributo | tamano-viaje | regla | 5 | 80 % | 38 % |
| atributo | vegano | rappi | 2 | 100 % | 34 % |
| atributo | vegano | regla | 9 | 100 % | 70 % |
| atributo | vegetariano | rappi | 3 | 67 % | 21 % |
| atributo | vegetariano | regla | 9 | 89 % | 56 % |
| atributo | vidrio | regla | 8 | 100 % | 68 % |
| concepto | accesorios-fumador | llm | 1 | 100 % | 21 % |
| concepto | accesorios-fumador | regla | 16 | 94 % | 72 % |
| concepto | accesorios-mascota | regla | 2 | 100 % | 34 % |
| concepto | accesorios-moda | llm | 1 | 100 % | 21 % |
| concepto | agua | llm | 1 | 0 % | 0 % |
| concepto | agua | regla | 1 | 100 % | 21 % |
| concepto | alimento-gato | embedding | 2 | 100 % | 34 % |
| concepto | alimento-gato | regla | 1 | 0 % | 0 % |
| concepto | arabe | regla | 3 | 100 % | 44 % |
| concepto | arroz-legumbres | llm | 1 | 100 % | 21 % |
| concepto | arroz-legumbres | regla | 1 | 0 % | 0 % |
| concepto | articulos-bebe | llm | 3 | 100 % | 44 % |
| concepto | asiatica | embedding | 1 | 0 % | 0 % |
| concepto | asiatica | regla | 5 | 100 % | 57 % |
| concepto | audio | embedding | 2 | 100 % | 34 % |
| concepto | audio | llm | 1 | 100 % | 21 % |
| concepto | audio | regla | 1 | 100 % | 21 % |
| concepto | automotriz | regla | 1 | 100 % | 21 % |
| concepto | azucar | regla | 2 | 50 % | 10 % |
| concepto | bienestar-sexual | llm | 2 | 100 % | 34 % |
| concepto | cafe | embedding | 1 | 100 % | 21 % |
| concepto | cafe | llm | 1 | 100 % | 21 % |
| concepto | calzado | embedding | 1 | 0 % | 0 % |
| concepto | calzado | llm | 2 | 100 % | 34 % |
| concepto | carnes | llm | 2 | 50 % | 10 % |
| concepto | carnes | regla | 7 | 57 % | 25 % |
| concepto | celulares | embedding | 3 | 100 % | 44 % |
| concepto | celulares | regla | 1 | 100 % | 21 % |
| concepto | cerveza | llm | 3 | 100 % | 44 % |
| concepto | cerveza | regla | 2 | 100 % | 34 % |
| concepto | chocolates | embedding | 1 | 100 % | 21 % |
| concepto | chocolates | regla | 5 | 80 % | 38 % |
| concepto | cigarrillos | embedding | 2 | 100 % | 34 % |
| concepto | cigarrillos | regla | 1 | 100 % | 21 % |
| concepto | cocina-menaje | embedding | 1 | 0 % | 0 % |
| concepto | cuidado-cabello | llm | 5 | 100 % | 57 % |
| concepto | cuidado-oral | llm | 1 | 100 % | 21 % |
| concepto | decoracion | llm | 2 | 100 % | 34 % |
| concepto | decoracion | regla | 1 | 100 % | 21 % |
| concepto | dermocosmetica | embedding | 1 | 100 % | 21 % |
| concepto | dermocosmetica | llm | 5 | 100 % | 57 % |
| concepto | dermocosmetica | regla | 1 | 100 % | 21 % |
| concepto | empanadas | regla | 5 | 100 % | 57 % |
| concepto | energizantes | regla | 1 | 100 % | 21 % |
| concepto | ensaladas-bowls | embedding | 3 | 33 % | 6 % |
| concepto | ensaladas-bowls | regla | 2 | 100 % | 34 % |
| concepto | ferreteria | llm | 3 | 100 % | 44 % |
| concepto | fiambres | embedding | 1 | 0 % | 0 % |
| concepto | fiambres | regla | 1 | 0 % | 0 % |
| concepto | frutas | regla | 5 | 0 % | 0 % |
| concepto | frutos-secos | regla | 1 | 0 % | 0 % |
| concepto | galletas | llm | 3 | 100 % | 44 % |
| concepto | gaseosas | embedding | 7 | 14 % | 3 % |
| concepto | gaseosas | llm | 2 | 50 % | 10 % |
| concepto | gaseosas | regla | 14 | 100 % | 78 % |
| concepto | golosinas | llm | 1 | 100 % | 21 % |
| concepto | hamburguesa | embedding | 15 | 47 % | 25 % |
| concepto | hamburguesa | llm | 3 | 33 % | 6 % |
| concepto | hamburguesa | regla | 3 | 100 % | 44 % |
| concepto | helados | embedding | 1 | 100 % | 21 % |
| concepto | helados | llm | 1 | 100 % | 21 % |
| concepto | helados | regla | 1 | 100 % | 21 % |
| concepto | higiene-femenina | embedding | 1 | 100 % | 21 % |
| concepto | higiene-femenina | llm | 2 | 100 % | 34 % |
| concepto | jardin | embedding | 1 | 0 % | 0 % |
| concepto | joyeria | regla | 1 | 100 % | 21 % |
| concepto | juegos-mesa | llm | 2 | 100 % | 34 % |
| concepto | jugos | embedding | 1 | 0 % | 0 % |
| concepto | jugos | regla | 1 | 100 % | 21 % |
| concepto | juguetes-infantiles | llm | 3 | 100 % | 44 % |
| concepto | juguetes-infantiles | regla | 1 | 0 % | 0 % |
| concepto | lacteos | embedding | 1 | 100 % | 21 % |
| concepto | lacteos | llm | 1 | 100 % | 21 % |
| concepto | lacteos | regla | 1 | 0 % | 0 % |
| concepto | latina | regla | 1 | 100 % | 21 % |
| concepto | libros | embedding | 1 | 100 % | 21 % |
| concepto | libros | llm | 2 | 100 % | 34 % |
| concepto | limpieza | embedding | 1 | 100 % | 21 % |
| concepto | manualidades | embedding | 7 | 100 % | 65 % |
| concepto | maquillaje | llm | 5 | 80 % | 38 % |
| concepto | medicamentos | embedding | 1 | 100 % | 21 % |
| concepto | medicamentos | regla | 1 | 100 % | 21 % |
| concepto | mexicana | regla | 1 | 100 % | 21 % |
| concepto | muebles | embedding | 1 | 0 % | 0 % |
| concepto | musica | regla | 1 | 100 % | 21 % |
| concepto | panaderia | regla | 1 | 100 % | 21 % |
| concepto | panales | llm | 1 | 100 % | 21 % |
| concepto | pastas | llm | 1 | 100 % | 21 % |
| concepto | pasteleria | llm | 5 | 80 % | 38 % |
| concepto | pasteleria | regla | 3 | 100 % | 44 % |
| concepto | pescados-mariscos | llm | 1 | 100 % | 21 % |
| concepto | pescados-mariscos | regla | 13 | 100 % | 77 % |
| concepto | picoteo | llm | 1 | 100 % | 21 % |
| concepto | picoteo | regla | 2 | 100 % | 34 % |
| concepto | pizza | embedding | 1 | 100 % | 21 % |
| concepto | pizza | llm | 5 | 60 % | 23 % |
| concepto | pizza | regla | 2 | 100 % | 34 % |
| concepto | platos-listos | embedding | 3 | 100 % | 44 % |
| concepto | platos-listos | llm | 2 | 100 % | 34 % |
| concepto | platos-listos | regla | 1 | 100 % | 21 % |
| concepto | pollo | regla | 5 | 100 % | 57 % |
| concepto | postres | embedding | 9 | 78 % | 45 % |
| concepto | postres | llm | 1 | 100 % | 21 % |
| concepto | primeros-auxilios | llm | 1 | 100 % | 21 % |
| concepto | quesos | llm | 2 | 100 % | 34 % |
| concepto | quesos | regla | 2 | 50 % | 10 % |
| concepto | reposteria | llm | 1 | 100 % | 21 % |
| concepto | reposteria | regla | 1 | 100 % | 21 % |
| concepto | ropa | llm | 1 | 100 % | 21 % |
| concepto | ropa-interior | embedding | 2 | 0 % | 0 % |
| concepto | ropa-interior | llm | 1 | 100 % | 21 % |
| concepto | salsas | embedding | 3 | 33 % | 6 % |
| concepto | salsas | regla | 1 | 100 % | 21 % |
| concepto | salud-sexual | llm | 1 | 100 % | 21 % |
| concepto | sandwiches | embedding | 18 | 56 % | 34 % |
| concepto | sandwiches | llm | 1 | 100 % | 21 % |
| concepto | sandwiches | regla | 8 | 88 % | 53 % |
| concepto | snacks-salados | llm | 1 | 0 % | 0 % |
| concepto | snacks-salados | regla | 3 | 33 % | 6 % |
| concepto | sopas | llm | 1 | 100 % | 21 % |
| concepto | sopas | regla | 6 | 67 % | 30 % |
| concepto | sushi | embedding | 16 | 38 % | 18 % |
| concepto | sushi | llm | 36 | 64 % | 48 % |
| concepto | sushi | regla | 13 | 92 % | 67 % |
| concepto | te | llm | 1 | 100 % | 21 % |
| concepto | te | regla | 1 | 100 % | 21 % |
| concepto | textil-hogar | embedding | 2 | 0 % | 0 % |
| concepto | textil-hogar | regla | 2 | 50 % | 10 % |
| concepto | tv-video | regla | 1 | 0 % | 0 % |
| concepto | untables-dulces | llm | 1 | 100 % | 21 % |
| concepto | untables-dulces | regla | 2 | 0 % | 0 % |
| concepto | utiles | llm | 2 | 50 % | 10 % |
| concepto | vapeo | embedding | 3 | 100 % | 44 % |
| concepto | vapeo | llm | 3 | 100 % | 44 % |
| concepto | vapeo | regla | 7 | 100 % | 65 % |
| concepto | vegano | regla | 1 | 0 % | 0 % |
| concepto | verduras | llm | 2 | 100 % | 34 % |
| concepto | verduras | regla | 4 | 25 % | 5 % |
| concepto | vino | llm | 1 | 100 % | 21 % |
| concepto | vitaminas | llm | 1 | 100 % | 21 % |
| concepto | vitaminas | regla | 1 | 100 % | 21 % |
| concepto | vodka | llm | 1 | 100 % | 21 % |
| concepto | whisky | embedding | 1 | 100 % | 21 % |

## Después de los cambios de reglas (sin volver a juzgar)

Lo ya juzgado que la base sigue afirmando hoy: los errores eliminados y los aciertos perdidos miden el
cambio; la precisión «después» es la de lo que sigue afirmándose.

| Tipo | Fuente | Precisión antes | Después | Errores eliminados | Aciertos perdidos |
|---|---|---|---|---|---|
| atributo | rappi | 86 % | 87 % | 1 de 9 | 0 de 55 |
| atributo | regla | 92 % | 96 % | 27 de 56 | 9 de 634 |
| concepto | embedding | 57 % | 82 % | 40 de 49 | 25 de 66 |
| concepto | llm | 82 % | 95 % | 18 de 24 | 5 de 110 |
| concepto | regla | 81 % | 91 % | 18 de 32 | 3 de 140 |
| marca | rappi | 97 % | 97 % | 0 de 1 | 0 de 37 |
| marca | regla | 99 % | 99 % | 0 de 1 | 1 de 98 |
