import { config } from '../config.js';
import { toWhatsAppId } from './phone.js';

/**
 * WhatsApp Cloud API client. The number runs in Coexistence mode: it lives on
 * the WhatsApp Business app (human oversight on the phone) AND the Cloud API
 * (this code) at the same time (spec section 2).
 */

async function graphRequest(payload) {
  const { apiVersion } = config.whatsapp;
  // Overridable so the local simulator can stand in for the Graph API.
  const graphRoot = process.env.WHATSAPP_GRAPH_ROOT || 'https://graph.facebook.com';
  const url = `${graphRoot}/${apiVersion}/${config.whatsapp.phoneNumberId()}/messages`;
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${config.whatsapp.accessToken()}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(`WhatsApp send failed (${res.status}): ${JSON.stringify(body)}`);
  }
  return body;
}

/**
 * Free-form text message. Only deliverable inside an open 24-hour session
 * (i.e. after the member has messaged us). Returns the WhatsApp message id.
 */
export async function sendText(toPhone, text) {
  const to = toWhatsAppId(toPhone);
  if (!to) throw new Error(`Cannot send: invalid phone ${toPhone}`);
  const body = await graphRequest({
    messaging_product: 'whatsapp',
    recipient_type: 'individual',
    to,
    type: 'text',
    text: { preview_url: true, body: text },
  });
  return body.messages?.[0]?.id || null;
}

/**
 * Approved Meta template message — needed to message members outside a
 * 24-hour session (weekly digest, Sprint 2).
 */
export async function sendTemplate(toPhone, templateName, languageCode, bodyParameters = []) {
  const to = toWhatsAppId(toPhone);
  if (!to) throw new Error(`Cannot send: invalid phone ${toPhone}`);
  const body = await graphRequest({
    messaging_product: 'whatsapp',
    recipient_type: 'individual',
    to,
    type: 'template',
    template: {
      name: templateName,
      language: { code: languageCode },
      components: bodyParameters.length
        ? [
            {
              type: 'body',
              parameters: bodyParameters.map((text) => ({ type: 'text', text: String(text) })),
            },
          ]
        : [],
    },
  });
  return body.messages?.[0]?.id || null;
}
