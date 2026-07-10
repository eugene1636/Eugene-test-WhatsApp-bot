import { config } from '../config.js';
import {
  listPilotMembers,
  getQueuedPicks,
  markPickSent,
  logMessage,
  touchMember,
} from '../lib/airtable.js';
import { sendTemplate, sendText } from '../lib/whatsapp.js';
import { WEEKLY_DIGEST_TEMPLATE, renderTemplate } from '../prompts/messages.js';

/**
 * Workflow C — Weekly digest (spec, Sprint 2): scheduled per member; pulls
 * fresh picks; skips the member entirely if nothing genuinely relevant;
 * respects Weekly Opt-Out.
 *
 * Messaging outside a 24-hour session requires an approved Meta template,
 * so the default send uses the template registered as DIGEST_TEMPLATE_NAME
 * with body variables {{1}}..{{4}} = first name + three pick lines.
 * Pass { asText: true } for testing inside an open session.
 */

export async function sendWeeklyDigests({ dryRun = false, asText = false } = {}) {
  const members = await listPilotMembers();
  console.log(`[digest] considering ${members.length} pilot member(s)`);
  const results = [];

  for (const member of members) {
    const name = member.fields.Name || member.fields['First Name'] || member.id;
    const firstName = member.fields['First Name'] || String(name).split(' ')[0];
    try {
      if (member.fields['Weekly Opt-Out']) {
        results.push({ member: name, skipped: 'opted out' });
        continue;
      }
      const phone = member.fields['WhatsApp Phone'];
      if (!phone) {
        results.push({ member: name, skipped: 'no WhatsApp Phone' });
        continue;
      }
      const picks = (await getQueuedPicks(member.id)).slice(0, 3);
      if (!picks.length) {
        // "skips the member entirely if nothing genuinely relevant"
        results.push({ member: name, skipped: 'no queued picks' });
        continue;
      }

      const pickVars = {};
      picks.forEach((p, i) => {
        const f = p.fields;
        pickVars[`pick_${i + 1}`] = `${f['Pick Title']}${f.Link ? ` (${f.Link})` : ''}`;
        pickVars[`why_${i + 1}`] = f["Why It's Relevant"] || f['Why It’s Relevant'] || '';
      });
      const bodyText = renderTemplate(WEEKLY_DIGEST_TEMPLATE, { first_name: firstName, ...pickVars })
        // Drop lines whose placeholders went unfilled (fewer than 3 picks).
        .split('\n')
        .filter((line) => !/\{(pick|why)_\d\}/.test(line))
        .join('\n');

      if (dryRun) {
        results.push({ member: name, wouldSend: bodyText });
        continue;
      }

      let messageId;
      if (asText) {
        messageId = await sendText(phone, bodyText);
      } else {
        const pickLines = picks.map((p, i) => {
          const f = p.fields;
          const why = f["Why It's Relevant"] || f['Why It’s Relevant'] || '';
          return `${f['Pick Title']}${f.Link ? ` (${f.Link})` : ''}${why ? ` — ${why}` : ''}`;
        });
        while (pickLines.length < 3) pickLines.push('—');
        messageId = await sendTemplate(
          phone,
          config.behaviour.digestTemplateName,
          config.behaviour.digestTemplateLanguage,
          [firstName, ...pickLines],
        );
      }

      await logMessage({
        memberId: member.id,
        direction: 'outbound-agent',
        message: bodyText,
        whatsappMessageId: messageId,
      });
      await touchMember(member.id);
      await Promise.all(picks.map((p) => markPickSent(p.id)));
      console.log(`[digest] sent to ${name}`);
      results.push({ member: name, sent: true });
    } catch (err) {
      console.error(`[digest] failed for ${name}:`, err.message);
      results.push({ member: name, error: err.message });
    }
  }
  return results;
}
