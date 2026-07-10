import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  isStopMessage,
  isStartMessage,
  renderTemplate,
  WEEKLY_DIGEST_TEMPLATE,
} from '../src/prompts/messages.js';

test('STOP detected in any casing, with whitespace/punctuation', () => {
  assert.ok(isStopMessage('STOP'));
  assert.ok(isStopMessage('stop'));
  assert.ok(isStopMessage('  Stop!  '));
  assert.ok(isStopMessage('stop.'));
});

test('STOP not detected inside a real question', () => {
  assert.ok(!isStopMessage('how do I stop churn?'));
  assert.ok(!isStopMessage('stop losing money on PPC'));
  assert.ok(!isStopMessage(''));
  assert.ok(!isStopMessage(null));
});

test('START detected the same way', () => {
  assert.ok(isStartMessage('START'));
  assert.ok(isStartMessage(' start '));
  assert.ok(!isStartMessage('start selling on TikTok?'));
});

test('renderTemplate fills variables and leaves unknowns intact', () => {
  const out = renderTemplate('Hey {first_name}, {unknown}', { first_name: 'Ana' });
  assert.equal(out, 'Hey Ana, {unknown}');
});

test('digest template renders with picks', () => {
  const out = renderTemplate(WEEKLY_DIGEST_TEMPLATE, {
    first_name: 'Ana',
    pick_1: 'PPC Masterclass',
    why_1: 'you asked about ad costs',
    pick_2: 'Intro to Ben',
    why_2: 'same niche',
    pick_3: 'Q3 meetup',
    why_3: 'near you',
  });
  assert.match(out, /Hey Ana, Olivia here/);
  assert.match(out, /1\. PPC Masterclass — you asked about ad costs/);
});
