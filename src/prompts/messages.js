/**
 * Message copy — spec section 5, verbatim. Claude fills the variables;
 * a human approves welcome messages before send.
 */

export const WELCOME_TEMPLATE = `Hey {first_name} — I’m Olivia, your MDS AI assistant 👋

I’ll message you once a week with 2–3 things that might be relevant for you — a new video, post, chat, an introduction to another member, or an upcoming event. Type STOP anytime if you don’t want the weekly updates.

You can also message me anytime with questions about MDS or issues you’re running into in your business, and I’ll do my best to find you a resource.

Here’s what I know about you so far: you run {brand_name}, a {business_type} brand in {niche}, selling on {channel_mix}. You’ve mentioned you’re interested in {interests} and working through {challenges} — tell me if I got any of that wrong!

A few things that might be relevant for you right now:
1. {pick_1} — {why_1}
2. {pick_2} — {why_2}
3. {pick_3} — {why_3}`;

export const STOP_CONFIRMATION =
  'Got it — no more weekly updates from me. You can still message me anytime and I’ll help however I can. Type START if you ever want the weekly picks back.';

export const START_CONFIRMATION =
  'Welcome back 👋 You’re on the list for weekly picks again. And as always, message me anytime.';

export const WEEKLY_DIGEST_TEMPLATE = `Hey {first_name}, Olivia here with this week’s picks for you:
1. {pick_1} — {why_1}
2. {pick_2} — {why_2}
3. {pick_3} — {why_3}
Reply anytime and I’ll dig into any of these with you — or tell me what you’re working on and I’ll find something better.`;

/** Replace {placeholders} with values; unknown placeholders are left intact. */
export function renderTemplate(template, variables) {
  return template.replace(/\{([a-z0-9_]+)\}/gi, (match, key) =>
    variables[key] !== undefined && variables[key] !== null && variables[key] !== ''
      ? String(variables[key])
      : match,
  );
}

/**
 * STOP/START detection (spec: "inbound 'stop' (any casing) sets
 * Weekly Opt-Out = true"). Matches the bare keyword, tolerating
 * whitespace and trailing punctuation, but not keyword-in-a-sentence —
 * "how do I stop churn?" must NOT opt anyone out.
 */
export function isStopMessage(text) {
  return /^\s*stop\s*[.!]*\s*$/i.test(text || '');
}

export function isStartMessage(text) {
  return /^\s*start\s*[.!]*\s*$/i.test(text || '');
}

/** Format picks (Airtable Pilot Picks records) into numbered digest lines. */
export function formatPickLines(picks) {
  return picks
    .map((pick, i) => {
      const title = pick.fields['Pick Title'] || 'Untitled';
      const link = pick.fields.Link ? ` ${pick.fields.Link}` : '';
      const why = pick.fields["Why It's Relevant"] || pick.fields['Why It’s Relevant'] || '';
      return `${i + 1}. ${title}${link}${why ? ` — ${why}` : ''}`;
    })
    .join('\n');
}
