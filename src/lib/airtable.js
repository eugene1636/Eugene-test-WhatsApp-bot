import { config } from '../config.js';
import { normalizePhone } from './phone.js';

/**
 * Minimal Airtable REST client for the MDS Member Database base
 * (spec section 6). Tables: Members, Conversation Log, Pilot Picks.
 */

// Overridable so the local simulator can stand in for Airtable.
const API_ROOT = process.env.AIRTABLE_API_ROOT || 'https://api.airtable.com/v0';

async function airtableRequest(method, path, body) {
  const url = `${API_ROOT}/${config.airtable.baseId()}/${encodeURIComponent(path.table)}${path.suffix || ''}`;
  const res = await fetch(url, {
    method,
    headers: {
      Authorization: `Bearer ${config.airtable.apiKey()}`,
      'Content-Type': 'application/json',
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Airtable ${method} ${path.table} failed (${res.status}): ${text}`);
  }
  return res.json();
}

async function listAll(table, params = {}) {
  const records = [];
  let offset;
  do {
    const query = new URLSearchParams();
    if (params.filterByFormula) query.set('filterByFormula', params.filterByFormula);
    if (params.maxRecords) query.set('maxRecords', String(params.maxRecords));
    if (params.sort) {
      params.sort.forEach((s, i) => {
        query.set(`sort[${i}][field]`, s.field);
        query.set(`sort[${i}][direction]`, s.direction || 'asc');
      });
    }
    if (offset) query.set('offset', offset);
    const page = await airtableRequest('GET', { table, suffix: `?${query}` });
    records.push(...page.records);
    offset = page.offset;
  } while (offset && (!params.maxRecords || records.length < params.maxRecords));
  return records;
}

// Escape a value for interpolation inside an Airtable formula string literal.
function formulaString(value) {
  return `'${String(value).replace(/\\/g, '\\\\').replace(/'/g, "\\'")}'`;
}

// ---------------------------------------------------------------------------
// Members
// ---------------------------------------------------------------------------

/** Find the member whose "WhatsApp Phone" matches an inbound sender. */
export async function findMemberByPhone(rawPhone) {
  const phone = normalizePhone(rawPhone);
  if (!phone) return null;
  // Compare digits-only so formatting differences in Airtable don't break matching.
  const digits = phone.slice(1);
  const formula = `REGEX_REPLACE({WhatsApp Phone} & '', '[^0-9]', '') = ${formulaString(digits)}`;
  const records = await listAll(config.airtable.membersTable, {
    filterByFormula: formula,
    maxRecords: 1,
  });
  return records[0] || null;
}

/** All members flagged Assistant Pilot = true. */
export async function listPilotMembers() {
  return listAll(config.airtable.membersTable, {
    filterByFormula: '{Assistant Pilot} = TRUE()',
  });
}

export async function updateMember(memberId, fields) {
  return airtableRequest('PATCH', { table: config.airtable.membersTable, suffix: `/${memberId}` }, { fields });
}

export async function setWeeklyOptOut(memberId, optedOut) {
  return updateMember(memberId, { 'Weekly Opt-Out': optedOut });
}

/** Set on every outbound message; drives weekly cadence (spec section 6). */
export async function touchMember(memberId) {
  return updateMember(memberId, {
    'Last Assistant Touch': new Date().toISOString().slice(0, 10),
  });
}

// ---------------------------------------------------------------------------
// Conversation Log
// ---------------------------------------------------------------------------

/**
 * Every webhook event (including human app-sent echoes) writes a row.
 * direction: 'inbound' | 'outbound-agent' | 'outbound-human'
 */
export async function logMessage({ memberId, direction, message, timestamp, whatsappMessageId }) {
  const fields = {
    Direction: direction,
    Message: message,
    Timestamp: timestamp || new Date().toISOString(),
  };
  if (memberId) fields.Member = [memberId];
  if (whatsappMessageId) fields['WhatsApp Message ID'] = whatsappMessageId;
  return airtableRequest('POST', { table: config.airtable.conversationLogTable }, { fields });
}

/** Last N log rows for a member, oldest first — the agent's memory. */
export async function getRecentLog(memberId, limit = config.behaviour.logContextRows) {
  const formula = `FIND(${formulaString(memberId)}, ARRAYJOIN({Member})) > 0`;
  const records = await listAll(config.airtable.conversationLogTable, {
    filterByFormula: formula,
    sort: [{ field: 'Timestamp', direction: 'desc' }],
    maxRecords: limit,
  });
  return records.reverse();
}

/**
 * Human-pause rule (spec, Sprint 0): true when an app-sent (human) message
 * echo exists on this member's thread within the pause window.
 */
export async function humanRepliedRecently(memberId, windowMs = config.behaviour.humanPauseMs) {
  const rows = await getRecentLog(memberId, config.behaviour.logContextRows);
  const cutoff = Date.now() - windowMs;
  return rows.some(
    (r) =>
      r.fields.Direction === 'outbound-human' &&
      new Date(r.fields.Timestamp).getTime() >= cutoff,
  );
}

// ---------------------------------------------------------------------------
// Pilot Picks
// ---------------------------------------------------------------------------

/** Queued picks for a member (hand-curated in V1). */
export async function getQueuedPicks(memberId) {
  const formula = `AND(FIND(${formulaString(memberId)}, ARRAYJOIN({Member})) > 0, {Status} = 'queued')`;
  return listAll(config.airtable.pilotPicksTable, { filterByFormula: formula });
}

export async function markPickSent(pickId) {
  return airtableRequest('PATCH', { table: config.airtable.pilotPicksTable, suffix: `/${pickId}` }, {
    fields: { Status: 'sent' },
  });
}
