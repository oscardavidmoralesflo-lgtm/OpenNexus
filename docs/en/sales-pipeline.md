# Sales pipeline

Each client has a sales board under **Clients → (client) → Sales**. Every contact sits in one stage:

| Stage | Meaning |
| --- | --- |
| New | Wrote in; nothing known yet. Contacts without a stage show here. |
| Interested | Showed real interest: asked about prices, availability or how to buy. |
| Booked | Booked an appointment, visit or call. |
| Won | Bought or paid. |
| Lost | Said no or bought elsewhere. |

Drag a card to another column, or pick the stage on the card. **+ Value** records what the deal is worth, in the client's currency; each column and the header add them up. The chat button opens the contact's latest conversation.

## Agents that keep it up to date

Turn on **Agents update the pipeline** and every agent of the client (chat and phone) gets the `update_sales_stage` tool. The agent is told the contact's current stage and moves them only when the conversation clearly shows it, without mentioning it. It may record the deal's value when the person names it or picks a priced product. The playground rehearses the tool without moving anyone.

Booking an appointment (see [appointment booking](booking.md)) moves a New or Interested contact to Booked on its own.

## API

- `GET /api/clients/{id}/pipeline?q=`: the board, up to 100 contacts per stage, with totals and values.
- `PUT /api/clients/{id}/pipeline/settings` with `{"enabled": true}`.
- `PATCH /api/clients/{id}/pipeline/contacts/{contact_id}` with `stage`, `deal_value` or `clear_value`.
