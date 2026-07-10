import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { renderTemplate } from './messages.js';

const promptPath = fileURLToPath(new URL('./olivia-system-prompt.md', import.meta.url));

/**
 * Build the fully-interpolated Olivia system prompt for one member
 * (spec section 7). The recent conversation itself is passed to Claude
 * as message turns, not inside the system prompt.
 *
 * @param {object} member - Airtable Members record
 * @param {Array} picks - Airtable Pilot Picks records (queued)
 */
export function buildSystemPrompt(member, picks) {
  const template = readFileSync(promptPath, 'utf8');
  const profile =
    member.fields['Assistant Profile Summary'] ||
    'No profile summary on file yet — ask light questions to learn about their business.';
  const picksText = picks.length
    ? picks
        .map((p) => {
          const f = p.fields;
          const why = f["Why It's Relevant"] || f['Why It’s Relevant'] || '';
          return `- ${f['Pick Title'] || 'Untitled'} (${f.Type || 'resource'})${f.Link ? ` ${f.Link}` : ''}${why ? ` — ${why}` : ''}`;
        })
        .join('\n')
    : 'No picks queued right now — do not invent any.';

  return renderTemplate(template, {
    assistant_profile_summary: profile,
    pilot_picks: picksText,
  });
}
