import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseWebhookEvents } from '../src/lib/webhookEvents.js';

const wrap = (field, value) => ({
  object: 'whatsapp_business_account',
  entry: [{ id: '0', changes: [{ field, value }] }],
});

test('parses inbound text messages', () => {
  const events = parseWebhookEvents(
    wrap('messages', {
      messages: [
        { from: '14155550123', id: 'wamid.1', timestamp: '1752105600', type: 'text', text: { body: 'hey Olivia' } },
      ],
    }),
  );
  assert.equal(events.length, 1);
  assert.equal(events[0].kind, 'inbound');
  assert.equal(events[0].from, '14155550123');
  assert.equal(events[0].text, 'hey Olivia');
  assert.equal(events[0].timestamp, new Date(1752105600 * 1000).toISOString());
});

test('parses delivery statuses', () => {
  const events = parseWebhookEvents(
    wrap('messages', {
      statuses: [{ id: 'wamid.2', status: 'delivered', recipient_id: '14155550123', timestamp: '1752105600' }],
    }),
  );
  assert.equal(events[0].kind, 'status');
  assert.equal(events[0].status, 'delivered');
});

test('parses smb_message_echoes (human app-sent messages)', () => {
  const events = parseWebhookEvents(
    wrap('smb_message_echoes', {
      message_echoes: [
        { to: '14155550123', id: 'wamid.3', timestamp: '1752105600', type: 'text', text: { body: 'human here, taking over' } },
      ],
    }),
  );
  assert.equal(events[0].kind, 'human-echo');
  assert.equal(events[0].to, '14155550123');
  assert.equal(events[0].text, 'human here, taking over');
});

test('non-text messages get a placeholder body', () => {
  const events = parseWebhookEvents(
    wrap('messages', {
      messages: [{ from: '1415', id: 'wamid.4', timestamp: '1752105600', type: 'audio', audio: { id: 'x' } }],
    }),
  );
  assert.equal(events[0].text, '[audio message]');
});

test('empty/odd payloads produce no events', () => {
  assert.deepEqual(parseWebhookEvents({}), []);
  assert.deepEqual(parseWebhookEvents(null), []);
});
