/**
 * Show how many properties are still pending backfill (missing key fields).
 * Usage: node scripts/check-backfill-pending.js [suburb]
 * Example: node scripts/check-backfill-pending.js
 *          node scripts/check-backfill-pending.js Northcross
 */
require('dotenv').config();
const { Client } = require('pg');

const suburb = process.argv[2] || null;

async function run() {
  const client = new Client({ connectionString: process.env.DATABASE_URL, ssl: { rejectUnauthorized: false } });
  await client.connect();

  try {
    const whereSuburb = suburb ? `AND suburb = '${suburb}'` : '';

    // Pending breakdown by suburb
    const pending = await client.query(`
      SELECT
        suburb,
        COUNT(*) as total,
        COUNT(*) FILTER (WHERE bedrooms      IS NULL) as no_beds,
        COUNT(*) FILTER (WHERE cover_image_url IS NULL) as no_image,
        COUNT(*) FILTER (WHERE description   IS NULL) as no_desc,
        COUNT(*) FILTER (WHERE capital_value IS NULL) as no_rv
      FROM properties
      WHERE (bedrooms IS NULL OR cover_image_url IS NULL OR description IS NULL)
        AND region = 'auckland'
        ${whereSuburb}
      GROUP BY suburb
      ORDER BY total DESC
    `);

    if (pending.rows.length === 0) {
      console.log('\n✅ All properties have complete data!\n');
      return;
    }

    const grandTotal = pending.rows.reduce((s, r) => s + parseInt(r.total), 0);
    console.log(`\n⏳ ${grandTotal} properties pending backfill${suburb ? ' in ' + suburb : ''}:\n`);
    console.log('  Suburb'.padEnd(35) + 'Total  NoBeds  NoImage  NoDesc  NoRV');
    console.log('  ' + '-'.repeat(70));

    pending.rows.forEach(r => {
      const name = r.suburb.padEnd(33);
      console.log(`  ${name}${String(r.total).padEnd(7)}${String(r.no_beds).padEnd(8)}${String(r.no_image).padEnd(9)}${String(r.no_desc).padEnd(8)}${r.no_rv}`);
    });
    console.log('');

    // Show first 5 pending records as sample
    const sample = await client.query(`
      SELECT address, suburb, property_url
      FROM properties
      WHERE (bedrooms IS NULL OR cover_image_url IS NULL OR description IS NULL)
        AND region = 'auckland'
        ${whereSuburb}
      ORDER BY created_at ASC
      LIMIT 5
    `);

    console.log('  Sample records to process:');
    sample.rows.forEach(r => console.log(`  • ${r.address} (${r.suburb})`));
    console.log('');

  } finally {
    await client.end();
  }
}

run().catch(e => { console.error('❌', e.message); process.exit(1); });
