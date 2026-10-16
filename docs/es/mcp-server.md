# Agentes de IA por MCP

OpenNexus también es un servidor [MCP](https://modelcontextprotocol.io). Claude
Code, Cursor, Codex o cualquier cliente MCP puede conectarse a tu espacio de
trabajo y hacer lo mismo que haces en el panel: leer clientes y agentes, crear y
afinar agentes, cargar conocimiento, conectar herramientas y probar respuestas.

## Conectar un agente

1. Abre **Configuración → Agentes de IA** y pulsa **Crear token**. Ponle el
   nombre de la máquina que lo usará. Marca **Solo lectura** para un token que
   puede listar y leer pero nunca cambiar nada ni gastar crédito.
2. Copia el token: se muestra una sola vez y solo se guarda su hash SHA-256.
3. Agrega el servidor a tu cliente. La pestaña muestra el snippet de cada uno:

```bash
claude mcp add --transport http opennexus https://app.tu-agencia.com/api/mcp --header "Authorization: Bearer onx_…"
```

Cursor (`.cursor/mcp.json`):

```json
{ "mcpServers": { "opennexus": { "url": "https://app.tu-agencia.com/api/mcp", "headers": { "Authorization": "Bearer onx_…" } } } }
```

## Herramientas

| Herramienta | Modifica datos | Qué hace |
|---|---|---|
| `list_clients`, `list_agents`, `get_agent` | no | Lee el espacio de trabajo; `get_agent` puede incluir el prompt del sistema. |
| `list_knowledge`, `list_agent_tools`, `list_models` | no | Documentos y preguntas de conocimiento, herramientas conectadas, modelos disponibles. |
| `create_client`, `create_agent`, `update_agent` | sí | Con la misma validación que el panel. |
| `add_knowledge_text`, `add_qa` | sí | Conocimiento en texto o Markdown (indexado para la búsqueda), respuestas exactas. |
| `connect_tool` | sí | Un endpoint HTTP o un servidor MCP que el agente llama al responder. |
| `test_agent` | sí | Un mensaje como cliente; pasa `conversation_id` para continuar. Se cobra como cualquier respuesta. |

Cada herramienta llama a la misma ruta que usa el panel, como la persona dueña
del token, así que las comprobaciones de propiedad y los efectos son idénticos.

## Registro de actividad y revocación

Cada llamada queda en **Registro de actividad**: cuándo, con qué token, qué
herramienta, sus argumentos (el texto largo, recortado) y el resultado.
**Revoca** un token en cuanto dejes de confiar en la máquina que lo tiene; deja
de funcionar al instante.

## Protocolo

HTTP transmitible, sin estado, respuestas JSON: `POST /api/mcp` con un mensaje
JSON-RPC o un lote. Se admiten `initialize`, `ping`, `tools/list` y
`tools/call`; las notificaciones reciben `202`. Un token ausente o revocado
recibe `401`.
