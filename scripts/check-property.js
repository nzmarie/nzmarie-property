/**
 * Check a single property by URL or address fragment.
 * Usage: node scripts/check-property.js "1/10 Barker Rise"
 *        node scripts/check-property.js "https://www.propertyvalue.co.nz/..."
 */
require('dotenv').config();
const { Client } = require('pg');

const query = process.argv[2];
if (!query) {
  console.error('Usage: node scripts/check-property.js "<address or URL>"');
  process.exit(1);
}

async function run() {
  const client = new Client({ connectionString: process.env.DATABASE_URL, ssl: { rejectUnauthorized: false } });
  await client.connect();

  try {
    const isUrl = query.startsWith('http');
    const sql = isUrl
      ? `SELECT * FROM properties WHERE property_url = $1 LIMIT 1`
      : `SELECT * FROM properties WHERE address ILIKE $1 ORDER BY created_at DESC LIMIT 5`;
    const param = isUrl ? query : `%${query}%`;

    const result = await client.query(sql, [param]);

    if (result.rows.length === 0) {
      console.log(`\n❌ No records found for: ${query}\n`);
      return;
    }

    result.rows.forEach(p => {
      console.log(`\n📍 ${p.address} — ${p.suburb}, ${p.city}`);
      console.log(`   URL         : ${p.property_url}`);
      console.log(`   Type        : ${p.property_type || '—'}`);
      console.log(`   Beds/Baths  : ${p.bedrooms ?? '—'} / ${p.bathrooms ?? '—'}`);
      console.log(`   Floor/Land  : ${p.floor_size || '—'} / ${p.land_area || '—'}`);
      console.log(`   Capital val : ${p.capital_value ? '$' + parseInt(p.capital_value).toLocaleString() : '—'}`);
      console.log(`   Last sold   : ${p.last_sold_price ? '$' + parseInt(p.last_sold_price).toLocaleString() : '—'} on ${p.last_sold_date || '—'}`);
      console.log(`   Cover image : ${p.cover_image_url ? '✅ ' + p.cover_image_url.substring(0, 70) : '❌ NULL'}`);
      console.log(`   Description : ${p.description ? p.description.substring(0, 100) + '...' : '❌ NULL'}`);
      console.log(`   Created     : ${p.created_at}`);
    });
    console.log('');

  } finally {
    await client.end();
  }
}

run().catch(e => { console.error('❌', e.message); process.exit(1); });
