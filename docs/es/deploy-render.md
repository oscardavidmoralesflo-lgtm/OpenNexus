# Desplegar OpenNexus en Render

[`render.yaml`](../../render.yaml) es un Blueprint con todo el stack:

| Servicio | Tipo | Qué es |
|---|---|---|
| `opennexus` | web (público) | Gateway Caddy: `/api/*` a la API, lo demás al frontend. Health check `/healthz`. |
| `opennexus-api` | servicio privado | FastAPI. Ejecuta `alembic upgrade head` en cada arranque. |
| `opennexus-web` | servicio privado | Panel Next.js, portales de clientes y widget. |
| `opennexus-whatsapp` | servicio privado | Puente de WhatsApp; las sesiones viven en el esquema `whatsmeow` de la base. |
| `opennexus-db` | PostgreSQL | Sin conexiones externas (`ipAllowList: []`). |

Solo el gateway es accesible desde internet. Render genera los secretos
(`SECRET_KEY`, `ENCRYPTION_KEY`, `WHATSAPP_BRIDGE_TOKEN`, `SETUP_TOKEN`) en el
grupo `opennexus-secrets`. Nunca regeneres `ENCRYPTION_KEY` cuando ya hay datos:
descifra las claves de IA y las sesiones de WhatsApp guardadas.

## Desplegar

1. Abre `https://dashboard.render.com/blueprint/new?repo=<URL de tu repositorio>`,
   elige la rama y pulsa **Apply**.
2. Cuando pida `FRONTEND_URL`, escribe la dirección del gateway, por ejemplo
   `https://opennexus.onrender.com` (el nombre que Render da al servicio
   `opennexus`), o tu propio dominio cuando lo agregues a ese servicio.
3. Espera a que los cuatro servicios queden en vivo.

## Reclamarlo en privado

La primera visita muestra el formulario de instalación. Pide el **token de
instalación**: copia `SETUP_TOKEN` del grupo `opennexus-secrets`. Sin él nadie
puede crear la agencia, y una vez que la creas, el registro se cierra para
siempre.

## Dominio propio

Agrega el dominio al servicio `opennexus` en **Settings → Custom Domains**, luego
pon ese dominio en `FRONTEND_URL` y vuelve a desplegar la API.

## Costos

Todos los servicios usan el plan `starter` (siempre encendidos; el puente de
WhatsApp no puede dormir) y la base `basic-256mb`. Cambia `plan:` en
`render.yaml` para escalar.
