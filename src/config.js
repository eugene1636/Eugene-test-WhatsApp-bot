const required = (name) => {
  const value = process.env[name];
  if (!value) throw new Error(`Missing required environment variable: ${name}`);
  return value;
};

export const config = {
  port: Number(process.env.PORT || 3000),

  whatsapp: {
    accessToken: () => required('WHATSAPP_ACCESS_TOKEN'),
    phoneNumberId: () => required('WHATSAPP_PHONE_NUMBER_ID'),
    verifyToken: process.env.WHATSAPP_VERIFY_TOKEN || 'change-me',
    appSecret: process.env.WHATSAPP_APP_SECRET || '',
    apiVersion: process.env.WHATSAPP_API_VERSION || 'v20.0',
  },

  anthropic: {
    apiKey: () => required('ANTHROPIC_API_KEY'),
    model: process.env.ANTHROPIC_MODEL || 'claude-sonnet-4-6',
  },

  airtable: {
    apiKey: () => required('AIRTABLE_API_KEY'),
    baseId: () => required('AIRTABLE_BASE_ID'),
    membersTable: process.env.AIRTABLE_MEMBERS_TABLE || 'Members',
    conversationLogTable:
      process.env.AIRTABLE_CONVERSATION_LOG_TABLE || 'Conversation Log',
    pilotPicksTable: process.env.AIRTABLE_PILOT_PICKS_TABLE || 'Pilot Picks',
  },

  behaviour: {
    debounceMs: Number(process.env.DEBOUNCE_SECONDS || 20) * 1000,
    humanPauseMs: Number(process.env.HUMAN_PAUSE_HOURS || 4) * 60 * 60 * 1000,
    logContextRows: Number(process.env.LOG_CONTEXT_ROWS || 30),
    digestTemplateName: process.env.DIGEST_TEMPLATE_NAME || 'olivia_weekly_digest',
    digestTemplateLanguage: process.env.DIGEST_TEMPLATE_LANGUAGE || 'en',
  },
};
