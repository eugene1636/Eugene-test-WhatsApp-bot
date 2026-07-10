import express from 'express';
import crypto from 'node:crypto';
import { config } from './config.js';
import { parseWebhookEvents } from './lib/webhookEvents.js';
import { handleInboundMessage, handleHumanEcho } from './workflows/inbound.js';

/**
 * Webhook server. Point the Meta app (or the Coexistence provider's webhook
 * forwarding) at GET/POST /webhook. Subscribed fields: messages,
 * message deliveries (statuses arrive on the messages field), and
 * smb_message_echoes (spec, Sprint 0).
 */

const app = express();

// Keep the raw body for signature verification.
app.use(
  express.json({
    verify: (req, _res, buf) => {
      req.rawBody = buf;
    },
  }),
);

app.get('/health', (_req, res) => res.json({ ok: true, service: 'olivia' }));

// Meta webhook verification handshake.
app.get('/webhook', (req, res) => {
  const mode = req.query['hub.mode'];
  const token = req.query['hub.verify_token'];
  const challenge = req.query['hub.challenge'];
  if (mode === 'subscribe' && token === config.whatsapp.verifyToken) {
    return res.status(200).send(challenge);
  }
  return res.sendStatus(403);
});

app.post('/webhook', (req, res) => {
  if (!verifySignature(req)) {
    console.warn('[webhook] invalid X-Hub-Signature-256 — rejecting');
    return res.sendStatus(401);
  }

  // Ack immediately (Meta retries on slow responses), then process async.
  res.sendStatus(200);

  const events = parseWebhookEvents(req.body);
  for (const event of events) {
    dispatch(event).catch((err) =>
      console.error(`[webhook] error handling ${event.kind}:`, err),
    );
  }
});

async function dispatch(event) {
  switch (event.kind) {
    case 'inbound':
      console.log(`[webhook] inbound from ${event.from}: ${truncate(event.text)}`);
      await handleInboundMessage(event);
      break;
    case 'human-echo':
      console.log(`[webhook] human app-sent echo to ${event.to}: ${truncate(event.text)}`);
      await handleHumanEcho(event);
      break;
    case 'status':
      // Delivery statuses are logged for observability only in V1.
      console.log(`[webhook] status ${event.status} for ${event.id}`);
      break;
    default:
      console.log(`[webhook] ignoring event kind ${event.kind}`);
  }
}

function verifySignature(req) {
  const appSecret = config.whatsapp.appSecret;
  if (!appSecret) return true; // not configured — skip (e.g. local testing)
  const signature = req.get('X-Hub-Signature-256') || '';
  const expected =
    'sha256=' + crypto.createHmac('sha256', appSecret).update(req.rawBody || '').digest('hex');
  try {
    return crypto.timingSafeEqual(Buffer.from(signature), Buffer.from(expected));
  } catch {
    return false;
  }
}

const truncate = (s, n = 80) => (s && s.length > n ? `${s.slice(0, n)}…` : s || '');

app.listen(config.port, () => {
  console.log(`Olivia webhook server listening on :${config.port}`);
});
