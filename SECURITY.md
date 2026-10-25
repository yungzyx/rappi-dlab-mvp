# Seguridad

rappi-dlab es un prototipo con una demo cerrada, no un servicio en producción. Aun así, un problema de seguridad se reporta en privado y se arregla con prioridad.

## Cómo reportar

- **En privado:** escríbele al mantenedor ([@yungzyx](https://github.com/yungzyx) en GitHub) o usa el canal acordado entre Rappi y el equipo del proyecto. **No abras un issue ni un PR** con el detalle: el repositorio lo ven más personas.
- **Qué incluir:** qué parte afecta (`rappi-ia`, `rappi-scraper`, `prototipo-app`, `dashboard-empresa` o `deploy/`), cómo reproducirlo, qué permite (leer o borrar datos de otra persona, saltarse la puerta de acceso, ejecutar código…) y, si lo sabes, desde qué versión o commit.
- **Qué pasa después:** el mantenedor confirma que lo recibió, acuerda contigo cuándo publicar el arreglo y lo publica con un test que reproduce el problema.

Si encuentras una clave o un secreto en el repositorio o en su historial, avísalo de la misma forma: hay que rotarlo, además de borrarlo.

## Qué está dentro del alcance

- La API (`rappi-ia`): identidad firmada (`POST /session`, `X-User-Token`), acceso a los datos de cada persona, `/analytics`, límites de tamaño y de tiempo de las consultas.
- El despliegue (`deploy/`): Caddy con TLS y la puerta de usuario y clave, roles de la base (`rappi_api` y `rappi_owner`), respaldos y archivo de entorno.
- La app y el panel: lo que se guarda en el navegador y lo que se manda a la API.
- El scraper: cualquier forma en que descargue algo más que páginas públicas, o más rápido que el ritmo acordado.

## Lo que ya se sabe (no hace falta reportarlo)

- **En local, la API no tiene puerta de acceso.** `make mvp` escucha solo en el equipo local; con `LAN=1` o `make serve-lan` se abre a la red, y eso se hace solo en una red de confianza. En un servidor, todo el sitio va detrás de la puerta de Caddy ([docs/despliegue.md](docs/despliegue.md)).
- **Los tokens de sesión no vencen.** El token firma el id seudónimo de cada persona con `API_SECRET`; rotar `API_SECRET` invalida a todas las personas. Basta para una demo cerrada.
- **No hay cuentas ni pagos reales.** El pago y el seguimiento del pedido son simulados.

## Datos

- **Personas:** solo simuladas (`source = 'synthetic'`) o del prototipo (`'prototype'`, con id seudónimo del navegador y sin cuenta). Las consultas se guardan con los datos personales redactados (correo, RUT, tarjetas, teléfonos) y su texto se borra a los 90 días; la persona borra lo suyo con «Borrar mis datos».
- **Secretos:** solo se versionan los `.env.example`, y el CI revisa los archivos versionados con gitleaks. `API_SECRET`, las claves de la base, `ANTHROPIC_API_KEY`, `TYPESAFE_API_KEY` y las de restic viven en los `.env` locales o en `/etc/rappi/rappi.env` del servidor, nunca en git.
- **Catálogo:** el contenido descargado de rappi.cl no se versiona; viaja en un respaldo de la base por un canal acordado.

## Descarga del catálogo

El scraper lee solo páginas públicas de rappi.cl, una a la vez, con pausas de 1,5 a 3 s. Se presenta con su propio User-Agent (`rappi-dlab-scraper`, con un contacto en `RAPPI_UA_CONTACT`), respeta robots.txt y se detiene ante una página no permitida o ante señales de bloqueo. En un servidor, la descarga semanal viene apagada. Si Rappi quiere que se detenga, que cambie su ritmo o que se identifique de otra forma, basta con avisar por el mismo canal: detalle en [rappi-scraper/README.md](rappi-scraper/README.md).
