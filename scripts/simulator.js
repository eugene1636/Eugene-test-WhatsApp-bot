/**
 * Local WhatsApp simulator — test Olivia end-to-end with zero external
 * accounts. Runs the REAL webhook server and Workflow A code; only the
 * three external services are faked:
 *
 *   - WhatsApp Graph API  -> captured and printed as "Olivia -> your phone"
 *   - Airtable            -> in-memory base seeded with you as a pilot member
 *   - Claude              -> canned replies, OR the real API if
 *                            ANTHROPIC_API_KEY is set to a real key
 *
 * Interactive:  npm run simulate
 *   type a message            -> arrives as if you texted the MDS number
 *   /human <text>             -> a human replies from the phone app (echo);
 *                                agent pauses on the thread for 4h
 *   /state                    -> dump the in-memory Airtable
 *   /quit
 *
 * Scripted demo:  npm run simulate -- --demo
 */

import express from 'express';
import readline from 'node:readline';

// ---------------------------------------------------------------------------
// Environment BEFORE any src/ import (config reads env at module load)
// ---------------------------------------------------------------------------
const MOCK_PORT = 4100;
const SERVER_PORT = 4000;
const YOUR_PHONE = '15550001111'; // "your" WhatsApp in the simulation

const hasRealClaudeKey = (process.env.ANTHROPIC_API_KEY || '').startsWith('sk-ant');

process.env.PORT = String(SERVER_PORT);
process.env.DEBOUNCE_SECONDS = process.env.DEBOUNCE_SECONDS || '2'; // fast for testing
process.env.AIRTABLE_API_ROOT = `http://127.0.0.1:${MOCK_PORT}/v0`;
process.env.WHATSAPP_GRAPH_ROOT = `http://127.0.0.1:${MOCK_PORT}/graph`;
if (!hasRealClaudeKey) {
  process.env.ANTHROPIC_API_ROOT = `http://127.0.0.1:${MOCK_PORT}/anthropic`;
  process.env.ANTHROPIC_API_KEY = 'mock-key';
}
process.env.AIRTABLE_API_KEY = process.env.AIRTABLE_API_KEY || 'mock-key';
process.env.AIRTABLE_BASE_ID = process.env.AIRTABLE_BASE_ID || 'appMOCK';
process.env.WHATSAPP_ACCESS_TOKEN = 'mock-token';
process.env.WHATSAPP_PHONE_NUMBER_ID = '999000999';
process.env.WHATSAPP_APP_SECRET = ''; // skip signature check locally

// ---------------------------------------------------------------------------
// In-memory Airtable, seeded per the pilot runbook
// ---------------------------------------------------------------------------
let nextId = 1;
const rec = (fields) => ({ id: `rec${String(nextId++).padStart(4, '0')}`, fields, createdTime: new Date().toISOString() });

const tables = {
  Members: [
    rec({
      Name: 'Eugene (you)',
      'First Name': 'Eugene',
      'WhatsApp Phone': `+${YOUR_PHONE}`,
      'Assistant Pilot': true,
      'Weekly Opt-Out': false,
      'Assistant Profile Summary':
        'Runs Acme Naturals, a DTC supplements brand in the wellness niche, selling on Amazon US and Shopify. Interested in retail expansion and AI for ops; working through rising PPC costs.',
    }),
  ],
  'Conversation Log': [],
  'Pilot Picks': [],
};
const memberId = tables.Members[0].id;
tables['Pilot Picks'].push(
  rec({ Member: [memberId], 'Pick Title': 'PPC Cost Control Masterclass', Link: 'https://mds.example/ppc', Type: 'video', "Why It's Relevant": 'you mentioned rising PPC costs', Status: 'queued' }),
  rec({ Member: [memberId], 'Pick Title': 'Intro to Ben K. (retail expansion)', Type: 'intro', "Why It's Relevant": 'he took a supplements brand into Target last year', Status: 'queued' }),
);

