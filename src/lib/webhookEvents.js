/**
 * Parse WhatsApp Cloud API webhook payloads into flat events.
 *
 * We subscribe to three event types (spec, Sprint 0):
 *  - inbound messages           -> { kind: 'inbound', from, text, id, timestamp }
 *  - delivery status            -> { kind: 'status', status, id, recipient }
 *  - smb_message_echoes         -> { kind: 'human-echo', to, text, id, timestamp }
 *    (messages sent by humans from the WhatsApp Business app — Coexistence)
 */
export function parseWebhookEvents(payload) {
  const events = [];
  for (const entry of payload?.entry || []) {
    for (const change of entry.changes || []) {
      const { field, value } = change;

      if (field === 'messages' && value?.messages) {
        for (const message of value.messages) {
          events.push({
            kind: 'inbound',
            from: message.from,
            id: message.id,
            timestamp: tsToIso(message.timestamp),
            text: extractText(message),
            type: message.type,
          });
        }
      }

      if (field === 'messages' && value?.statuses) {
        for (const status of value.statuses) {
          events.push({
            kind: 'status',
            id: status.id,
            status: status.status,
            recipient: status.recipient_id,
            timestamp: tsToIso(status.timestamp),
          });
        }
      }

      if (field === 'smb_message_echoes') {
        const echoes = value?.message_echoes || value?.messages || [];
        for (const echo of echoes) {
          events.push({
            kind: 'human-echo',
            to: echo.to,
            id: echo.id,
            timestamp: tsToIso(echo.timestamp),
            text: extractText(echo),
          });
        }
      }
    }
  }
  return events;
}

function extractText(message) {
  if (message.text?.body) return message.text.body;
  if (message.button?.text) return message.button.text;
  if (message.interactive?.button_reply?.title) return message.interactive.button_reply.title;
  if (message.interactive?.list_reply?.title) return message.interactive.list_reply.title;
  if (message.reaction?.emoji) return message.reaction.emoji;
  if (message.type && message.type !== 'text') return `[${message.type} message]`;
  return '';
}

function tsToIso(timestamp) {
  if (!timestamp) return new Date().toISOString();
  const n = Number(timestamp);
  // WhatsApp sends unix seconds as a string.
  if (Number.isFinite(n)) return new Date(n * 1000).toISOString();
  return new Date(timestamp).toISOString();
}
