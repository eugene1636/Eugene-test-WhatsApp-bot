import { config } from '../config.js';

/**
 * Claude API client (spec section 2: "Brain — Claude API").
 */

const API_URL = 'https://api.anthropic.com/v1/messages';

/**
 * @param {string} system - the fully-interpolated Olivia system prompt
 * @param {Array<{role: 'user'|'assistant', content: string}>} messages
 * @returns {Promise<string>} Olivia's reply text
 */
export async function askClaude(system, messages, { maxTokens = 1024 } = {}) {
  const res = await fetch(API_URL, {
    method: 'POST',
    headers: {
      'x-api-key': config.anthropic.apiKey(),
      'anthropic-version': '2023-06-01',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model: config.anthropic.model,
      max_tokens: maxTokens,
      system,
      messages,
    }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(`Claude API failed (${res.status}): ${JSON.stringify(body)}`);
  }
  return (body.content || [])
    .filter((block) => block.type === 'text')
    .map((block) => block.text)
    .join('\n')
    .trim();
}

/**
 * Convert Conversation Log rows into Claude message turns. Consecutive
 * same-role rows are merged (the API requires alternating roles). Both
 * agent and human outbound messages count as "assistant" — from the
 * member's point of view they are all Olivia/MDS on the same thread.
 */
export function logRowsToMessages(rows) {
  const turns = [];
  for (const row of rows) {
    const text = (row.fields.Message || '').trim();
    if (!text) continue;
    const role = row.fields.Direction === 'inbound' ? 'user' : 'assistant';
    const last = turns[turns.length - 1];
    if (last && last.role === role) {
      last.content += `\n${text}`;
    } else {
      turns.push({ role, content: text });
    }
  }
  // Claude requires the first message to be from the user.
  while (turns.length && turns[0].role !== 'user') turns.shift();
  return turns;
}
