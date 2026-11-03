# WhatsApp campaigns

A campaign sends one approved WhatsApp template to many contacts of a client: a promotion, a reminder to everyone, a message to bring back inactive customers. Open **Clients → (client) → Campaigns**.

## What it needs

- A number connected through the **WhatsApp API (Cloud)**. Meta only lets a business start a conversation with an approved template, and only the Cloud API sends them. Numbers linked by QR are not offered: mass messages from them get the number banned.
- An **approved template** on that number's business account (the client's **Templates** tab creates them and sends them for approval; see [WhatsApp Cloud API](whatsapp-cloud-api.md)).

## Creating one

1. **New campaign**: give it a name and choose the number and the template.
2. Fill in each template variable. `{first_name}` and `{name}` become each contact's first or full name; anything else is sent as written. A template with a media header asks for a public link to the image, video or document. The preview shows the message as a contact named Ana would see it.
3. Choose **who receives it**: contacts with a phone number that are not blocked. Without filters it goes to all of them; with tags or sales stages (see [sales pipeline](sales-pipeline.md)), to those in any of the chosen ones. The live count shows how many it reaches.
4. **Send now**, **Schedule** for a date and time, or **Save draft**.

Starting a campaign freezes its list of recipients, up to 10,000. The follow-up timer sends it in batches of 60 per minute. Each message goes into the contact's open chat on that number, or a new one, stored as the agent's message: when someone replies, the agent sees what the campaign said and answers as usual.

## Following it

Each campaign shows how many were sent, delivered, read, replied and failed, with the share of the sent ones. **Recipients** lists each contact with its result and a link to the chat. **Stop** halts a scheduled or sending campaign; what went out stays sent. If Meta pauses or rejects the template while it is going out, the campaign returns to draft with the reason, instead of failing every contact.

## Good practice

Send campaigns only to people who agreed to hear from the business. When many people block or report the messages, Meta lowers the number's quality rating and can limit or block it. Meta bills each marketing template message to the business account.

## API

- `GET /api/clients/{id}/campaigns` lists them with their stats.
- `POST /api/clients/{id}/campaigns/audience` with `{"tag_ids": [], "stages": []}` counts who an audience reaches.
- `POST /api/clients/{id}/campaigns` creates a draft: `name`, `channel_id`, `template_name`, `template_language`, `variables`, `header_value`, `audience`. `PUT /api/clients/{id}/campaigns/{campaign_id}` edits a draft.
- `POST .../{campaign_id}/start` with an optional `scheduled_at`; `POST .../{campaign_id}/cancel`; `DELETE .../{campaign_id}`.
- `GET .../{campaign_id}/recipients?status=` lists up to 500 recipients.
