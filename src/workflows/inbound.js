import { config } from '../config.js';
import {
  findMemberByPhone,
  logMessage,
  getRecentLog,
  humanRepliedRecently,
  getQueuedPicks,
  setWeeklyOptOut,
  touchMember,
} from '../lib/airtable.js';
import { sendText } from '../lib/whatsapp.js';
import { askClaude, logRowsToMessages } from '../lib/claude.js';
import { buildSystemPrompt } from '../prompts/systemPrompt.js';
import { MessageDebouncer } from '../lib/debounce.js';
import { normalizePhone } from '../lib/phone.js';
import {
  isStopMessage,
  isStartMessage,
  STOP_CONFIRMATION,
  START_CONFIRMATION,
} from '../prompts/messages.js';

/**
 * Workflow A — Inbound handler (spec, Sprint 0):
 * webhook → normalize phone → match member → log → Claude → send → log reply.
 *
 * Rules layered on top:
 *  - Debounce: batch a burst of texts into one reply.
 *  - STOP/START: opt-out handling with immediate confirmation (no debounce).
 *  - Human-pause: if a human replied from the phone app in the last 4 hours,
 *    the agent stays silent on that thread.
 */

const debouncer = new MessageDebouncer(config.behaviour.debounceMs, (phone, batch) =>
  replyToBatch(phone, batch),
);

/** Entry point for each parsed inbound webhook event. */
export async function handleInboundMessage(event) {
  const phone = normalizePhone(event.from);
  if (!phone) {
    console.warn(`[inbound] unparseable sender: ${event.from}`);
    return;
  }

  const member = await findMemberByPhone(phone);
  if (!member) {
    // Unknown numbers are logged (unlinked) and left to the human on the phone.
    console.warn(`[inbound] no member match for ${phone}; leaving to human`);
    await logMessage({
      direction: 'inbound',
      message: `[unmatched ${phone}] ${event.text}`,
      timestamp: event.timestamp,
      whatsappMessageId: event.id,
    });
    return;
  }

  await logMessage({
    memberId: member.id,
    direction: 'inbound',
    message: event.text,
    timestamp: event.timestamp,
    whatsappMessageId: event.id,
  });

  // STOP/START are handled deterministically and immediately — never left
  // to the model, never debounced (spec, Sprint 1: STOP handling).
  if (isStopMessage(event.text)) {
    debouncer.cancel(phone);
    await setWeeklyOptOut(member.id, true);
    await sendAgentReply(member, phone, STOP_CONFIRMATION);
    return;
  }
  if (isStartMessage(event.text)) {
    debouncer.cancel(phone);
    await setWeeklyOptOut(member.id, false);
    await sendAgentReply(member, phone, START_CONFIRMATION);
    return;
  }

  debouncer.push(phone, { member, event });
}

/**
 * Handle a human app-sent message echo (Coexistence): log it as
 * outbound-human and cancel any pending agent reply on that thread —
 * the human has taken over.
 */
export async function handleHumanEcho(event) {
  const phone = normalizePhone(event.to);
  if (phone) debouncer.cancel(phone);
  const member = phone ? await findMemberByPhone(phone) : null;
  await logMessage({
    memberId: member?.id,
    direction: 'outbound-human',
    message: member ? event.text : `[unmatched ${event.to}] ${event.text}`,
    timestamp: event.timestamp,
    whatsappMessageId: event.id,
  });
}

async function replyToBatch(phone, batch) {
  const { member } = batch[batch.length - 1];

  // Human-pause rule: re-check at send time, not just arrival time.
  if (await humanRepliedRecently(member.id)) {
    console.log(`[inbound] human active on ${phone} in last ${config.behaviour.humanPauseMs / 3600000}h — staying silent`);
    return;
  }

  const [logRows, picks] = await Promise.all([
    getRecentLog(member.id),
    getQueuedPicks(member.id),
  ]);

  const system = buildSystemPrompt(member, picks);

  // The current batch is already in the log, but WhatsApp timestamps are
  // whole seconds, so a burst ties on Timestamp and can come back from
  // Airtable out of order. Drop the batch's rows from history and append
  // the batch itself (which is in arrival order) as the final user turn.
  const batchIds = new Set(batch.map((b) => b.event.id));
  const history = logRows.filter((r) => !batchIds.has(r.fields['WhatsApp Message ID']));
  const messages = logRowsToMessages(history);
  const batchText = batch.map((b) => b.event.text).join('\n');
  const last = messages[messages.length - 1];
  if (last && last.role === 'user') {
    last.content += `\n${batchText}`; // keep roles alternating
  } else {
    messages.push({ role: 'user', content: batchText });
  }

  const reply = await askClaude(system, messages);
  if (!reply) {
    console.warn(`[inbound] empty model reply for ${phone}; staying silent`);
    return;
  }

  await sendAgentReply(member, phone, reply);
}

async function sendAgentReply(member, phone, text) {
  const messageId = await sendText(phone, text);
  await logMessage({
    memberId: member.id,
    direction: 'outbound-agent',
    message: text,
    whatsappMessageId: messageId,
  });
  await touchMember(member.id);
}
