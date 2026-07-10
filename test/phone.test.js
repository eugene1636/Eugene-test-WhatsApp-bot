import { test } from 'node:test';
import assert from 'node:assert/strict';
import { normalizePhone, toWhatsAppId } from '../src/lib/phone.js';

test('normalizes webhook sender (digits, no plus)', () => {
  assert.equal(normalizePhone('14155550123'), '+14155550123');
});

test('normalizes formatted Airtable numbers', () => {
  assert.equal(normalizePhone('+1 (415) 555-0123'), '+14155550123');
  assert.equal(normalizePhone('001-415-555-0123'.replace(/^00/, '')), '+14155550123');
});

test('already-E.164 passes through', () => {
  assert.equal(normalizePhone('+14155550123'), '+14155550123');
});

test('rejects garbage and too-short/long input', () => {
  assert.equal(normalizePhone(''), null);
  assert.equal(normalizePhone(null), null);
  assert.equal(normalizePhone('hello'), null);
  assert.equal(normalizePhone('123'), null);
  assert.equal(normalizePhone('1'.repeat(16)), null);
});

test('toWhatsAppId strips the plus', () => {
  assert.equal(toWhatsAppId('+14155550123'), '14155550123');
  assert.equal(toWhatsAppId('bad'), null);
});
