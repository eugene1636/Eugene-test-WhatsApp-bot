# Email Response Assistant — Design (working draft)

Owner: Eugene · Status: **DRAFT — open items marked 🔴**

Drafts replies in Eugene's voice on email threads he started, pulling context
from Slack, ClickUp, and web search when the thread needs it. It **never
sends** — every output is a Gmail draft sitting in the thread, waiting for a
human to hit send.

This is the same machine as Olivia (WhatsApp), pointed at a second channel:
`event → deterministic gate → debounce → assemble context → Claude → write a
draft a human approves`. Workflow B in this repo already establishes the
pattern ("Nothing is auto-sent"). Reuse it rather than starting fresh.

---

## 1. The gate is code, never the model

"Only touch the emails I started" is the whole safety story, and it must be
a deterministic function that runs *before* a single token is spent — the
same way STOP/START is handled in Workflow A, never by Claude.

A thread is eligible only if **all** of these hold:

| # | Check | How |
|---|-------|-----|
| 1 | **Eugene started it** | Fetch the thread, look at the **first** message's `From` header. Must be `eugene@mds.co`. One header comparison — nothing fuzzy. |
| 2 | Someone replied and the ball is in his court | Latest message in the thread is **not** from Eugene. |
| 3 | He hasn't already answered | No Eugene message newer than the triggering one. (Email's equivalent of the 4-hour human-pause.) |
| 4 | No draft already on the thread | `drafts.list` → skip if one exists. Idempotency; never clobber something he's typing. |
| 5 | Not already processed | Seen-set keyed on `messageId`. Polling replays history; this stops doubles. |
| 6 | Not machine mail | Sender denylist: `noreply@`, `no-reply@`, `notifications@`, calendar invites (`text/calendar` part), bulk headers (`List-Unsubscribe`, `Precedence: bulk`). |
| 7 | Not opted out | A Gmail label `no-assistant` on the thread → skip forever. The manual escape hatch; he can apply it from his phone. |

🔴 **Decide reading of "emails I have started."** Two plausible meanings, one
config flag apart:

- `THREAD_SCOPE=initiated` *(recommended default)* — Rule 1 as written: he
  sent the first message. Covers his outbound: intros, pitches, follow-ups.
  The tightest possible blast radius for v1.
- `THREAD_SCOPE=participated` — he has sent **any** message in the thread.
  Wider: also covers inbound threads he has already engaged with. Strictly a
  superset; flip the flag once the `initiated` version has earned trust.

Either way, cold inbound he has never touched is out of scope. Start narrow —
this is the setting that makes the thing safe to leave running.

---

## 2. Architecture

```
Gmail (poll users.history.list every 60s, stored historyId)
        │  new message ids
        ▼
  eligibility gate (§1) ── deterministic, no model, no API spend
        │
        ▼
  debounce 60s (reuse src/lib/debounce.js verbatim)
        │  reply-all bursts get one draft, not four
        ▼
  voice retrieval: ~12 of Eugene's real past replies (§3)
        │
        ▼
  Claude (claude-opus-5) + tools: slack / clickup / web_search / prior threads
        │  agentic loop, capped at ~6 tool calls
        ▼
  drafts.create on the thread  ← human reviews and sends
        │
        ▼
  after he sends: diff sent vs draft → learning corpus (§5)
```

### Trigger: poll, don't push

Gmail push (`users.watch` → Cloud Pub/Sub) is the real-time route, but it
needs a GCP project, a Pub/Sub topic, IAM bindings, and re-registration every
7 days. For a draft assistant, 60-second latency is invisible.

**Start with polling**: store `historyId`, call `users.history.list` on a
timer, ~1 API call/minute, no extra infrastructure. Move to push only if
volume ever justifies it. Same pragmatism as this repo choosing a small Node
service over the n8n build.

---

## 3. Sounding like Eugene

This is the part that decides whether the thing is used or abandoned, and the
common mistake is to hand-write a "style guide" prompt. Don't. **Retrieve his
actual sent mail and put it in the prompt as examples.** His Sent folder is
the training data, and it is already sitting in the account.

Two layers:

**a) Style card (static, cached).** One offline pass over ~200 recent sent
messages → a compact profile: typical greeting and sign-off, average length,
paragraph vs. bullets, sentence rhythm, punctuation habits (does he use
em-dashes? exclamation marks? lowercase openers?), how he says no, how he
chases. ~500 tokens, regenerated monthly, sits at the top of the system
prompt behind a `cache_control` breakpoint so it's cheap on every call.

