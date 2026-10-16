# OpenNexus documentation

Every guide lives here, in the repository, so a change to the product and the
change to its documentation travel in the same pull request. Guides are written
in English and Spanish; code, identifiers and commands stay English in both.

Adding a guide: write `en/<slug>.md` and `es/<slug>.md`, then list it below.

## English

Everything you need to build, brand and operate AI agents for your clients.

**Getting started**

- [Getting started](en/getting-started.md) — Run the full stack with Docker and create your first agency in minutes.
- [Configuration](en/configuration.md) — Environment variables, secrets, ports and gateway settings.

**Concepts**

- [Architecture](en/architecture.md) — The three services, the data model and ownership checks.

**Agents**

- [Agents](en/agents.md) — Instructions, context, models and multimodal capabilities.
- [Knowledge base](en/knowledge-base.md) — Manual context, Q&A pairs, PDFs and semantic retrieval.
- [AI providers](en/ai-providers.md) — Connect your OpenRouter key and pick per-agent models from any vendor.
- [Reports](en/reports.md) — What every reply cost, by client, agent, model and day, with CSV export.
- [Custom tools](en/custom-tools.md) — Let agents call HTTP endpoints and MCP servers during a conversation.
- [AI agents over MCP](en/mcp-server.md) — Connect Claude Code, Cursor or Codex to the workspace with a personal token.
- [Sandbox](en/sandbox.md) — One WhatsApp number where each prospect tries their agent by sending its code.

**Channels**

- [WhatsApp](en/whatsapp.md) — Link one or more numbers per client through the whatsmeow bridge and hand off to a human.
- [WhatsApp Cloud API](en/whatsapp-cloud-api.md) — Connect a number through Meta's official Cloud API: app, token, webhook and going live.
- [Template webhooks](en/template-webhooks.md): an address another system calls to send an approved WhatsApp template that the agent then follows up on.
- [Web chat widget](en/web-widget.md) — Embed an agent on any website with a single snippet.

**Operating**

- [Inbox](en/inbox.md) — Search, filter and take over conversations from AI to human.
- [Client portal & domains](en/client-portal.md) — Give each client a branded portal on its own custom domain.
- [Workspace domain](en/workspace-domain.md) — The whole workspace on a branded subdomain or your own domain.
- [Billing](en/billing.md) — Plans, AI credit and Stripe payments, for operators who host the workspace for an agency.
- [Dashboard](en/dashboard.md) — Activity, top agents and token usage by model.
- [Push notifications](en/push-notifications.md) — The provider seam for mobile push: what ships, what it costs and how to register one.

**Self-hosting**

- [Deploy on Render](en/deploy-render.md) — The whole stack from one Blueprint, private until you claim it with the setup token.
- [Self-hosting](en/self-hosting.md) — Deploy to a server, back up data, upgrade and troubleshoot.
- [Contributing](en/contributing.md) — Run the project locally, the test suites and the conventions.

## Español

Todo lo que necesitas para construir, marcar y operar agentes de IA para tus clientes.

**Primeros pasos**

- [Primeros pasos](es/getting-started.md) — Levanta el stack completo con Docker y crea tu primera agencia en minutos.
- [Configuración](es/configuration.md) — Variables de entorno, secretos, puertos y ajustes del gateway.

**Conceptos**

- [Arquitectura](es/architecture.md) — Los tres servicios, el modelo de datos y las comprobaciones de propiedad.

**Agentes**

- [Agentes](es/agents.md) — Instrucciones, contexto, modelos y capacidades multimodales.
- [Base de conocimiento](es/knowledge-base.md) — Contexto manual, pares de preguntas y respuestas, PDFs y recuperación semántica.
- [Proveedores de IA](es/ai-providers.md) — Conecta tu clave de OpenRouter y elige modelos de cualquier proveedor por agente.
- [Reportes](es/reports.md) — Lo que costó cada respuesta, por cliente, agente, modelo y día, con exportación CSV.
- [Herramientas personalizadas](es/custom-tools.md) — Permite que los agentes llamen endpoints HTTP y servidores MCP durante una conversación.
- [Agentes de IA por MCP](es/mcp-server.md) — Conecta Claude Code, Cursor o Codex al espacio de trabajo con un token personal.
- [Sandbox](es/sandbox.md) — Un número de WhatsApp donde cada prospecto prueba su agente enviando su código.

**Canales**

- [WhatsApp](es/whatsapp.md) — Vincula uno o más números por cliente con el puente de whatsmeow y pasa a control humano.
- [API de WhatsApp Cloud](es/whatsapp-cloud-api.md) — Conecta un número por la API Cloud oficial de Meta: app, token, webhook y salida a producción.
- [Webhooks de plantilla](es/template-webhooks.md): una dirección que otro sistema llama para enviar una plantilla aprobada de WhatsApp que el agente luego continúa.
- [Widget de chat web](es/web-widget.md) — Integra un agente en cualquier sitio web con un único snippet.

**Operación**

- [Bandeja de entrada](es/inbox.md) — Busca, filtra y toma el control de conversaciones de IA a humano.
- [Portal del cliente y dominios](es/client-portal.md) — Dale a cada cliente un portal con su marca en su propio dominio.
- [Dominio del espacio de trabajo](es/workspace-domain.md) — Todo el espacio de trabajo en un subdominio con tu marca o en tu propio dominio.
- [Facturación](es/billing.md) — Planes, crédito de IA y pagos con Stripe, para quien opera el espacio de trabajo para una agencia.
- [Panel](es/dashboard.md) — Actividad, agentes destacados y uso de tokens por modelo.
- [Notificaciones push](es/push-notifications.md) — La costura de proveedores para push móvil: qué trae, qué cuesta y cómo registrar uno.

**Autoalojamiento**

- [Desplegar en Render](es/deploy-render.md) — Todo el stack desde un Blueprint, privado hasta que lo reclamas con el token de instalación.
- [Autoalojamiento](es/self-hosting.md) — Despliega en un servidor, respalda datos, actualiza y resuelve problemas.
- [Contribuir](es/contributing.md) — Ejecuta el proyecto en local, las suites de pruebas y las convenciones.
