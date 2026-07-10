/**
 * Phone normalization to E.164 (spec section 6: "WhatsApp Phone (E.164
 * normalized, e.g. +14155550123) — matching key for inbound messages").
 *
 * WhatsApp webhooks deliver the sender as digits without a plus
 * (e.g. "14155550123"); Airtable may hold formatted numbers
 * (e.g. "+1 (415) 555-0123"). Both must normalize to the same key.
 */

/**
 * Normalize any phone-ish string to E.164: "+" followed by digits only.
 * Returns null when the input can't plausibly be a phone number.
 */
export function normalizePhone(raw) {
  if (raw === null || raw === undefined) return null;
  const digits = String(raw).replace(/[^\d]/g, '');
  // E.164 numbers are 7–15 digits including country code.
  if (digits.length < 7 || digits.length > 15) return null;
  return `+${digits}`;
}

/**
 * WhatsApp Cloud API "to" field wants digits without the leading "+".
 */
export function toWhatsAppId(e164) {
  const normalized = normalizePhone(e164);
  return normalized ? normalized.slice(1) : null;
}