**b) Retrieved examples (dynamic, per thread).** ~12 of his real past replies,
picked in priority order:

1. Replies **to this same person** — tone is relationship-specific; how he
   writes to a partner isn't how he writes to a member.
2. Replies on a **similar topic** — Gmail search on subject keywords and
   named entities, `in:sent`.
3. Recent generic replies, as filler if 1 and 2 come up short.

Verbatim, as `<example>` blocks, with the message each was replying to so the
model sees the stimulus and the response. Style transfer from real pairs
beats any description of a style. No fine-tuning needed — and fine-tuning
would be worse here, because it can't condition on *who he's writing to*.

**Register control.** The style card should capture that he writes
differently to different audiences, and the prompt should pick the register
from the recipient. 🔴 Worth seeding manually with 3–4 buckets (member,
partner/vendor, internal team, cold outbound) rather than hoping it's
inferred.

---

## 4. Context: Slack, ClickUp, web

Give Claude tools and let it decide when it needs them — that's exactly the
"multi-step, hard to specify in advance" case where an agent loop earns its
cost. A hard-coded "always search Slack" rule burns tokens on threads that
need nothing.

| Tool | Backing | Answers |
|---|---|---|
| `slack_search` | Slack MCP / `search.messages` | "What did we actually agree with this person?" — DMs and channels mentioning the sender, their company, the topic |
| `clickup_search` | ClickUp MCP / search API | Live status of whatever he's being asked about: is the task done, who owns it, what's the due date |
| `web_search` | Anthropic server-side tool, `web_search_20260209` | Facts about their company, a product, a news item — no separate provider to wire up |
| `prior_threads` | Gmail `messages.list` `from:<sender>` | What was already promised to this person, and when |

**Wiring.** Slack and ClickUp already have MCP servers connected to Eugene's
account — attach them straight to the Messages API rather than hand-rolling
API clients:

```js
mcp_servers: [{ type: "url", url: SLACK_MCP_URL, name: "slack" }],
tools: [{ type: "mcp_toolset", mcp_server_name: "slack" },
        { type: "web_search_20260209", name: "web_search" }],
betas: ["mcp-client-2025-11-20"],
```

Both halves are required — `mcp_servers` alone is a validation error.

**Bound the loop.** Cap total tool calls (~6) and set an explicit budget so
one ambiguous thread can't spend $3. Instruct the model plainly: *most
threads need zero tool calls; reach out only when the reply depends on a fact
you don't have.*

**Inherit V1's data discipline.** Andy's rule from PROCESS-V2 §3 applies
unchanged: **the assistant only reads sources that have been defined.** Scope
Slack to named channels, ClickUp to named spaces. No crawling everything he
has access to — a draft that quotes a private #founders thread back at a
vendor is the failure mode that kills the project on day one.

🔴 **Define the Slack channel allowlist and ClickUp space allowlist** before
first run.

---

## 5. Drafts, the never-send guarantee, and learning

### Where the draft lands

`drafts.create` with the thread's `threadId` plus correct `In-Reply-To` and
`References` headers → the draft appears **inside the thread** in Gmail on
every device. He opens the thread on his phone, reads, edits, sends. Zero new
UI to build, zero new habits to learn. This is the single highest-leverage
decision in the design.

### The never-send guarantee

Be precise about this: Gmail has **no scope that permits drafts but forbids
sending** — `gmail.compose` grants both. So the guarantee cannot come from
OAuth. It comes from code:

- The codebase contains **no call** to `messages.send` or `drafts.send`. Make
  that a grep-able invariant and a test that fails if either string appears.
- The email service holds the only credential with `gmail.compose`, and it
  has exactly one write path.
- Scopes stay minimal: `gmail.readonly` + `gmail.compose` + `gmail.labels`.
  Nothing else.

### Where the reasoning goes

The draft body should be clean — a footer he has to delete before sending is
a footgun waiting for a distracted Tuesday. Send the "here's what I looked
at" note **out of band**: a Slack DM to himself with the sources used, the
confidence, and a deep link to the draft. Keeps the draft sendable as-is.

### The learning loop — build this early

After he sends, fetch the sent message and diff it against what was drafted.
That diff is the most valuable data in the system and it costs nothing to
collect.

