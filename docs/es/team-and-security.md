# Equipo y seguridad

## Equipo

**Configuración → Equipo** lista a todas las personas que trabajan en el espacio.
Los propietarios y administradores invitan: la invitación es un enlace privado
que funciona una vez y vence en 7 días. Compártelo por un canal de confianza;
quien lo abre elige nombre y contraseña y entra con el rol que elegiste.

| Rol | Puede |
|---|---|
| Propietario | Todo, incluida la facturación y gestionar propietarios y administradores. |
| Administrador | Clientes, agentes, canales, claves, tokens de agentes de IA y el equipo, salvo facturación y otros administradores. |
| Operador | Atiende la bandeja (responder, tomar el control, resolver, playground) y lee lo demás. |
| Lector | Lee clientes, agentes, conversaciones y reportes. |

La API aplica el rol en cada solicitud del panel, así que una ruta nueva queda
cubierta sin código extra. La agencia siempre conserva al menos un propietario.
Un miembro quitado pierde el acceso al instante, junto con los tokens MCP que
creó; los tokens MCP de operadores y lectores solo pueden leer.

## Verificación en dos pasos

**Configuración → Seguridad** activa códigos temporales (TOTP) con cualquier app
de autenticación: escanea el QR, confirma un código y guarda los 10 códigos de
recuperación (cada uno sirve una vez). Desde entonces, el acceso pide un código
después de la contraseña; un código no se puede reutilizar. Desactivarla pide la
contraseña y un código.

Un propietario puede **exigir la verificación en dos pasos** a todo el equipo en
**Configuración → Equipo → Política de seguridad**. Quien no la tenga es enviado a
Seguridad y no puede usar nada más hasta configurarla.

## Instalación inicial

Define `SETUP_TOKEN` en un despliegue público: el formulario inicial lo pide, así
nadie más puede reclamar la instalación antes que tú.
