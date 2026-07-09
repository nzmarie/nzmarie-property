/**
 * Check data completeness for a given suburb in the properties table.
 * Usage: node scripts/check-suburb.js [suburb]
 * Example: node scripts/check-suburb.js Northcross
 *          node scripts/check-suburb.js "Browns Bay"
 */
require('dotenv').config();
const { Client } = require('pg');

const suburb = process.argv[2] || 'Northcross';

async function run() {
  const client = new Client({ connectionString: process.env.DATABASE_URL, ssl: { rejectUnauthorized: false } });
  await client.connect();

  try {
    // Count + completeness
    const stats = await client.query(`
      SELECT
        COUNT(*) as total,
        COUNT(bedrooms)        as has_bedrooms,
        COUNT(bathrooms)       as has_bathrooms,
        COUNT(cover_image_url) as has_image,
        COUNT(capital_value)   as has_rv,
        COUNT(last_sold_price) as has_sold_price,
        COUNT(description)     as has_description
      FROM properties WHERE suburb = $1
    `, [suburb]);

    const s = stats.rows[0];
    const total = parseInt(s.total);

    if (total === 0) {
      console.log(`No records found for suburb: ${suburb}`);
      return;
    }

    const pct = n => `${parseInt(n)}/${total} (${(parseInt(n)/total*100).toFixed(1)}%)`;

    console.log(`\n📊 ${suburb} — ${total} properties\n`);
    console.log(`   Cover image : ${pct(s.has_image)}`);
    console.log(`   Bedrooms    : ${pct(s.has_bedrooms)}`);
    console.log(`   Bathrooms   : ${pct(s.has_bathrooms)}`);
    console.log(`   Capital value (RV): ${pct(s.has_rv)}`);
    console.log(`   Last sold price   : ${pct(s.has_sold_price)}`);
    console.log(`   Description : ${pct(s.has_description)}`);

    // Duplicate check
    const dups = await client.query(`
      SELECT address, COUNT(*) as count
      FROM properties WHERE suburb = $1
      GROUP BY address HAVING COUNT(*) > 1
      ORDER BY count DESC LIMIT 5
    `, [suburb]);

    if (dups.rows.length > 0) {
      console.log(`\n⚠️  Duplicate addresses:`);
      dups.rows.forEach(r => console.log(`   "${r.address}" × ${r.count}`));
    } else {
      console.log(`\n✅ No duplicate addresses`);
    }

    // Sample (last 5 created)
    const sample = await client.query(`
      SELECT address, bedrooms, cover_image_url, created_at
      FROM properties WHERE suburb = $1
      ORDER BY created_at DESC LIMIT 5
    `, [suburb]);

    console.log(`\n📋 Latest 5 records:`);
    sample.rows.forEach(r => {
      const img = r.cover_image_url ? '✅' : '❌';
      const bed = r.bedrooms != null ? r.bedrooms : '—';
      console.log(`   ${img} img | beds: ${bed} | ${r.address}`);
    });
    console.log('');

  } finally {
    await client.end();
  }
}

run().catch(e => { console.error('❌', e.message); process.exit(1); });
