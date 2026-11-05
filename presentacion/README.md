# Presentación del MVP

Dos HTML de un solo archivo para mostrar el MVP sin API ni internet, con los controles de la demo a mano y un recorrido automático por capítulos:

- **"Mochi MVP - Presentación.html"**: para un notebook o un proyector. Al centro, "Prototipo MVP.html" tal cual; a la izquierda, la vista (MVP con Mochi o Rappi hoy, también con la tecla D), primero los perfiles de gusto (fichas con su emoji) y después las otras personas del "Panel de la demo", la línea de la escalera ("Hoy: … → siguiente: …") y, en "Simular", "+1 visita a…" (cierra el buscador si estaba abierto, para que se vea a Mochi mover los accesos), "Borrar historial", "Atrasar el pedido en curso" y, en el MVP con Mochi, "Ocultar a Mochi" o "Mostrar a Mochi" (el mismo botón, sin confirmar: vuelve a la Home para que se vea); a la derecha, el panel de negocio, el recorrido automático, sus capítulos y Parar.
- **"Mochi MVP - iPhone y iPad.html"**: la app a pantalla completa, con una barra abajo (la persona elegida, el recorrido y un menú) y una hoja con las mismas opciones.

Los botones de la presentación tocan los de la app: el interruptor de modo y el "Panel de la demo" quedan ocultos dentro del iframe y la presentación los muestra a los lados. Elegir una persona a mano abre el buscador con Mochi, lo que Mochi le muestra a esa persona; con un perfil de gusto, además pasea su escalera "Para ti en otras verticales". Un toque, una tecla o la rueda dentro de la app detiene el recorrido.

## Capítulos del recorrido

1. La Home que aprende: Mochi se presenta, los accesos ordenados por uso (y "+1 visita", con la que Mochi los mueve y dice por qué), la vertical que Mochi propone con su "¿Por qué?".
2. El buscador con Mochi: "¿Repetimos?", el perfil de gusto con su "¿Por qué?" y su saludo, la escalera por verticales (hasta RappiTravel) y agregar una idea al carro.
3. Por necesidad o por plan: "¿Qué llevo para un asado de 6?", el chip "Más barato" y el kit de "¿Qué plan tienes hoy?".
4. "¿Volvemos a…?" y Ofertas.
5. Carro, pago y seguimiento, con el atraso simulado.
6. Preferencias y "Pedir por mí".
7. Cambiar de persona: asiático, café y mascotero.
8. Rappi hoy frente al MVP.
9. El panel de negocio: Resumen, Retención y venta cruzada, Mochi y búsquedas (con "¿Mochi molesta?").

Cada capítulo elige su persona (que borra lo de antes) o sigue con lo que dejó el anterior; si algo no aparece, el paso se salta y queda en la consola del navegador ("Paso saltado").

## Lo que no hay sin conexión

La app de la presentación responde con una API simulada en el navegador y una muestra del catálogo ([prototipo-app/README.md](../prototipo-app/README.md#demo-sin-conexión-prototipo-mvphtml)). Lo que se muestra fuera del recorrido puede salir distinto que en dlab-mvp.com:

| En dlab-mvp.com | Sin conexión |
|---|---|
| Corrige las faltas de tipeo del buscador y de Mochi | Solo las grabadas: las del set `rappi-ia/src/rappi_ia/eval/typos.json` en el buscador, y "cervesa", "quiero cervesa" y "pizaa" en el buscador y en Mochi. Lo demás se busca tal cual; si no encuentra nada, el buscador dice "Demo sin conexión: busca solo en una muestra y no corrige faltas de tipeo; en dlab-mvp.com sí." |
| Búsqueda semántica en todo el catálogo | Por palabras en la muestra, salvo las búsquedas y preguntas grabadas, que salen tal cual las respondió la API |
| "Lo que sea" (pedir con RappiFavor lo que no se encontró) | No aparece |
| Tiendas y restaurantes que se llaman como lo buscado | Solo en las búsquedas grabadas, y la mayoría no está en la muestra: al abrirlos, no cargan |
| Comparar un producto entre tiendas ("Mejor precio", "Más rápido") | No aparece |
| "Para ti" dentro de una tienda | No aparece |
| Lo que aprende la población (compra cruzada, "Lo más buscado") | No se aprende: lo de la población llega como quedó en las respuestas grabadas, y "Lo más buscado" no aparece; lo de la persona sale de lo que hace en este navegador |

## Armarla

Hacen falta las dos muestras grabadas (ignoradas en git): `prototipo-app/src/api/offline/snapshot.json` (con `npm run demo:snapshot`) y `dashboard-empresa/snapshot/panel.json` (con `npm run panel:snapshot`), las dos desde una API sobre `rappi_staging` en otro puerto, nunca sobre `rappi` ni el 8000 (ver [prototipo-app/README.md](../prototipo-app/README.md#demo-sin-conexión-prototipo-mvphtml) y [dashboard-empresa/README.md](../dashboard-empresa/README.md#panel-en-un-solo-html)). Con ellas:

```bash
make presentacion                                            # desde la raíz: demo:html, panel:html y build.mjs
PRESENTACION_COPY="$HOME/Desktop/Mochi MVP" make presentacion  # además, una copia de los dos HTML en esa carpeta
```

Escribe `presentacion/dist/` (ignorada en git: lleva la muestra del catálogo y sus fotos). Si "Prototipo MVP.html" y "Panel de negocio (demo).html" ya están armados, `node presentacion/build.mjs` basta.

## Cómo está hecha

- `escritorio.html` y `movil.html`: las dos plantillas (el marco, su CSS y la hoja del menú táctil).
- `recorrido.js`: lo común a las dos (los controles que tocan los de la app, el panel de negocio y el recorrido con su guion por capítulos).
- `shim.js`: se inyecta al inicio de la app y del panel. Guarda `localStorage` y `sessionStorage` con un prefijo propio ("mvp:", "panel:"; también `length`, `key()` y `Object.keys()`, que la app recorre al cambiar de persona) y les da un historial en memoria, para que el "atrás" de la app no mueva la página de la presentación.
- `build.mjs`: inyecta `shim.js` (y el estilo que oculta los controles de la demo) en los dos HTML, los mete como texto en `const PROTOS = {mvp, panel}` de cada plantilla (cada uno se abre en un iframe con `srcdoc`) junto con `recorrido.js`, y escribe los dos archivos.

Si cambian las clases de la app que usa el guion (`.smart-bar`, `.taste-rail`, `.live-card--repeat`, `.offline-demo-panel`…), el recorrido salta esos pasos: se revisa en `recorrido.js` (`CHAPTERS`).
