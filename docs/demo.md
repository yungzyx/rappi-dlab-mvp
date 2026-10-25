# Guion de demo del MVP

Unos 12 minutos para mostrar el prototipo final a una persona del negocio: cómo la Home aprende de cada persona, cómo Mochi propone la siguiente vertical siguiendo la escalera de combinaciones, cómo cruza verticales al buscar y cómo invita a descubrir las que la persona no usa. Se hace con el MVP corriendo (`make mvp`): la app no abre sin la API.

## Antes de empezar

En una terminal del equipo donde está la base, desde la raíz del repositorio:

```bash
make mvp             # esperar «MVP listo: app http://localhost:5174 · panel …» (la API carga los modelos antes)
make mvp LAN=1       # si se muestra desde un celular en la misma red (solo en una red de confianza)
```

Si la app muestra **«Sin conexión con Mochi»**, la API todavía no terminó de cargar o no está corriendo: espera a «MVP listo»: la pantalla vuelve a probar sola cada 2 s y **Reintentar** prueba al instante. Qué más revisar: [instalación](instalacion.md#5-el-mvp). Antes de una presentación, `make mvp-check` comprueba que la app y la API se hablan, contra un catálogo de prueba inventado y sin tocar la base real (qué revisa, en [instalación](instalacion.md#5-el-mvp)); no lo corras junto con pytest directo; con make test, el segundo en empezar se niega.

1. Abre el prototipo (http://localhost:5174) y deja el modo **Prototipo final** (arriba a la izquierda; la tecla **D** alterna con «Rappi hoy», la app como es hoy).
2. Justo antes de presentar, con la API arriba: `cd rappi-ia && make warm`. Pasa por los botones del guion sin registrarlos: en frío la primera respuesta tarda de 2 a 5 s; después, menos de medio segundo. Repetirlo si la API pasó un rato sin uso.
3. Para empezar sin rastros de pruebas anteriores, toca la barra de la Home («¿Qué se te antoja hoy?») para abrir el buscador con Mochi y, arriba, en «Aprendiendo de ti», toca **Olvidar** (o, en Cuenta, **Borrar mis datos**) y confirma con **Sí, borrar**: borra en la API el perfil, los eventos y los pedidos, vacía lo que la app guardó en este navegador y la recarga en la Home, como la primera vez (vuelve el aviso de privacidad: «Entendido»). El botón aparece siempre, aunque Mochi todavía no haya aprendido nada.

## Recorrido

Dos partes: primero la Home y el motor (lo que salió de la conversación con el equipo de Rappi), después el buscador con Mochi.

### 1. La Home y el motor (unos 5 minutos)

Para partir de cero: **↺ Repetir escena** (junto al interruptor, arriba a la izquierda), con **Olvidar** recién hecho.

| # | Qué tocar | Qué mostrar | Qué decir |
|---|---|---|---|
| 1 | Nada: la Home recién abierta. | Mochi entra caminando y saluda. La primera vez hace una guía de 2 pasos: el buscador y qué pasa al tocarla (**Siguiente** / **Saltar**). Los accesos están en el orden fijo, con Lealtad y Beneficios Pro al final y sin leyenda. | Mochi es parte de la Home, no un canal aparte. |
| 2 | Un acceso pequeño (por ejemplo **Rappi Mall**) y volver a la Home. Con una vez basta. | Ese acceso sube al primer lugar y aparece «Ordenadas según lo que más usas». | La Home se ordena sola con lo que cada persona pide y abre. Restaurantes y Turbo no se mueven, Lealtad y Beneficios Pro quedan al final y «Rappi hoy» (tecla **D**) no aprende. |
| 3 | Tocar a Mochi y, en su globo, **¿Por qué?** | Propone una vertical donde la persona aún no pide: «¿Y si pruebas algo de …?», con un botón para abrirla y **Después**. «¿Por qué?» dice «Porque aún no pides en …». Si no tiene nada que ofrecer, calla. | Abrir una vertical no es pedir en ella: Mochi propone según los pedidos, y siempre dice por qué. |
| 4 | **Restaurantes** → un restaurante → un plato → pagar. Volver a la Home y tocar a Mochi. | Ahora propone **Turbo**: «¿Y si pruebas algo de Turbo?», con **Abrir Turbo** y **Después**. «¿Por qué?» dice la razón: hoy, «Porque aún no pides en Turbo: esto es lo que más se pide.» (con una regla de compra cruzada activa sería «Porque pides …. Para acompañar: …, en ….»), sin afirmar lo que hace la población. | La sugerencia sigue una escalera, Restaurantes → Turbo → Retail y después vertical por vertical, que parte de la tabla de combinaciones que compartió Rappi: quienes combinan las tres vuelven el 93 % al mes siguiente, frente al 47 % de quienes solo piden en Restaurantes. Es una correlación, no un efecto: quien pide mucho usa más verticales y además vuelve más. El efecto real se mide con un grupo de control. Si ya pidió en esa vertical hace más de un mes, «¿Por qué?» dice «Porque hace más de un mes que no pides en …». |
| 5 | Opcional: pedir una vez en **Turbo** y tocar de nuevo a Mochi. | El paso siguiente es Retail, en la vertical de retail que el motor pone primero para la persona. Con Restaurantes + Turbo + Retail la escalera no se detiene: sigue con otra vertical de Retail (súper, Express, Mall o Chocolatería) y, cuando la persona ya usa todas las que Mochi puede ofrecer, propone **RappiFavor** y después **RappiTravel** («¿Conoces RappiFavor? …», sin productos, con un botón a su pantalla). | El camino avanza con lo que la persona hace, vertical por vertical. Dentro de un grupo, que cada vertical extra retenga algo más es un **supuesto propio** (cada vez menos: 10 %, 5 %, 2,5 % de la parte que no vuelve), no un dato de Rappi; con datos reales lo reemplaza lo aprendido. Farmacia y Licores nunca se proponen. |
| 6 | Bajar hasta **¿Qué plan tienes hoy?** (cinco ocasiones) y elegir **Carrete**. | Un kit de varias verticales con un solo botón. Como la persona eligió la ocasión, puede traer alcohol, con la marca **+18**. | En lo que Mochi ofrece por su cuenta nunca hay alcohol, farmacia, bebé ni salud. |

**Si preguntan por la compra cruzada («Porque pides …. Para acompañar: …»):** solo aparece cuando el λ del motor es mayor que 0. Hoy, con la población simulada, la validación lo deja en 0 y la razón es «Porque aún no pides en …: esto es lo que más se pide.»

**La recompra («¿Repetimos …?»):** una persona que pide el mismo concepto con ritmo (por ejemplo, café cada 14 días) ve, cuando le toca, el bloque «¿Repetimos …? Pides cada N días.» en la Home, después de los accesos, con **Ver producto**. Necesita tres compras del concepto en días distintos y un ritmo regular, así que con una cuenta nueva no sale en la demo: se cuenta con la [captura de ejemplo](../prototipo-app/docs/screenshots/21-recompra.jpg). Se cuenta como aceptada cuando la persona agrega el producto al carro, no al tocar el botón.

**Volver a pedir («¿Volvemos a …?»):** si no le toca la recompra, el mismo bloque invita a volver a lo que la persona pedía con ritmo y dejó: un concepto atrasado más de un intervalo (14 a 90 días), «¿Volvemos a café? La última vez que pediste café fue hace 20 días.», o una vertical que dejó hace más de un mes mientras pide en otra. Necesita semanas de pedidos, así que con una cuenta nueva no sale (ni en la demo sin conexión). **Qué decir:** apunta a la retención; Mochi no insiste: una invitación por semana y, con dos «Después», no la repite. En el panel, «A quién invitar a volver» dice cuántas personas califican (con datos simulados, «Simulado: no es evidencia»).

### 2. El buscador con Mochi (unos 6 minutos)

En el prototipo final la barra de la Home abre el buscador con Mochi. El campo de arriba («Busca o pregúntale a Mochi») busca tiendas y productos y, si lo escrito parece una pregunta, se la hace a Mochi; las ideas de Mochi están en los botones de «Toca y te armo algo».

| # | Qué tocar | Qué mostrar | Qué decir |
|---|---|---|---|
| 1 | La barra de la Home y, en «Toca y te armo algo», **🍻 Arma un carrete** | Va directo a Express sin preguntar: snacks, bebidas y hielo, sin alcohol, porque la persona no lo pidió (el kit «Carrete» de la Home sí lo trae, con +18). Con la API, productos reales del catálogo, la sugerencia de otra vertical aparte y la fila **«También en»** (otras verticales con tiendas reales). | Entiende ocasiones, no solo productos. El mismo concepto existe en varias verticales: hoy cada una lo muestra por separado. |
| 2 | **🍔 ¿Qué almuerzo hoy?** | Solo restaurantes que llegan rápido, sin mezclar con lo anterior. | La búsqueda no se mezcla: responde en su vertical. |
| 3 | Arriba, «Aprendiendo de ti» muestra lo que Mochi notó de la persona (el perfil lo arma el servidor con sus eventos); **Olvidar** lo borra. | Los conceptos aprendidos, sin los sensibles. Tras **Olvidar**, la app se recarga en la Home y la lista parte de cero. | Cada toque enseña y la persona puede borrarlo: la memoria es transparente. |
| 4 | Un producto de la respuesta → en la tienda, bajo **«Lo que elegiste»**, tócalo de nuevo. | Se abre la hoja del producto: cantidad, notas para la tienda y el total. **Agregar.** | Lo que Mochi recomienda se compra con el mismo flujo de la app, sin salir a otra pantalla. |
| 4b | Volver con la flecha del buscador. | El buscador con Mochi se reabre donde estaba, con la misma respuesta. | Mochi no es otro canal: es parte del buscador, y se vuelve a él como a cualquier pantalla. |
| 5 | Abre el carro, revisa y recarga la página. | El carro sigue ahí (se guarda en el navegador). **Ir a pagar** → delivery o retiro, propina y desglose → pagar. | El pedido se confirma; el pago es un texto de ejemplo. |
| 5b | **Cuenta → Pedidos** (o «Ver todos» en Pedidos recientes) | **Mis pedidos**: el pedido recién hecho con su seguimiento en curso; al tocarlo, el mapa con Mochi recorriendo la ruta. | El seguimiento avanza solo, para la demo. |
| 6 | De vuelta en el buscador con Mochi, baja hasta **Descubre con Mochi** y toca una tarjeta. | La tarjeta dice por qué la propone (un complemento de lo que le gusta a la persona, de una vertical que quizá no abre) y abre esa vertical. | Lo aprendido también sirve para llevar a la persona a verticales donde nunca pidió. |
| 6b | En la Home, el acceso **Turbo**. | Los pasillos de la tienda Turbo (pestañas arriba) con sus productos reales y «Ver más», que se agregan al carro. | Opcional: muestra que la compra rápida también vive en el prototipo. |
| 6c | En la Home, un acceso de vertical (**Súper**, **Licores**…) → una tienda → **Ver más**. | Las tiendas reales de la vertical, la tienda con sus pasillos y precios vigentes, y la página siguiente de productos; en Licores, la marca **+18**. | Opcional: las pantallas de siempre, pero con el catálogo real. |
| 7 | En el buscador con Mochi, escribe **chela**. | No hay resultados con esa palabra, pero Mochi dice dónde sí hay lo que se buscaba («… sí hay en Licores») y **Ver en Licores** lleva ahí. | Un «sin resultados» no termina en un callejón sin salida: Mochi entiende el tema. |
| 7b | En el buscador con Mochi, escribe **cerveza**. | La API busca en todas las verticales y muestra **un grupo por vertical** (Licores, Express, Súper…), con «Ver más» en cada uno y la marca **+18**. Con el buscador abierto desde una vertical, esa va primero. | Un mismo producto se encuentra en varias verticales, sin elegir una antes. |
| 7c | En el buscador con Mochi, escribe **¿qué llevo para un asado de 6?** y Enter. | La primera fila, resaltada, dice «Pregúntale a Mochi «…»». La respuesta sale en la tarjeta de Mochi con «Preguntaste «…»»: carne para asado del catálogo y «Para 6 personas, calcula unos 2,1 kg de carne». | A Mochi también se le escribe: una pregunta, una respuesta, con productos reales y su razón. Lo entienden reglas, no un LLM. |
| 7d | Escribe **mi hijo tiene fiebre, ¿qué le doy?** y Enter. | Mochi no muestra remedios ni aconseja: nombra al médico, al químico farmacéutico o al pediatra, el SAMU (131) si es urgente, y deja **Ir a Farmacia**. | Mochi no da consejo médico. |
| 8 | En el checkout, toca **¿Me falta algo? Pregúntale a Mochi**. | Una sola sugerencia de otra vertical con su razón («Para completar lo que llevas: …, en …»), **Agregar** y **Deshacer**. Nunca trae alcohol, farmacia, bebé ni salud: Mochi no los propone por su cuenta. | Mochi sugiere cuando se le pide, en el momento en que más sirve, y sin empujar lo delicado. |

Los productos y precios salen del catálogo real y la sugerencia de otra vertical la decide Mochi en el servidor; la búsqueda también es de la API. Las pantallas de catálogo (verticales, tiendas, restaurantes con su menú, Turbo, Ofertas, Favoritos y la Home) leen el mismo catálogo. No hay respaldo local: si la API se cae a mitad de la demo, el buscador con Mochi dice «Sin conexión» con **Reintentar**, que vuelve a mandar la misma pregunta, y las ofertas que Mochi hace solo callan. Los botones **🍫 Algo dulce**, **🎁 Un regalo** y **🔥 Ofertas de hoy**, y el campo de búsqueda (con «Search ideas», que son ideas fijas y no un historial, y «Popular stores», como en la app) quedan para preguntas del público.

### El panel con lo que acaba de pasar (2 minutos, opcional)

Con `make mvp` el panel ya está arriba. Después de la demo de la app, ábrelo en [http://localhost:5175/?vista=mochi&fuente=prototipo](http://localhost:5175/?vista=mochi&fuente=prototipo) (o elige **Prototipo** arriba y la pestaña **Mochi y búsquedas**; **Actualizar** vuelve a pedir lo nuevo sin recargar).

1. **Lo que ofrece Mochi, por momento:** el kit de «Carrete» aparece en **Plan**, lo que propuso Mochi al tocarlo en **Vertical por probar** y, si usaste el carro o el checkout, en **Carro** y **Antes de pagar**, con lo mostrado y lo aceptado (una recompra aparecería en **Recompra** y una invitación a volver, en **Volver a pedir**). **Qué decir:** así se ve en qué momento la oferta de Mochi funciona; el porcentaje aparece recién con 10 mostradas, antes solo las cuentas.
2. **Qué buscan y no encuentran:** una búsqueda sin resultado en la app (por ejemplo, algo que el catálogo no tiene) suma a su vertical; el concepto solo se suma si la pregunta pasó por el agente (las búsquedas de la app no llevan concepto). Nunca se ve lo que se escribió.

**Qué decir:** cada sección lleva el rótulo «uso del MVP, pocas personas: no es evidencia». Son las pruebas de unas pocas personas, no una medición, y nunca se mezclan con los datos simulados. «Olvidar» en la app borra también los eventos de esa persona.

Para cerrar, con la fuente **Simulados**, abre el **Resumen**: las cuatro preguntas para la gerencia y RappiAds, cada una con su cifra, su comparación y una acción sugerida. **¿Dónde está la venta cruzada?** lleva a **Retención y venta cruzada**, donde la tabla de Rappi se ve como escalera: el 62,6 % de los usuarios solo pide en Restaurantes y vuelve el 47 % al mes siguiente; quienes además piden en Turbo, el 82 %. **Qué decir:** es el dato de Rappi y el punto de partida del motor, una correlación y no un efecto; el resto de las cifras son simuladas y muestran la mecánica, no evidencia.

## Qué aclarar si preguntan

- **De dónde salen los productos:** del catálogo público de rappi.cl (muestra de hasta 24 productos por sub-pasillo), con precios vigentes. Un producto muestra el precio y la tienda de su oferta vigente más barata entre las tiendas que se pueden abrir, así que no siempre es el mínimo absoluto.
- **Ofertas:** son productos con una rebaja que marca la tienda o una baja de precio respecto de la descarga anterior, sin las de más de 60 % (en la base real eran graneles: precio por kilo contra precio por unidad). No hay «Envío más barato»: el costo de envío es $0 en el 91 % de la base, casi seguro «sin dato», así que la Home y Ofertas muestran «Mejor evaluados».
- **Por qué no está Mascotas:** la base no tiene esa vertical, así que salió de los accesos y de las pantallas.
- **Por qué no siempre sale Restaurantes:** la vertical se elige donde el concepto es típico, no donde hay más ítems; restaurantes solo compite en lo que se pide hecho (comida, postres, café). Una vertical chica tampoco gana con un puñado de productos: necesita oferta suficiente. Ver [decisiones.md](decisiones.md#agente-mochi).
- **Cómo se mediría el efecto:** la API ya registra cada sugerencia mostrada, aceptada y convertida en pedido (eventos seudónimos). Con datos de Rappi y un experimento A/B con grupo de control se mide si sube la frecuencia y cuántas verticales usa cada persona.
- **Qué va con qué:** hay dos fuentes. Los complementos curados (hamburguesa → gaseosas, vino → quesos) son una lista escrita a mano y deciden la sugerencia del carro y del checkout. Las reglas de compra cruzada del motor («quien pide A en una vertical pide B en otra») se aprenden de la población, hoy simulada, y se mezclan con lo más pedido en la vertical por probar. Con pedidos de Rappi se cambia la población (`MOTOR_POBLACION`) y las reglas pasan a ser relaciones medidas, sin cambiar el mecanismo.
- **De dónde sale la escalera:** de la tabla de combinaciones que compartió el equipo de Rappi (cohortes de enero a junio de 2026), con una agrupación gruesa propia: `rest` (Restaurantes), `turbo` (Turbo) y `retail` (todo el comercio que no es restaurante ni Turbo), mezclada con lo aprendido de la población (hoy simulada; por eso el orden entre grupos puede cambiar con otra población). Dentro de cada grupo sigue vertical por vertical con un supuesto propio de rendimiento decreciente, y al final suma RappiFavor y RappiTravel. Detalle en [capa-de-datos.md](capa-de-datos.md#la-escalera-fina).
