import { config } from '../src/config.js';

/**
 * One-time Airtable schema additions (spec section 6), applied to the
 * existing MDS Member Database base via the Airtable Metadata API.
 * Idempotent: skips anything that already exists. Requires a token with
 * schema.bases:write scope.
 *
 *   npm run setup:airtable
 */

const META_ROOT = 'https://api.airtable.com/v0/meta/bases';

const MEMBER_FIELDS = [
  { name: 'WhatsApp Phone', type: 'phoneNumber', description: 'E.164 normalized, e.g. +14155550123 — matching key for inbound messages' },
  { name: 'Assistant Pilot', type: 'checkbox', options: { icon: 'check', color: 'greenBright' } },
  { name: 'Weekly Opt-Out', type: 'checkbox', options: { icon: 'check', color: 'redBright' } },
  { name: 'Assistant Profile Summary', type: 'multilineText', description: "Curated 'what we know' blob Claude receives: business type, brand, niche, channel mix, interests, current challenges" },
  { name: 'Last Assistant Touch', type: 'date', options: { dateFormat: { name: 'iso' } }, description: 'Set on every outbound; drives weekly cadence' },
  // Workflow B lands review drafts here (welcome copy, section 5).
  { name: 'Welcome Draft', type: 'multilineText', description: 'Claude-drafted welcome message awaiting human review' },
  { name: 'Welcome Draft Status', type: 'singleSelect', options: { choices: [{ name: 'needs review' }, { name: 'approved' }, { name: 'sent' }] } },
];

const CONVERSATION_LOG_TABLE = {
  name: config.airtable.conversationLogTable,
  description: "Every webhook event (including human app-sent echoes) writes a row. This is the agent's memory.",
  fields: [
    { name: 'Message', type: 'multilineText' },
    { name: 'Direction', type: 'singleSelect', options: { choices: [{ name: 'inbound' }, { name: 'outbound-agent' }, { name: 'outbound-human' }] } },
    { name: 'Timestamp', type: 'dateTime', options: { dateFormat: { name: 'iso' }, timeFormat: { name: '24hour' }, timeZone: 'utc' } },
    { name: 'WhatsApp Message ID', type: 'singleLineText' },
    // 'Member' link field is added after creation, once we know the Members table id.
  ],
};

const PILOT_PICKS_TABLE = {
  name: config.airtable.pilotPicksTable,
  description: 'Hand-curated recommendations per pilot member (V1: humans choose the substance, Claude personalizes the wording).',
  fields: [
    { name: 'Pick Title', type: 'singleLineText' },
    { name: 'Link', type: 'url' },
    { name: 'Type', type: 'singleSelect', options: { choices: [{ name: 'video' }, { name: 'post' }, { name: 'chat' }, { name: 'intro' }, { name: 'event' }] } },
    { name: "Why It's Relevant", type: 'singleLineText' },
    { name: 'Status', type: 'singleSelect', options: { choices: [{ name: 'queued' }, { name: 'sent' }] } },
    { name: 'Week Of', type: 'date', options: { dateFormat: { name: 'iso' } } },
  ],
};

async function metaRequest(method, path, body) {
  const res = await fetch(`${META_ROOT}/${config.airtable.baseId()}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${config.airtable.apiKey()}`,
      'Content-Type': 'application/json',
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(`Airtable meta ${method} ${path} failed (${res.status}): ${JSON.stringify(json)}`);
  }
  return json;
}

async function main() {
  const { tables } = await metaRequest('GET', '/tables');
  const byName = new Map(tables.map((t) => [t.name, t]));

  const members = byName.get(config.airtable.membersTable);
  if (!members) {
    throw new Error(
      `Members table "${config.airtable.membersTable}" not found in base — this script adds to the existing MDS Member Database, it does not create Members.`,
    );
  }

  // 1. New fields on Members
  const existingFieldNames = new Set(members.fields.map((f) => f.name));
  for (const field of MEMBER_FIELDS) {
    if (existingFieldNames.has(field.name)) {
      console.log(`✓ Members.${field.name} already exists`);
      continue;
    }
    await metaRequest('POST', `/tables/${members.id}/fields`, field);
    console.log(`+ created Members.${field.name}`);
  }

  // 2. New tables
  for (const tableSpec of [CONVERSATION_LOG_TABLE, PILOT_PICKS_TABLE]) {
    let table = byName.get(tableSpec.name);
    if (table) {
      console.log(`✓ table "${tableSpec.name}" already exists`);
    } else {
      table = await metaRequest('POST', '/tables', tableSpec);
      console.log(`+ created table "${tableSpec.name}"`);
    }
    // 3. Member link field
    const hasMemberLink = (table.fields || []).some((f) => f.name === 'Member');
    if (!hasMemberLink) {
      await metaRequest('POST', `/tables/${table.id}/fields`, {
        name: 'Member',
        type: 'multipleRecordLinks',
        options: { linkedTableId: members.id },
      });
      console.log(`+ created ${tableSpec.name}.Member link`);
    } else {
      console.log(`✓ ${tableSpec.name}.Member link already exists`);
    }
  }

  console.log('\nDone. Populate 3 test members (Sprint 0) and you are ready to test Workflow A.');
}

main().catch((err) => {
  console.error(err.message);
  process.exit(1);
});