// Interpret exactly the formula shapes src/lib/airtable.js generates.
function matchFormula(formula, record) {
  if (!formula) return true;
  let m;
  if ((m = formula.match(/REGEX_REPLACE\(\{WhatsApp Phone\}[\s\S]*= '(\d+)'/))) {
    return String(record.fields['WhatsApp Phone'] || '').replace(/\D/g, '') === m[1];
  }
  if (formula.includes('{Assistant Pilot} = TRUE()')) return !!record.fields['Assistant Pilot'];
  if ((m = formula.match(/FIND\('([^']+)', ARRAYJOIN\(\{Member\}\)\) > 0/))) {
    const linked = (record.fields.Member || []).includes(m[1]);
    return formula.includes("{Status} = 'queued'") ? linked && record.fields.Status === 'queued' : linked;
  }
  return true;
}

// ---------------------------------------------------------------------------
// Mock backend: Airtable + Graph API + (optionally) Anthropic
// ---------------------------------------------------------------------------
const mock = express();
mock.use(express.json());

mock.get('/v0/:base/:table', (req, res) => {
  const rows = tables[req.params.table] || [];
  let out = rows.filter((r) => matchFormula(req.query.filterByFormula, r));
  const sortField = req.query['sort[0][field]'];
  if (sortField) {
    const dir = req.query['sort[0][direction]'] === 'desc' ? -1 : 1;
    out = [...out].sort((a, b) => {
      const av = String(a.fields[sortField] || '');
      const bv = String(b.fields[sortField] || '');
      return av === bv ? 0 : av < bv ? -dir : dir;
    });
  }
  if (req.query.maxRecords) out = out.slice(0, Number(req.query.maxRecords));
  res.json({ records: out });
});
mock.post('/v0/:base/:table', (req, res) => {
  const record = rec(req.body.fields || {});
  (tables[req.params.table] ||= []).push(record);
  res.json(record);
});
mock.patch('/v0/:base/:table/:id', (req, res) => {
  const record = (tables[req.params.table] || []).find((r) => r.id === req.params.id);
  if (!record) return res.status(404).json({ error: 'not found' });
  Object.assign(record.fields, req.body.fields);
  res.json(record);
});

// WhatsApp Graph API — capture outbound sends and print them.
let wamid = 0;
mock.post('/graph/:version/:phoneId/messages', (req, res) => {
  const body = req.body;
  const text = body.type === 'template' ? `[template ${body.template.name}]` : body.text?.body;
  printOlivia(text);
  res.json({ messages: [{ id: `wamid.mock.${++wamid}` }] });
});

// Canned Claude — only mounted when no real key is present.
mock.post('/anthropic/v1/messages', (req, res) => {
  const turns = req.body.messages || [];
  const lastUser = [...turns].reverse().find((t) => t.role === 'user');
  const text =
    `Hey! (mock Claude — set a real ANTHROPIC_API_KEY for live Olivia replies)\n` +
    `I got your message${turns.length > 1 ? ` and I can see our ${turns.length}-turn history` : ''}: ` +
    `"${String(lastUser?.content || '').slice(0, 120)}"\n` +
    `Based on your profile I'd point you at the PPC Cost Control Masterclass 👀`;
  res.json({ content: [{ type: 'text', text }] });
});

// ---------------------------------------------------------------------------
// Drive the REAL server with webhook payloads
// ---------------------------------------------------------------------------
const WEBHOOK = `http://127.0.0.1:${SERVER_PORT}/webhook`;
const unix = () => String(Math.floor(Date.now() / 1000));

const post = (field, value) =>
  fetch(WEBHOOK, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ object: 'whatsapp_business_account', entry: [{ id: '0', changes: [{ field, value }] }] }),
  });

const sendAsYou = (text) =>
  post('messages', {
    messages: [{ from: YOUR_PHONE, id: `wamid.you.${++wamid}`, timestamp: unix(), type: 'text', text: { body: text } }],
  });

const sendAsHuman = (text) =>
  post('smb_message_echoes', {
    message_echoes: [{ to: YOUR_PHONE, id: `wamid.human.${++wamid}`, timestamp: unix(), type: 'text', text: { body: text } }],
  });

// ---------------------------------------------------------------------------
// Output helpers
// ---------------------------------------------------------------------------
const line = () => console.log('─'.repeat(64));
function printOlivia(text) {
  line();
  console.log(`📱  Olivia → your WhatsApp:\n${text}`);
  line();
  rl?.prompt();
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const debounceMs = Number(process.env.DEBOUNCE_SECONDS) * 1000;

function printState() {
  const m = tables.Members[0].fields;
  console.log(`Member: ${m.Name} | Weekly Opt-Out: ${m['Weekly Opt-Out']} | Last Assistant Touch: ${m['Last Assistant Touch'] || '—'}`);
  console.log('Conversation Log:');
  for (const r of tables['Conversation Log']) {
    console.log(`  [${r.fields.Direction}] ${String(r.fields.Message).replace(/\n/g, ' ').slice(0, 70)}`);
  }
}

// ---------------------------------------------------------------------------
// Boot mock + real server, then run demo or REPL
// ---------------------------------------------------------------------------
let rl = null;

mock.listen(MOCK_PORT, async () => {
  await import('../src/server.js'); // the real Olivia server, pointed at the mocks
  await sleep(300);
  console.log(`\nSimulator ready. You are "${tables.Members[0].fields.Name}" texting the MDS number.`);
  console.log(`Claude: ${hasRealClaudeKey ? 'REAL API' : 'mocked (set ANTHROPIC_API_KEY for live replies)'} | debounce: ${debounceMs / 1000}s\n`);

  if (process.argv.includes('--demo')) return demo();

  rl = readline.createInterface({ input: process.stdin, output: process.stdout, prompt: 'you> ' });
  console.log('Type a message. Commands: /human <text>, /state, /quit\n');
  rl.prompt();
  rl.on('line', async (input) => {
    const text = input.trim();
    if (!text) return rl.prompt();
    if (text === '/quit') process.exit(0);
    if (text === '/state') { printState(); return rl.prompt(); }
    if (text.startsWith('/human ')) {
      await sendAsHuman(text.slice(7));
      console.log('(human replied from the phone app — agent now pauses on this thread)');
      return rl.prompt();
    }
    await sendAsYou(text);
    rl.prompt();
  });
});

async function demo() {
  console.log('=== DEMO 1: burst of 3 texts gets ONE coherent reply (debounce) ===');
  await sendAsYou('hey Olivia');
  await sleep(300);
  await sendAsYou('quick question');
  await sleep(300);
  await sendAsYou('my PPC costs are killing me, anything in MDS that can help?');
  await sleep(debounceMs + 2500);

  console.log('\n=== DEMO 2: STOP opts out instantly (deterministic, not the model) ===');
  await sendAsYou('STOP');
  await sleep(1200);

  console.log('\n=== DEMO 3: START opts back in ===');
  await sendAsYou('start');
  await sleep(1200);

  console.log('\n=== DEMO 4: human takes over from the phone app -> agent goes silent ===');
  await sendAsHuman("Hey Eugene, Kat here — I'll personally walk you through the PPC stuff tomorrow!");
  await sleep(300);
  await sendAsYou('amazing, what time works?');
  await sleep(debounceMs + 2500);
  console.log('(no Olivia reply above = correct: a human owns this thread for the next 4h)');

  console.log('\n=== Final Airtable state ===');
  printState();
  process.exit(0);
}
