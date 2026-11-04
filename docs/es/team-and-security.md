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

## Contraseña y acceso perdido

**Configuración → Seguridad → Contraseña** cambia tu propia contraseña; pide la actual.

**¿Olvidaste tu contraseña?** en la pantalla de entrada envía por correo un enlace para elegir una nueva, una vez configurado el correo saliente con las variables `SMTP_*` (ver [configuración](configuration.md)). El enlace vence en 30 minutos, sirve una sola vez y deja activa la verificación en dos pasos. La solicitud y el cambio quedan en el registro de actividad.

Sin correo, o si también se perdió el buzón, ejecuta esto en el servidor y entra con la contraseña que imprime una sola vez (el cambio queda en el registro de actividad):

```bash
docker compose --env-file .env.docker exec api python -m app.account_admin users
docker compose --env-file .env.docker exec api python -m app.account_admin reset-password owner@example.com
```

Agrega `--disable-2fa` si también se perdió la app de autenticación; desactiva la verificación en dos pasos de esa persona para que la configure de nuevo.

## Registro de actividad

**Configuración → Actividad** muestra cada cambio hecho en el panel y cada inicio de sesión, del más reciente al más antiguo: cuándo pasó, quién lo hizo, qué cambió y desde qué dirección IP. Los inicios de sesión fallidos de una cuenta real aparecen en rojo. Lo leen owners y admins; operadores y lectores no.

Cada escritura exitosa en la API del panel se registra sola, así que las funciones nuevas quedan cubiertas sin trabajo extra. Se dejan fuera el trabajo de rutina de la bandeja (enviar una respuesta, reaccionar, marcar como leída) y las pruebas que solo verifican una clave. El registro se lee en `GET /api/audit` (filtros `limit`, `offset`, prefijo `action` y correo `actor`).

## Instalación inicial

Define `SETUP_TOKEN` en un despliegue público: el formulario inicial lo pide, así
nadie más puede reclamar la instalación antes que tú.
