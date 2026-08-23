# Olivia — MDS Personal Assistant (V1 Pilot)

WhatsApp AI assistant for MDS (Million Dollar Sellers) members, per the
**V1 Pilot Sprint Plan & Developer Spec (July 2026)**. Every pilot member gets
a personal assistant on the warmed-up MDS WhatsApp number that answers
questions any time, and (from Sprint 2) proactively sends 2–3 fresh picks each
week — with a human watching every conversation live from the phone.

```
WhatsApp (Coexistence: Business app + Cloud API on the same number)
        │  webhooks: messages, statuses, smb_message_echoes
        ▼
  this service (src/server.js)
        │  normalize phone → match member → assemble context
        ▼
  Airtable (MDS Member Database: Members, Conversation Log, Pilot Picks)
        │
        ▼
  Claude API (claude-sonnet-4-6, Olivia system prompt)
        │
        ▼
  reply via Cloud API → both sides logged to Conversation Log
```

> The sprint plan names n8n as the orchestrator. This repo implements the
> exact same three workflows as a small Node service — it can run standalone,
> or serve as the reference logic for the n8n build (each workflow module maps
> 1:1 to an n8n workflow).

## The three workflows

| Spec | Here | Trigger |
|---|---|---|
| **Workflow A** — inbound handler | `src/workflows/inbound.js` | WhatsApp webhook → `POST /webhook` |
| **Workflow B** — welcome drafts | `src/workflows/welcomeDrafts.js` | `npm run drafts:welcome` |
| **Workflow C** — weekly digest | `src/workflows/weeklyDigest.js` | `npm run digest:weekly` (cron) |

### Workflow A rules (Sprint 0)

- **Debounce** — after an inbound message, wait 20s (`DEBOUNCE_SECONDS`); a
  burst of texts gets one coherent reply.
- **Human-pause** — if a human replied from the phone app (an
  `smb_message_echoes` event) on that thread in the last 4 hours
  (`HUMAN_PAUSE_HOURS`), the agent stays silent. A human echo also cancels
  any reply pending in the debounce window.
- **STOP / START** — bare `stop` (any casing) sets `Weekly Opt-Out` and sends
  the confirmation copy; the agent still answers if they message later.
  `start` opts back in. Handled deterministically, never by the model.
- **Unknown numbers** — logged unlinked and left to the human on the phone;
  the agent never replies to non-members.
- **Memory** — the last ~30 Conversation Log rows (`LOG_CONTEXT_ROWS`) are
  sent to Claude with each request, plus the member's
  `Assistant Profile Summary` and queued Pilot Picks in the system prompt.

### Workflow B (Sprint 1)

Generates a personalized welcome draft (copy in `src/prompts/messages.js`,
spec section 5) for every `Assistant Pilot` member into the `Welcome Draft`
field for Eugene/Kat review. **Nothing is auto-sent** — approved welcomes go
out manually from the phone app (no template approval needed, lands as a
normal chat).

### Workflow C (Sprint 2)

Per member: pulls queued picks, skips entirely if none are relevant, respects
`Weekly Opt-Out`, sends the approved Meta template (`DIGEST_TEMPLATE_NAME`,
body variables `{{1}}`=first name, `{{2}}..{{4}}`=pick lines), marks picks
sent, stamps `Last Assistant Touch`. Use `--dry-run` first; `--as-text` sends
free-form for testing inside an open 24h session.

## Try it right now — no accounts needed

```
npm run simulate            # interactive: you play the member texting Olivia
npm run simulate -- --demo  # scripted walkthrough of all the pilot rules
```

The simulator runs the **real** webhook server and Workflow A code; only the
three external services are faked (WhatsApp sends are printed to the console,
Airtable is in-memory and seeded with you as a pilot member, Claude replies
are canned). Export a real `ANTHROPIC_API_KEY` first and you get live Olivia
replies through the actual system prompt. In interactive mode, `/human <text>`
simulates a teammate replying from the phone app (the agent then pauses on
the thread) and `/state` dumps the in-memory Airtable.

## Testing with a real WhatsApp phone

