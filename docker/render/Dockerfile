# The public gateway for the Render Blueprint (render.yaml).
FROM caddy:2.10.2-alpine

COPY Caddyfile /etc/caddy/Caddyfile

CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
