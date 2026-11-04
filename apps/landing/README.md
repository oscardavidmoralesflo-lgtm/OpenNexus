# Agentaria landing page

The public marketing site for Agentaria: one static page in Spanish (`public/index.html`) and English (`public/en/index.html`). It has no build dependencies and no JavaScript framework, so any static host can serve `public/` as is (Caddy, Nginx, Netlify, Cloudflare Pages, S3).

## Editing

- Layout and styles live in `template.html`.
- Every visible word lives in `copy/es.json` and `copy/en.json`. Both files must have the same keys.
- After any change, rebuild and commit the output:

```bash
cd apps/landing
python build.py
```

## Links

Buttons point at the app, a demo contact and the legal pages. Set them when building for your own domain:

```bash
LANDING_APP_URL=https://app.example.com/login \
LANDING_DEMO_URL=https://wa.me/15551234567 \
LANDING_PRIVACY_URL=https://example.com/privacy \
LANDING_TERMS_URL=https://example.com/terms \
python build.py
```

The defaults (`app.agentaria.com`, `hello@agentaria.com`) are placeholders until the domain is registered.

## Before going live

- Replace the placeholder links above.
- Publish real privacy and terms pages.
- Keep the copy honest: the security list and the plans only name features the product ships today. Update both when that changes.