Meta gives every developer a **free test number** that can message up to 5
opted-in phones — perfect for the pre-pilot test, no Coexistence provider
needed yet:

1. developers.facebook.com → create an app → add the **WhatsApp** product.
2. On *API Setup* you get a test number, a `WHATSAPP_PHONE_NUMBER_ID`, and a
   temporary access token — put them in `.env`. Add your personal WhatsApp
   under "To" recipients and verify it.
3. Run this server somewhere Meta can reach (deploy it, or run locally behind
   a tunnel like `cloudflared tunnel --url http://localhost:3000`), then in
   *Configuration* set the webhook to `https://<public-host>/webhook` with
   your `WHATSAPP_VERIFY_TOKEN`, and subscribe to the **messages** field.
4. Add yourself as a member in Airtable (or a test base) with your real
   number in `WhatsApp Phone`, send the test-number's hello template to open
   the session, then text it — Olivia answers.

Note: `smb_message_echoes` (human-pause) only exists on a real Coexistence
number, so that rule is testable in the simulator but not on the test number.

## Setup

1. **Prereqs** — Node ≥ 20.6; the warmed-up number connected to the Cloud API
   via a Coexistence-capable provider (Wati / 360dialog), keeping app access.
2. `npm install`
3. `cp .env.example .env` and fill in tokens (WhatsApp, Anthropic, Airtable).
4. **Airtable schema** (spec section 6): `npm run setup:airtable` — adds the
   new Members fields and creates `Conversation Log` + `Pilot Picks` in the
   existing base. Idempotent.
5. **Webhooks** — point the Meta app / provider at `https://<host>/webhook`
   with `WHATSAPP_VERIFY_TOKEN`; subscribe **messages** and
   **smb_message_echoes**.
6. `npm start`

## Pilot runbook (Sprint 1)

1. Flag 5–10 members `Assistant Pilot = true`; confirm `WhatsApp Phone`
   (any formatting works — matching is digits-only) and fill
   `Assistant Profile Summary`.
2. Hand-curate 2–3 `Pilot Picks` per member, `Status = queued`.
3. `npm run drafts:welcome -- --dry-run`, then without the flag to write
   drafts to Airtable for review.
4. Send approved welcomes **manually from the phone app**, spaced over 1–2 days.
5. When members reply, the 24-hour session opens and Workflow A answers
   automatically — take over from the phone whenever needed; the agent backs
   off for 4 hours.

## Tests

```
npm test
```

Covers phone normalization, STOP/START detection, debounce batching and
human-takeover cancellation, webhook payload parsing (all three event types),
and conversation-log → Claude message conversion.

## Repo map

```
src/
  server.js                 webhook server (verification, signature check, dispatch)
  config.js                 env config
  lib/
    airtable.js             Members / Conversation Log / Pilot Picks client
    whatsapp.js             Cloud API sends (text + template)
    claude.js               Claude API + log→messages conversion
    debounce.js             per-thread burst batching
    webhookEvents.js        Cloud API payload → flat events
    phone.js                E.164 normalization
  workflows/
    inbound.js              Workflow A
    welcomeDrafts.js        Workflow B
    weeklyDigest.js         Workflow C
  prompts/
    olivia-system-prompt.md Olivia persona (spec section 7 — Eugene owns wording)
    messages.js             welcome / STOP / digest copy (spec section 5) + STOP/START detection
scripts/
  setup-airtable.js         one-time schema additions (spec section 6)
  generate-welcome-drafts.js
  send-weekly-digest.js
```

## Deferred (per spec, out of V1 scope)

Auto-trigger on new-member signup · tagged content index and auto-matching ·
escalation-to-Slack lane (the system prompt makes Olivia say she's looping in
the team on billing/renewal/complaints and stop) · Sprint 3 scale-up.

## Also in this repo

`mds-kpi-system/` is a separate Python project: the automated 13-KPI weekly
scoreboard that replaces the 109-row manual spreadsheet. It shares nothing with
the Olivia service except the n8n WhatsApp webhook it can deliver recaps
through. See `mds-kpi-system/README.md`.
