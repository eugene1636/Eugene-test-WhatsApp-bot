# MDS Member Assistant — Process Document V2 (working draft)

Owner: Eugene · Build: Andy · Status: **DRAFT — open items marked 🔴**

This supersedes the V1 Pilot Sprint Plan as the full-picture process
document. The V1 plan (and the code in this repo) remains the first
implementation slice; this document defines the whole system it grows into.

---

## 1. Current onboarding process (as-is — to be confirmed)

The assistant *enhances* this process; it does not replace it. Getting the
as-is right matters because the first WhatsApp message slots into it.

1. **Manual personalized email.** 🔴 *[Name TBC — heard "Bilin"?]* manually
   reviews information about each incoming new member and sends a customized
   email that mentions a few things specifically relevant to them. This is
   the start of onboarding.
   - 🔴 **Insert a real example of this email** (copy one in here).
   - 🔴 **Document exactly what information she looks at** to write it
     (application form? vetting call notes? LinkedIn? which Airtable
     fields?). This same information becomes the seed for the assistant's
     member profile, so precision here pays off twice.
   - 🔴 **Document the launch/send process** — when in the member journey it
     goes out, from what address, any follow-up cadence.
2. **Intercom onboarding flow.** An automated flow triggered in Intercom for
   new members. 🔴 Document the triggers, steps, and messages in that flow.
3. **1:1 onboarding call.** The team tries to get every member on a
   one-on-one call and walks them through the different programs.
   🔴 Who runs these, how they're booked, what's covered.

**Where WhatsApp fits:** the assistant's first message is a new touchpoint
alongside (not instead of) the email, Intercom flow, and 1:1 call.
🔴 Decide sequencing: does the WhatsApp intro land before or after the
email / call?

---

## 2. The two sides of the assistant

### Side A — Proactive weekly message (push)

- **First message is special.** A unique introductory message ("hey, I'm
  going to be your weekly …") — warmer and more personal than the recurring
  ones. (V1 welcome copy already drafted; see repo `src/prompts/messages.js`.)
- **Then a weekly automation.** Each week, look at what happened recently
  and pick relevant items *for this member* from the available data sources
  (section 3): recent videos, people they should meet, partner offers,
  upcoming events, programs they should know about.
- **Memory / no-repeats.** The system must remember everything it already
  sent each member and never resend the same item. (V1 already has this:
  Conversation Log + picks marked `sent`.)
- **Skip rather than pad.** If nothing genuinely relevant exists that week,
  send nothing.

### Side B — Reactive agent (pull)

A member messages a question, gets an answer. Question types, simplest to
hardest:

1. **Structured lookup.** "What's the next event in New York?" → query the
   events data, answer directly with the specific item.
2. **Open-ended topic question.** "Do you know anything about AI?" / "Where
   should I look for AI stuff?" → summarize the relevant MDS resource (e.g.
   TLDR of what's happening in the AI chat right now, what people are
   building) + "click here to see more."
3. **Member matchmaking.** "Do you know a member who knows a lot about X?"
   → search member database, suggest a member, and potentially offer a
   **"make introduction" action** — the system then makes the intro via
   email or WhatsApp. 🔴 Define consent: does the *other* member get asked
   before an intro is made?
4. **Partner offers.** 🔴 *Dictation cut off here* — define what happens
   when somebody asks about a partner offer.

