# Agenda de citas

Cada cliente tiene una agenda en **Clientes → (cliente) → Agenda**. Con la agenda activa, cada agente de chat de ese cliente puede ofrecer horarios libres, agendar una cita y cancelarla, directamente en la conversación.

## Configurar la agenda

- **Los agentes agendan citas**: activa la agenda. Necesita al menos un día con horario.
- **Horario de citas**: por día de la semana, las horas en que pueden empezar las citas, en la zona horaria del cliente (en **Detalles**).
- **Duración de cada cita**: en minutos. Los horarios libres se ofrecen en esa cuadrícula desde el inicio del horario de cada día.
- **Citas a la misma hora**: cuántas personas se pueden atender a la vez (1 por defecto).
- **Anticipación mínima** y **Agendar hasta**: lo más pronto y lo más lejos que se puede agendar.
- **Lugar o indicaciones**: el agente lo comparte al confirmar y el recordatorio lo incluye.
- **Enviar recordatorio**: un mensaje unas horas antes (24 por defecto) en el mismo chat.

## Qué hace el agente

El agente recibe tres herramientas:

| Herramienta | Qué hace |
| --- | --- |
| `check_availability` | Lista los horarios libres de los próximos días. |
| `book_appointment` | Agenda un horario libre con el nombre de la persona y notas opcionales. |
| `cancel_appointment` | Cancela una de las próximas citas de la persona. |

El agente conoce la fecha y hora actuales del negocio, consulta la disponibilidad antes de ofrecer horarios, confirma día, hora y nombre antes de agendar y nunca dice que la cita quedó agendada si la herramienta no lo confirmó. Para cambiar una cita cancela la anterior y agenda la nueva. También ve las próximas citas de la persona.

El playground ensaya las herramientas con horarios libres reales, pero no agenda nada. Las llamadas telefónicas todavía no agendan.

## Recordatorios

Los recordatorios salen por el canal de la conversación (WhatsApp, WhatsApp Cloud API, Instagram o Messenger) como un texto fijo, así que no cuestan IA. En WhatsApp Cloud API la ventana de 24 horas debe seguir abierta; si no, el recordatorio se omite y la cita muestra el motivo. Una cita agendada dentro de la ventana del recordatorio no lleva recordatorio, porque la confirmación se acaba de enviar.

## Para el equipo

La pestaña **Agenda** lista las citas de los próximos 30 días, quién agendó cada una (un agente o el equipo) y el estado del recordatorio. Desde ahí puedes agendar en los horarios libres, abrir el chat y marcar una cita como asistió, no asistió o cancelada. El equipo puede agendar fuera del horario publicado, pero nunca por encima del cupo de un horario.

## API

- `GET` / `PUT /api/clients/{id}/booking`: la configuración.
- `GET /api/clients/{id}/booking/slots?date=YYYY-MM-DD&days=7`: horarios libres.
- `GET /api/clients/{id}/appointments?from=&to=&status=`: citas.
- `POST /api/clients/{id}/appointments`, `PATCH` / `DELETE /api/clients/{id}/appointments/{appointment_id}`.
