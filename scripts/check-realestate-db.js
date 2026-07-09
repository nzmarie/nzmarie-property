/**
 * Check real_estate and real_estate_rent table status
 * Usage: node scripts/check-realestate-db.js
 */
require('dotenv').config();
const { Client } = require('pg');

async function run() {
  const client = new Client({ connectionString: process.env.DATABASE_URL, ssl: { rejectUnauthorized: false } });
  await client.connect();

  try {
    for (const table of ['real_estate', 'real_estate_rent']) {
      console.log(`\n${'='.repeat(60)}`);
      console.log(`Table: ${table}`);
      console.log('='.repeat(60));

      // Total count
      const count = await client.query(`SELECT COUNT(*) as total FROM ${table}`);
      const total = parseInt(count.rows[0].total);
      console.log(`\nTotal records: ${total}`);

      if (total === 0) { console.log('(empty)'); continue; }

      // Column completeness
      const sample = await client.query(`SELECT * FROM ${table} LIMIT 1`);
      const columns = Object.keys(sample.rows[0]);
      console.log(`\nColumns (${columns.length}): ${columns.join(', ')}`);

      // Field fill rates for key columns
      const fields = ['address','price_display','bedroom_count','bathroom_count',
                      'floor_area','land_area','property_type','cover_image_url',
                      'images','description','listing_number','listing_date_raw',
                      'agent_name','latitude','longitude'];

      const existing = columns.filter(c => fields.includes(c));
      const missing  = fields.filter(f => !columns.includes(f));

      console.log('\nField completeness:');
      for (const f of existing) {
        const r = await client.query(`SELECT COUNT(${f}) as n FROM ${table}`);
        const n = parseInt(r.rows[0].n);
        const pct = (n / total * 100).toFixed(1);
        const bar = n === 0 ? '❌' : n === total ? '✅' : '⚠️ ';
        console.log(`  ${bar} ${f.padEnd(22)} ${n}/${total} (${pct}%)`);
      }

      if (missing.length > 0) {
        console.log(`\n  ⛔ Missing columns: ${missing.join(', ')}`);
      }

      // Sample row
      const sampleCols = ['address','price_display','bedroom_count','listing_date_raw'].filter(c => columns.includes(c)).join(', ');
      const row = await client.query(`SELECT ${sampleCols} FROM ${table} LIMIT 1`);
      console.log('\nSample row:');
      console.log('  address      :', row.rows[0].address);
      console.log('  price        :', row.rows[0].price_display);
      console.log('  beds         :', row.rows[0].bedroom_count);
      console.log('  listed       :', row.rows[0].listing_date_raw);
      console.log('  description  :', row.rows[0].description ? row.rows[0].description.substring(0,80)+'...' : 'NULL');
    }
    console.log('');
  } finally {
    await client.end();
  }
}

run().catch(e => { console.error('❌', e.message); process.exit(1); });
