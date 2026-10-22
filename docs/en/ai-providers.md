# AI providers

> Leer en español: [ai-providers.md](../es/ai-providers.md)

Each agency can connect **OpenRouter, OpenAI, Anthropic (Claude), Google Gemini, DeepSeek, Groq, xAI (Grok), Mistral AI, Together AI, Fireworks AI, and Cerebras**. OpenNexus encrypts each key, and each agent chooses its provider independently. Direct providers use their own accounts, balances and native model IDs; OpenRouter remains available as a multi-vendor router.

## Bring your own key

Keys are configured per agency. Open **Settings → AI providers**, search for the provider and use its API-key link. Saving first verifies the key without generating a reply: OpenRouter uses `/key`, and direct providers use their authenticated `/models` endpoint. Anthropic model discovery uses its native authentication headers. If verification fails, nothing is saved. Keys can be paused, replaced, or removed independently.

Stored keys are never returned to the browser in full — the UI only shows a masked value. On disk, the key is encrypted with a key derived from `ENCRYPTION_KEY` and decrypted on demand when an agent needs it, so rotating or losing that secret makes the stored key unreadable. See [Configuration](configuration.md) for how `ENCRYPTION_KEY` is set and why it must never change.

## How requests are made

Chat uses the selected provider's fixed OpenAI-compatible endpoint. Anthropic uses its documented compatibility layer for chat and tools; native-only Claude features are not exposed by this layer. Router-only usage extensions are omitted for direct APIs. The fixed endpoint registry is `apps/api/app/services/providers.py`.

| Capability | Endpoint |
| --- | --- |
| Chat replies and tool calls | `/chat/completions` |
| Image understanding | `/chat/completions` with an image part |
| Voice note transcription | `/audio/transcriptions` |
| Knowledge base embeddings | `/embeddings` (`openai/text-embedding-3-small`) |

OpenRouter can report the billed cost in its usage block. Direct APIs often report tokens without a billed amount; an absent amount remains unknown in the stored usage record. OpenRouter generation reconciliation is never sent to a direct provider. Check the provider dashboard for its authoritative charge. Image, transcription, speech and embedding models can use a matching direct vendor key when a router key is unavailable. A missing capability key does not prevent ordinary text replies; document retrieval can fall back to keyword search.

## Model ids

Models are named by their OpenRouter slug, `vendor/model`: `openai/gpt-6-luna`, `anthropic/claude-sonnet-5`, `google/gemini-3.8-flash`. The agent wizard and the agent page offer a curated preset list, grouped by what an agency actually chooses on (fastest and cheapest, balanced, most capable), and accept any other slug typed by hand. The presets come from `apps/web/lib/providers.ts` and are mirrored, with context windows, capabilities and list prices, in `apps/api/app/services/model_catalog.py` (`GET /api/catalog/models`).

### Vision and audio models

Some capabilities use dedicated model sets rather than the chat model:

- **Vision (`IMAGE_MODELS`)** for image understanding: any vision-capable chat model in the catalog. The default is `openai/gpt-4.1`.
- **Transcription (`AUDIO_MODELS`)** for audio understanding: `openai/gpt-4o-mini-transcribe` (default), `openai/gpt-4o-transcribe`, `openai/gpt-transcribe`.

## Choosing a model per agent

Keys are set once per agency, but each agent picks its own provider and model. Configured direct providers discover the models accessible to their key, and their pickers still accept a manually entered native model ID. You do this when you create or edit an agent, choosing from the presets above or typing a slug. See [Agents](agents.md) for how model choice, instructions and knowledge come together.

## MCP management and customer replies

Connecting Codex, Claude Code or Cursor through the workspace MCP server lets that client prepare agents, load knowledge, connect tools and run tests. It does not replace the agent and AI-provider configuration used for unattended customer replies, and it does not supply API credit from a Codex or ChatGPT subscription.

## Historical migration from OpenAI and Anthropic keys

Releases before migration `0042_openrouter` stored OpenAI and Anthropic keys and used bare model ids. The migration moves every agent to OpenRouter and rewrites its model ids to slugs (`gpt-4.1-mini` becomes `openai/gpt-4.1-mini`, `claude-sonnet-5` becomes `anthropic/claude-sonnet-5`, `whisper-1` becomes `openai/gpt-4o-mini-transcribe`). The old keys are dropped, since OpenRouter cannot use them: after upgrading, add an OpenRouter key in Settings and the agents reply again.

## Next steps

- [Agents](agents.md) — pick a model and write instructions.
- [Configuration](configuration.md) — `ENCRYPTION_KEY` and other secrets.
- [Knowledge base](knowledge-base.md) — give an agent context, Q&A and PDFs.