**Core answering principle:** the goal is **not to be the answer — it's to
route to an MDS resource.** Every answer = high-level TLDR of what the thing
is + up to ~3 MDS places to go look. The agent may also ask a clarifying
follow-up ("want events or the chat on this?", "what's your preferred medium
— video, post, intro?") and remember the preference.

---

## 3. Data elements — definitions and availability

Each source the assistant could draw from, and what "properly defined" means
for it. 🔴 **The availability column is the single biggest unknown — Andy to
confirm each one** (he's flagged that data is scattered across multiple
bases/tables; each source below needs one clean, agreed home before the
agent may read it).

**Confirmed 2026-07-13 (scan of Eugene's Airtable account):** six bases
exist — `MDS Member Database`, `Members (Operations)`, `Member ScoreCard`,
`Event Planning Base`, `Partnerships`, `MDS Team Org & Performance`. This
confirms Andy's "multiple bases" point (member data alone appears in at
least three) and that Events and Partnerships have obvious candidate homes.
🔴 Table-level inventory of each base still to do (needs Airtable access
approval in the code session, or Andy documents it).

| # | Source | Used for | Where it lives today | Available? |
|---|--------|----------|----------------------|-----------|
| 1 | **Video/content library** | weekly picks, topic answers | 🔴 confirm (recordings platform? Airtable index?) | 🔴 |
| 2 | **WhatsApp chats** (community groups) | topic summaries ("what's happening in the AI chat") | Andy moved WA data to Supabase | 🔴 partially? |
| 3 | **Member database** | profiles, matchmaking, intros | Airtable — at least 3 candidate bases: `MDS Member Database`, `Members (Operations)`, `Member ScoreCard` → 🔴 pick ONE canonical | ✅ exists, needs canonicalizing |
| 4 | **People-they-should-meet / matchmaking signals** | intros | 🔴 derived from member DB? niche/interest tags needed | 🔴 |
| 5 | **Partner offers** | weekly picks, offer questions | Airtable `Partnerships` base — 🔴 confirm it holds member-facing offers | ✅ candidate exists |
| 6 | **Facebook group** | topic answers | Facebook — *known hard to extract; likely out of scope* | ❌ assume no |
| 7 | **Events (all upcoming)** | "next event in NY", weekly picks | Airtable `Event Planning Base` — 🔴 confirm it covers all upcoming events with dates/locations | ✅ candidate exists |
| 8 | **Programs** (walked through on 1:1 calls) | onboarding answers, picks | 🔴 confirm — a simple static list may be enough | 🔴 |

For each source, "properly defined" =
**(a)** one agreed system-of-record, **(b)** the fields the agent may read,
**(c)** how fresh it is / who updates it, **(d)** tagging (topic, niche,
geography, date) so relevance matching works, **(e)** anything private the
agent must never surface.

Rule inherited from V1 (and Andy's very valid concern): **the agent only
reads sources that have been cleaned and defined.** Undefined source = the
agent acts as if it doesn't exist. No crawling raw scattered bases.

---

## 4. Memory requirements

1. **Sent-history** per member: every item ever sent (weekly or in-chat),
   checked before sending anything → no repeats. *(V1: Conversation Log +
   Pilot Picks status.)*
2. **Conversation memory:** recent exchanges inform answers. *(V1: last ~30
   log rows.)*
3. **Preference memory:** stated preferences (preferred medium, topics,
   "don't message me about X") get written back to the profile. *(V1 seed:
   Assistant Profile Summary field; needs a defined write-back path.)*

---

## 5. Positioning, naming, and the opt-out trap

- 🔴 **Decide what this is called to members at launch:** a weekly
  newsletter, or an assistant/agent ("Olivia") from day one.
- **The trap Eugene flagged:** if members experience it as "a newsletter,"
  block/STOP it, and it *later* becomes an agent — those members have
  pre-blocked a product they never saw. Bad member experience, hard to undo.
- **Design answer (already built into V1, keep it):** STOP only ever means
  "stop the weekly pushes," never "block the agent." The STOP confirmation
  says exactly that ("you can still message me anytime"). Members who opt
  out of weekly still get answers whenever they message in.
- **Recommendation:** introduce it as an AI assistant that *sends* a weekly
  update (agent identity first, newsletter as one of its behaviors) — then
  growing its abilities later is a natural upgrade, not a bait-and-switch.
  Members must always know it's an AI (disclosure requirement from V1
  stands).

---

## 6. Which side to build first

**Recommendation: Side B first (reactive agent), Side A's smart version
second — but Side A's *manual* version ships immediately.** Reasoning:

- **Side B is further along than it looks:** the inbound agent loop already
  exists in this repo and works (webhook → member match → context → Claude →
  reply, with STOP, debounce, human-pause all tested). Each data source from
  section 3 that gets defined becomes something the agent can answer about.
  Value grows source by source; nothing blocks on "all data mapped."
- **Side A's smart version is the harder build** — automatic weekly
  relevance-matching needs *several* clean, tagged sources plus a matching
  layer. That's exactly the scattered-data problem, so it comes after
  sources are defined one by one.
- **But Side A with hand-curated picks needs no data work at all** (a human
  picks 2–3 items; code exists) — so the weekly rhythm can start during the
  pilot anyway, and automation replaces the human curation later.

Build order: **1)** pilot as planned (agent + hand-curated weekly),
**2)** define and connect data sources one at a time — each one upgrades
Side B answers immediately, **3)** when 2–3 sources are clean and tagged,
automate Side A's weekly matching, **4)** actions (make-introduction button,
partner-offer flows).

---

## 7. What's already built (this repo)

Inbound agent loop (Workflow A) with debounce, human-takeover pause,
STOP/START; welcome-draft generation (Workflow B); weekly send with curated
picks (Workflow C); Airtable schema; Olivia prompt; local simulator; tests.
See `README.md`. Channel and datastore layers are single swappable files
pending Andy's provider/stack decision.

---

## 8. Open questions (running list)

1. 🔴 Confirm name + details of who sends the manual onboarding email; paste
   a real example email; list the info she uses; document the send process.
2. 🔴 Document the Intercom flow and the 1:1 call process.
3. 🔴 Sequencing of the WhatsApp intro vs email vs 1:1 call.
4. 🔴 Availability + system-of-record for every source in section 3 (Andy).
5. 🔴 Partner-offer flow (dictation cut off — Eugene to finish this
   thought).
6. 🔴 Intro-making: consent flow and medium (email vs WhatsApp), and whether
   V-next includes an actual "make introduction" button (WhatsApp
   interactive message) or plain text first.
7. 🔴 Naming/positioning decision (section 5).
8. 🔴 Channel decision: official Meta route vs Andy's existing sending
   method (carried over from V1 — still the blocking decision).
9. 🔴 Where member data canonically lives going forward: Airtable vs
   Supabase (affects which adapter gets written).
