import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setTimeout as sleep } from 'node:timers/promises';
import { MessageDebouncer } from '../src/lib/debounce.js';

test('a burst of 3 texts gets 1 flush with the whole batch', async () => {
  const flushes = [];
  const d = new MessageDebouncer(50, (key, batch) => flushes.push({ key, batch }));
  d.push('+1555', 'a');
  await sleep(10);
  d.push('+1555', 'b');
  await sleep(10);
  d.push('+1555', 'c');
  await sleep(120);
  assert.equal(flushes.length, 1);
  assert.deepEqual(flushes[0].batch, ['a', 'b', 'c']);
});

test('separate threads flush independently', async () => {
  const flushes = [];
  const d = new MessageDebouncer(30, (key, batch) => flushes.push({ key, batch }));
  d.push('+1', 'a');
  d.push('+2', 'b');
  await sleep(100);
  assert.equal(flushes.length, 2);
});

test('cancel drops pending replies (human takeover)', async () => {
  const flushes = [];
  const d = new MessageDebouncer(30, (key, batch) => flushes.push({ key, batch }));
  d.push('+1', 'a');
  d.cancel('+1');
  await sleep(80);
  assert.equal(flushes.length, 0);
});
