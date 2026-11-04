# Keeping up with OpenLivery

Agentaria started as a copy of [OpenLivery](https://github.com/sarrazola/openlivery)
(MIT) with no shared git history, so upstream changes are ported by hand, one
pull request per batch. A scheduled task checks upstream every week and opens
that pull request when there is something new.

## Where we are

`.github/upstream.json` holds the last upstream commit already ported. Update
it in the same pull request that ports newer commits.

## Rules for a port

- Port upstream's merged pull requests in order, one commit each, keeping
  their titles and adding `(#NNN)` like upstream. Take changes from
  upstream's `main` only.
- Open the pull request against `feature/panel-parity` and never merge it; the
  owner merges, and the merge deploys.
- Migrations: upstream numbers its own, and ours have moved ahead. Give each
  ported migration the next free number here and chain its `down_revision`
  to our latest head.
- Keep what Agentaria adds on top: the 11 direct AI providers next to
  OpenRouter (upstream is OpenRouter only), the Agentaria name and brand,
  the activity log, the quality lab, the monthly client report, Ctrl K
  search and the community links hidden by default.
- Code, comments, docs and commits stay in English; user-facing copy goes
  through the i18n dictionaries in English and Spanish.
- Run the API tests, `npx tsc --noEmit`, `npm run lint` and `go test ./...`
  for what changed before pushing. A change that cannot fit cleanly is left
  out and listed in the pull request body with the reason.
