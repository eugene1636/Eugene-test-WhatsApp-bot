import { listPilotMembers, getQueuedPicks, updateMember } from '../lib/airtable.js';
import { askClaude } from '../lib/claude.js';
import { WELCOME_TEMPLATE } from '../prompts/messages.js';

/**
 * Workflow B — Welcome drafts (spec, Sprint 1): for each pilot member,
 * Claude fills the welcome copy (section 5) from their profile + picks;
 * drafts land in Airtable ("Welcome Draft" field on Members) for
 * Eugene/Kat to review and edit. Nothing is sent by this workflow — the
 * approved welcomes go out manually from the phone app.
 */

const DRAFT_SYSTEM_PROMPT = `You draft WhatsApp welcome messages for Olivia, the MDS AI assistant.
You will receive a message template, a member profile summary, and their hand-curated picks.
Fill in the template's {variables} from the profile and picks. Keep the template's structure,
tone, and the STOP line exactly. If the profile lacks a fact (e.g. no niche on file), rewrite
that sentence gracefully around what IS known instead of guessing — never invent facts.
If there are only 2 picks, list 2. Return ONLY the finished message text, no commentary.`;

export async function generateWelcomeDrafts({ dryRun = false } = {}) {
  const members = await listPilotMembers();
  console.log(`[welcome-drafts] ${members.length} pilot member(s)`);
  const results = [];

  for (const member of members) {
    const name = member.fields.Name || member.fields['First Name'] || member.id;
    try {
      const picks = await getQueuedPicks(member.id);
      const profile = member.fields['Assistant Profile Summary'] || '(no profile summary on file)';
      const picksText = picks.length
        ? picks
            .map((p, i) => {
              const f = p.fields;
              const why = f["Why It's Relevant"] || f['Why It’s Relevant'] || '';
              return `${i + 1}. ${f['Pick Title']}${f.Link ? ` (${f.Link})` : ''} — ${why}`;
            })
            .join('\n')
        : '(no picks queued yet)';

      const draft = await askClaude(DRAFT_SYSTEM_PROMPT, [
        {
          role: 'user',
          content: `Template:\n${WELCOME_TEMPLATE}\n\nMember name: ${name}\n\nProfile summary:\n${profile}\n\nCurated picks:\n${picksText}`,
        },
      ]);

      if (!dryRun) {
        await updateMember(member.id, {
          'Welcome Draft': draft,
          'Welcome Draft Status': 'needs review',
        });
      }
      console.log(`[welcome-drafts] drafted for ${name}`);
      results.push({ member: name, ok: true, draft });
    } catch (err) {
      console.error(`[welcome-drafts] failed for ${name}:`, err.message);
      results.push({ member: name, ok: false, error: err.message });
    }
  }
  return results;
}
