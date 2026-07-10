import { test } from 'node:test';
import assert from 'node:assert/strict';
import { logRowsToMessages } from '../src/lib/claude.js';

const row = (direction, message) => ({ fields: { Direction: direction, Message: message } });

test('maps log directions to roles', () => {
  const turns = logRowsToMessages([
    row('inbound', 'hi'),
    row('outbound-agent', 'hey!'),
    row('inbound', 'question?'),
  ]);
  assert.deepEqual(turns, [
    { role: 'user', content: 'hi' },
    { role: 'assistant', content: 'hey!' },
    { role: 'user', content: 'question?' },
  ]);
});

test('merges consecutive same-role rows (burst of texts)', () => {
  const turns = logRowsToMessages([
    row('inbound', 'one'),
    row('inbound', 'two'),
    row('outbound-human', 'human reply'),
    row('outbound-agent', 'agent reply'),
  ]);
  assert.deepEqual(turns, [
    { role: 'user', content: 'one\ntwo' },
    { role: 'assistant', content: 'human reply\nagent reply' },
  ]);
});

test('drops leading assistant rows so the thread starts with the user', () => {
  const turns = logRowsToMessages([row('outbound-agent', 'welcome!'), row('inbound', 'thanks')]);
  assert.deepEqual(turns, [{ role: 'user', content: 'thanks' }]);
});

test('skips empty messages', () => {
  const turns = logRowsToMessages([row('inbound', '  '), row('inbound', 'real')]);
  assert.deepEqual(turns, [{ role: 'user', content: 'real' }]);
});
