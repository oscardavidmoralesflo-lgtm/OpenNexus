# Workspace domain

Serve the whole workspace (sign-in, dashboard and every client portal) on an
address with your brand.

## Branded subdomain

Set `WORKSPACE_BASE_DOMAIN=app.example.com` and point a wildcard DNS record
(`*.app.example.com`) at the gateway. The agency is then reachable at
`<agency identifier>.app.example.com` with no further setup. It is shown under
**Settings → Domain → Branded sign-in URL**.

## Your own domain

1. In **Settings → Domain**, enter a subdomain you control, such as
   `app.your-agency.com`, and save.
2. Create the two DNS records shown: a `CNAME` to the gateway host
   (`WORKSPACE_CNAME_TARGET`, or the host of `FRONTEND_URL`) and a `TXT` record
   at `_opennexus-challenge.<domain>` with the value shown.
3. Click **Verify**. Once the TXT record is found, the domain is routed and the
   certificate is issued on the first visit.

The tab reports ownership, SSL and DNS (whether the domain resolves to the
same addresses as the gateway). **Check again** re-reads DNS.

## Gateway

Certificates for these hosts are issued on demand by the opt-in
`docker/Caddyfile.ondemand`, which asks `GET /api/public/tls-ask?domain=…`
before issuing. It answers `2xx` only for a verified client portal domain, a
verified workspace domain or an agency's branded subdomain. See
[Self-hosting](self-hosting.md) for enabling it.
