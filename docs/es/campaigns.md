# Campañas de WhatsApp

Una campaña envía una plantilla aprobada de WhatsApp a muchos contactos de un cliente: una promoción, un recordatorio para todos, un mensaje para recuperar clientes inactivos. Abre **Clientes → (cliente) → Campañas**.

## Qué necesita

- Un número conectado por la **API de WhatsApp (Cloud)**. Meta solo deja que un negocio inicie una conversación con una plantilla aprobada, y solo la API Cloud las envía. Los números vinculados por QR no se ofrecen: los envíos masivos desde ellos hacen que bloqueen el número.
- Una **plantilla aprobada** en la cuenta de negocio de ese número (la pestaña **Plantillas** del cliente las crea y las envía a aprobación; ver [API de WhatsApp Cloud](whatsapp-cloud-api.md)).

## Crear una

1. **Nueva campaña**: ponle nombre y elige el número y la plantilla.
2. Llena cada variable de la plantilla. `{first_name}` y `{name}` se cambian por el primer nombre o el nombre completo de cada contacto; lo demás se envía tal cual. Una plantilla con encabezado de imagen, video o documento pide un enlace público. La vista previa muestra el mensaje como lo vería una contacto llamada Ana.
3. Elige **quién la recibe**: contactos con número de teléfono que no estén bloqueados. Sin filtros va a todos; con etiquetas o etapas de venta (ver [embudo de ventas](sales-pipeline.md)), a los que tengan alguna de las elegidas. El contador en vivo muestra a cuántos llega.
4. **Enviar ahora**, **Programar** para una fecha y hora, o **Guardar borrador**.

Al iniciar una campaña se congela su lista de destinatarios, hasta 10.000. El temporizador de seguimientos la envía en tandas de 60 por minuto. Cada mensaje va al chat abierto del contacto en ese número, o a uno nuevo, guardado como mensaje del agente: cuando alguien responde, el agente ve lo que dijo la campaña y responde como siempre.

## Seguimiento

Cada campaña muestra cuántos se enviaron, entregaron, leyeron, respondieron y fallaron, con el porcentaje sobre los enviados. **Destinatarios** lista cada contacto con su resultado y un enlace al chat. **Detener** frena una campaña programada o en envío; lo que ya salió queda enviado. Si Meta pausa o rechaza la plantilla mientras sale, la campaña vuelve a borrador con el motivo, en vez de fallar con cada contacto.

## Buenas prácticas

Envía campañas solo a personas que aceptaron recibir mensajes del negocio. Cuando muchos bloquean o reportan los mensajes, Meta baja la calificación de calidad del número y puede limitarlo o bloquearlo. Meta cobra cada mensaje de plantilla de marketing a la cuenta de negocio.

## API

- `GET /api/clients/{id}/campaigns` las lista con sus cifras.
- `POST /api/clients/{id}/campaigns/audience` con `{"tag_ids": [], "stages": []}` cuenta a quién llega una audiencia.
- `POST /api/clients/{id}/campaigns` crea un borrador: `name`, `channel_id`, `template_name`, `template_language`, `variables`, `header_value`, `audience`. `PUT /api/clients/{id}/campaigns/{campaign_id}` edita un borrador.
- `POST .../{campaign_id}/start` con un `scheduled_at` opcional; `POST .../{campaign_id}/cancel`; `DELETE .../{campaign_id}`.
- `GET .../{campaign_id}/recipients?status=` lista hasta 500 destinatarios.
