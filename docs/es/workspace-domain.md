# Dominio del espacio de trabajo

Sirve todo el espacio de trabajo (acceso, panel y el portal de cada cliente) en
una dirección con tu marca.

## Subdominio con tu marca

Define `WORKSPACE_BASE_DOMAIN=app.ejemplo.com` y apunta un registro DNS comodín
(`*.app.ejemplo.com`) al gateway. La agencia queda disponible en
`<identificador de la agencia>.app.ejemplo.com` sin más pasos. Se muestra en
**Configuración → Dominio → URL de acceso con tu marca**.

## Dominio propio

1. En **Configuración → Dominio**, escribe un subdominio que controles, como
   `app.tu-agencia.com`, y guarda.
2. Crea los dos registros DNS que se muestran: un `CNAME` al host del gateway
   (`WORKSPACE_CNAME_TARGET`, o el host de `FRONTEND_URL`) y un registro `TXT`
   en `_opennexus-challenge.<dominio>` con el valor indicado.
3. Pulsa **Verificar**. En cuanto se encuentra el TXT, el dominio se enruta y el
   certificado se emite en la primera visita.

La pestaña informa propiedad, SSL y DNS (si el dominio resuelve a las mismas
direcciones que el gateway). **Comprobar de nuevo** vuelve a leer el DNS.

## Gateway

Los certificados de estos hosts los emite bajo demanda el
`docker/Caddyfile.ondemand` opcional, que consulta
`GET /api/public/tls-ask?domain=…` antes de emitir. Responde `2xx` solo para un
dominio de portal verificado, un dominio de espacio de trabajo verificado o el
subdominio con marca de una agencia. Consulta
[Autoalojamiento](self-hosting.md) para activarlo.
