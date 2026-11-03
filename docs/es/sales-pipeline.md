# Embudo de ventas

Cada cliente tiene un tablero de ventas en **Clientes → (cliente) → Ventas**. Cada contacto está en una etapa:

| Etapa | Significado |
| --- | --- |
| Nuevo | Escribió; todavía no se sabe más. Los contactos sin etapa aparecen aquí. |
| Interesado | Mostró interés real: preguntó precios, disponibilidad o cómo comprar. |
| Agendado | Agendó una cita, visita o llamada. |
| Ganado | Compró o pagó. |
| Perdido | Dijo que no o compró en otro lado. |

Arrastra una tarjeta a otra columna, o elige la etapa en la tarjeta. **+ Valor** registra cuánto vale la venta, en la moneda del cliente; cada columna y el encabezado los suman. El botón de chat abre la última conversación del contacto.

## Agentes que lo mantienen al día

Activa **Los agentes actualizan el embudo** y cada agente del cliente (chat y teléfono) recibe la herramienta `update_sales_stage`. El agente conoce la etapa actual del contacto y lo mueve solo cuando la conversación lo muestra con claridad, sin mencionarlo. Puede registrar el valor de la venta cuando la persona lo dice o elige un producto con precio. El playground ensaya la herramienta sin mover a nadie.

Agendar una cita (ver [agenda de citas](booking.md)) pasa a Agendado a un contacto Nuevo o Interesado automáticamente.

## API

- `GET /api/clients/{id}/pipeline?q=`: el tablero, hasta 100 contactos por etapa, con totales y valores.
- `PUT /api/clients/{id}/pipeline/settings` con `{"enabled": true}`.
- `PATCH /api/clients/{id}/pipeline/contacts/{contact_id}` con `stage`, `deal_value` o `clear_value`.
