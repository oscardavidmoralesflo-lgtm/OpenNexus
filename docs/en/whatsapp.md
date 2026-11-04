# WhatsApp

> Leer en español: [whatsapp.md](../es/whatsapp.md)

Agentaria connects a real WhatsApp number to each client so their agent answers conversations automatically. Each client gets its own session, linked by scanning a QR code from the WhatsApp mobile app — no WhatsApp Business API account required.

## The bridge service

WhatsApp support runs in a dedicated service, the **bridge** (`apps/whatsapp/`), a stateful Go process built on [whatsmeow](https://github.com/tulir/whatsmeow), a library for the WhatsApp Web multi-device protocol. The bridge holds one live connection per connected client and talks to the backend over an internal API.

Because it is stateful, the bridge does not keep sessions in memory only: whatsmeow persists the session keys in its own SQL store, configured by `WHATSAPP_STORE_URL` (a local SQLite file by default; PostgreSQL is supported too). The backend keeps a small encrypted marker per channel that records which linked device the session belongs to. On startup the bridge calls the backend for the list of enabled channels that already have a saved session and reloads them, so numbers reconnect on their own after a restart.

## Connect a number

A WhatsApp session belongs to one client, and a client can link several numbers, each answered by the agent you pick (the same agent may answer more than one). To connect one:

1. Open a **client**, go to its **WhatsApp** channel, and pick the agent that should answer incoming messages.
2. Click connect. The backend asks the bridge to start a session, and a **QR code** appears.
3. On the phone that owns the number, open WhatsApp and go to **Settings → Linked devices → Link a device**.
4. Scan the QR code. Once the phone confirms, the channel switches to **connected** and shows the linked number.

The session survives restarts from then on. If the number is unlinked from the phone (or the session is invalidated), the bridge clears the stored session and the channel returns to disconnected. You can also disconnect from the same page, which logs the device out and removes the saved session.

## How messages flow

When a contact writes to the number:

1. The bridge receives the message and forwards it to the backend at `POST /api/whatsapp/channels/{channel_id}/inbound`.
2. The backend records the message on the client's conversation, retrieves the agent's knowledge, and generates a reply with the assigned agent.
3. The reply is sent back through the bridge to the contact on WhatsApp.

Images and voice notes are forwarded too; when the agent has image or audio understanding enabled they are described or transcribed before reaching the model. See [Knowledge base](knowledge-base.md).

Backend and bridge authenticate every call to each other with a shared secret, `WHATSAPP_BRIDGE_TOKEN`. It is generated for you by the setup script — see [Configuration](configuration.md).

## Ban shield

Numbers linked by QR use the WhatsApp Web protocol, which WhatsApp does not offer to bots, so they can be banned. Each QR line has a ban shield, on by default, shown under its connection:

- **A normal browser**: the line links as WhatsApp Web on Chrome for Windows, not as an automated device. A line linked before this release keeps its old name until it is linked again.
- **Online only while answering**: the line goes online when it reads and types, and offline 40 to 150 seconds after it last did. While offline, the phone keeps its notifications.
- **Limits on what the line starts**: follow-ups, reminders and chats a person opens. Replies to people who wrote always go out. A held follow-up or reminder is retried later instead of being lost.
  - A new number warms up over 7 days: 20, 36, 65, 117, 210, 378 and 680 messages a day. After that the limit is 1,000 a day.
  - At most 200 an hour and 8 a minute, with 2.5 to 7 seconds at random between two of them.
  - Messages to people who never wrote: 3 a day for the first three days, then 10.
  - The same text goes to at most 5 chats an hour. Case, spacing and punctuation do not make it a different text.
- **Pause on risk signals**: the line stops starting messages for 6 hours after 5 refused messages or 3 disconnections in an hour, and for 24 hours after a temporary ban. **Resume now** lifts the pause by hand.

The numbers follow the community anti-ban libraries for Baileys and whatsmeow. They lower the risk without removing it. What weighs most is people blocking or reporting the number, so write first only to people who expect it. For volume, use the [WhatsApp Cloud API](whatsapp-cloud-api.md).

## Human takeover

Every conversation has a `mode`, either `ai` (the default) or `human`. When you switch a conversation to human mode, the AI stops replying to it — the backend still records incoming messages, but generates no automatic answer — so a person can take over and respond directly from the [inbox](inbox.md) or the [client portal](client-portal.md). Switch back to `ai` to hand the conversation to the agent again.

## Other channels

WhatsApp is the only messaging channel in the open-source core today. Instagram and Facebook Messenger are on the roadmap.

Next: manage live conversations in the [inbox](inbox.md), or let clients handle their own in the [client portal](client-portal.md).
