# Sandbox

One WhatsApp number where every prospect tries the agent you built for them.
Each sandbox agent has a short code; whoever sends it to the number talks to
that agent from then on, and another code switches agents.

## Set it up

1. Open **Sandbox** in the sidebar. The sandbox client (`<Agency> Sandbox`) is
   created the first time; it never counts toward a plan's clients.
2. **Connect number** opens the sandbox client's channels. Link a number with
   the QR bridge or the Cloud API. It asks for an agent: pick any, because the
   agent of the code answers.
3. **New agent** creates an agent in the sandbox client. It gets a 6-character
   code (no ambiguous characters such as `0`/`O` or `1`/`I`).

## Share it

**Copy invitation** copies a message with the agent's name, its code and a
`wa.me` link that opens the chat with the code already typed. The table counts
how many prospects chose each agent.

## How messages are routed

- A message that contains a code (as a word, any case) connects that chat to
  the agent and gets a fixed confirmation.
- Later messages are answered by the chosen agent, with its knowledge, tools
  and model. The choice survives resolved conversations.
- A chat that has not sent a code gets a fixed explanation. No AI is called,
  so stray messages spend no credit.
- **New code** retires the old code at once; chats already connected keep the
  agent.
