# Team and security

## Team

**Settings → Team** lists everyone who works in the workspace. Owners and
admins invite people: the invitation is a private link that works once and
expires in 7 days. Share it through a channel you trust; whoever opens it picks
a name and password and joins with the role you chose.

| Role | Can |
|---|---|
| Owner | Everything, including billing and managing owners and admins. |
| Admin | Clients, agents, channels, keys, AI-agent tokens and the team, except billing and other admins. |
| Operator | Works the inbox (reply, take over, resolve, playground) and reads the rest. |
| Viewer | Reads clients, agents, conversations and reports. |

The API enforces the role on every dashboard request, so a new route is
covered without extra code. The agency always keeps at least one owner. A
removed member loses access at once, along with the MCP tokens they created;
MCP tokens of operators and viewers can only read.

## Two-step verification

**Settings → Security** turns on time-based codes (TOTP) with any authenticator
app: scan the QR code, confirm a code, and keep the 10 recovery codes (each
works once). Sign-in then asks for a code after the password; a code cannot be
reused. Turning it off needs the password and a code.

An owner can **require two-step verification** for the whole team under
**Settings → Team → Security policy**. Members who have not set it up are sent
to Security and can use nothing else until they do.

## First-run setup

Set `SETUP_TOKEN` on a public deployment: the first-run form then asks for it,
so nobody else can claim the installation before you.
