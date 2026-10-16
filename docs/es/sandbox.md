# Sandbox

Un solo número de WhatsApp donde cada prospecto prueba el agente que le
armaste. Cada agente del sandbox tiene un código corto; quien lo envía al
número habla con ese agente desde ese momento, y otro código cambia de agente.

## Configurarlo

1. Abre **Sandbox** en el menú lateral. El cliente del sandbox
   (`<Agencia> Sandbox`) se crea la primera vez; nunca cuenta en los clientes
   del plan.
2. **Conectar número** abre los canales del cliente del sandbox. Vincula un
   número con el puente QR o la API Cloud. Te pedirá un agente: elige
   cualquiera, porque responde el agente del código.
3. **Nuevo agente** crea un agente en el cliente del sandbox. Recibe un código
   de 6 caracteres (sin caracteres ambiguos como `0`/`O` o `1`/`I`).

## Compartirlo

**Copiar invitación** copia un mensaje con el nombre del agente, su código y un
enlace `wa.me` que abre el chat con el código ya escrito. La tabla cuenta
cuántos prospectos eligieron cada agente.

## Cómo se enrutan los mensajes

- Un mensaje que contiene un código (como palabra, en mayúsculas o minúsculas)
  conecta ese chat con el agente y recibe una confirmación fija.
- Los mensajes siguientes los responde el agente elegido, con su conocimiento,
  herramientas y modelo. La elección sobrevive a las conversaciones resueltas.
- Un chat que no ha enviado código recibe una explicación fija. No se llama a
  la IA, así que los mensajes sueltos no gastan crédito.
- **Nuevo código** retira el código anterior al instante; los chats ya
  conectados conservan el agente.
