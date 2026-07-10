import { generateWelcomeDrafts } from '../src/workflows/welcomeDrafts.js';

/**
 * Workflow B runner: draft welcome messages for every Assistant Pilot member
 * into Airtable for Eugene/Kat review. Pass --dry-run to print without writing.
 *
 *   npm run drafts:welcome [-- --dry-run]
 */
const dryRun = process.argv.includes('--dry-run');

generateWelcomeDrafts({ dryRun })
  .then((results) => {
    for (const r of results) {
      if (r.ok && dryRun) console.log(`\n--- ${r.member} ---\n${r.draft}\n`);
    }
    const failed = results.filter((r) => !r.ok);
    console.log(`\n${results.length - failed.length}/${results.length} drafts generated${dryRun ? ' (dry run)' : ''}`);
    process.exit(failed.length ? 1 : 0);
  })
  .catch((err) => {
    console.error(err);
    process.exit(1);
  });