- **Near-zero edits** → the draft was right; nothing to do.
- **Heavy rewrite** → store the `(draft, what_he_actually_sent)` pair.

Feed the ~10 most recent high-edit pairs back into the prompt as corrections:
*"You drafted X. He sent Y. Note the difference."* This converges the voice in
weeks rather than months, and it also gives an honest quality metric —
**median edit distance over time** is the number that says whether this is
working. Track it from day one.

---

## 6. Build order

| Phase | Ships | Why here |
|---|---|---|
| **0** | Gate + poller + logging only. **Writes nothing.** Log which threads it *would* have drafted, for a week. | Confirms the gate matches Eugene's intuition about "emails I started" before anything reaches his mailbox. Cheap, and it settles the 🔴 in §1 with evidence. |
| **1** | Drafting with voice retrieval. **No external tools yet.** | Voice is the make-or-break. Get it right in isolation; most replies need no outside context anyway. |
| **2** | Learning loop (sent-vs-draft diff) + the edit-distance metric. | Before adding surface area, install the thing that measures whether surface area helps. |
| **3** | Tools, one at a time — Slack, then ClickUp, then web. | Each is independently testable. Mirrors PROCESS-V2 §6: connect one clean source at a time; value grows per source, nothing blocks on all of them. |
| **4** | Register buckets, per-recipient tuning, escalation rules. | Only once there's real edit data showing where it goes wrong. |

Phase 0 is not a formality. It is what makes it safe to point this at a live
mailbox.

---

## 7. Reuse from this repo

| Need | Already exists |
|---|---|
| Burst batching | `src/lib/debounce.js` — reuse unchanged, 60s window |
| Claude client | `src/lib/claude.js` — extend for tool use and the agentic loop |
| Env config | `src/config.js` — add a `gmail` block |
| Draft-then-human-approves | Workflow B (`src/workflows/welcomeDrafts.js`) is this exact shape |
| Deterministic rules before the model | Workflow A's STOP/START handling is the precedent |

Suggested layout: `src/channels/email/` (poller, gate, voice, tools, draft
writer), leaving `src/workflows/` as the WhatsApp channel. Olivia becomes
"the WhatsApp channel"; this is "the email channel"; the brain is shared.

🔴 **Decide: same repo or separate service.** Same repo shares the primitives
and the deploy target, and both channels are the same pattern. Separate keeps
the Gmail OAuth credential in its own blast radius. Recommendation: same
repo, separate process, separate credential.

---

## 8. Model, cost, latency

- **Model:** `claude-opus-5` with `thinking: {type: "adaptive"}`. Voice
  matching and "do I need to look this up?" are both judgment calls where the
  stronger model shows. This is the highest-visibility output in the system —
  it goes out under his name.
- **Prompt caching:** stable prefix = system prompt + style card + tool
  definitions, behind one `cache_control` breakpoint. Volatile content (the
  thread, the retrieved examples) goes after it. Verify with
  `usage.cache_read_input_tokens` — if it's zero across calls, something in
  the prefix is changing.
- **Cost:** ~30–50K input tokens per draft (thread + 12 examples + tool
  results), ~1K out. At Opus 5 rates ($5/$25 per MTok) that's roughly
  **$0.10–0.25 per draft**, less with caching. At 20 drafts/day, order
  **$60–150/month**. If that's the wrong shape, `effort: "medium"` and fewer
  retrieved examples are the first levers — before changing model.
- **Latency:** 60s poll + 60s debounce + 10–40s generation. He sees a draft
  ~2–3 minutes after the reply lands. Fine for something he reviews.

---

## 9. Open questions

1. 🔴 `THREAD_SCOPE`: `initiated` or `participated` (§1). Phase 0 answers this
   with real data.
2. 🔴 Slack channel allowlist and ClickUp space allowlist (§4).
3. 🔴 Register buckets — how many, and which (§3).
4. 🔴 Same repo vs. separate service (§7).
5. 🔴 Does it draft on threads with **multiple** recipients, or 1:1 only?
   (Recommend 1:1 for Phase 1 — reply-all mistakes are the expensive kind.)
6. 🔴 Retention: how long are retrieved sent-mail excerpts and the
   draft/sent diff corpus kept, and where do they live?
7. 🔴 Anything the assistant must never read even inside allowlisted sources
   (legal, HR, comp threads) — the PROCESS-V2 §3(e) question, applied to
   Slack and Gmail.
