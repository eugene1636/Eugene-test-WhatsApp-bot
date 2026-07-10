import { sendWeeklyDigests } from '../src/workflows/weeklyDigest.js';

/**
 * Workflow C runner: send the weekly digest to pilot members with queued
 * picks, skipping opt-outs and members with nothing relevant. Schedule via
 * cron (digest day/time is an open decision — spec section 9).
 *
 *   npm run digest:weekly [-- --dry-run] [-- --as-text]
 *
 * --dry-run  print what would be sent, send nothing
 * --as-text  send as a free-form session message instead of the approved
 *            Meta template (only works inside an open 24h session; testing)
 */
const dryRun = process.argv.includes('--dry-run');
const asText = process.argv.includes('--as-text');

sendWeeklyDigests({ dryRun, asText })
  .then((results) => {
    for (const r of results) {
      if (r.wouldSend) console.log(`\n--- would send to ${r.member} ---\n${r.wouldSend}\n`);
      else if (r.skipped) console.log(`skip ${r.member}: ${r.skipped}`);
      else if (r.error) console.log(`FAIL ${r.member}: ${r.error}`);
    }
    const sent = results.filter((r) => r.sent).length;
    console.log(`\n${sent} digest(s) sent, ${results.filter((r) => r.skipped).length} skipped`);
    process.exit(results.some((r) => r.error) ? 1 : 0);
  })
  .catch((err) => {
    console.error(err);
    process.exit(1);
  });
