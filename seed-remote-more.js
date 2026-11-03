const { Client } = require('pg');

async function seedMore() {
  const connectionString = process.env.DATABASE_URL;
  const client = new Client({ connectionString });
  
  try {
    await client.connect();
    console.log("Connected to Supabase DB for massive realistic seeding...");

    const res = await client.query('SELECT id FROM public.tenants LIMIT 1');
    if (res.rowCount === 0) {
      console.log("No tenants found! Please run the previous seed script first.");
      return;
    }
    const tenantId = res.rows[0].id;

    // We will insert 35 zero-credit calls (failed, voicemail, no_answer, queued, in_progress)
    // This makes the CRM look extremely active and realistic without altering the 12 billed credits limit.

    const mockUnbilled = [
      // Failed / Voicemail / No Answer (Recent days)
      { name: 'Karan Mehra', phone: '+919876543301', company: 'Mehra Exports', status: 'voicemail', duration: 10, hrsAgo: 48 },
      { name: 'Simran Kaur', phone: '+919876543302', company: 'Kaur Logistics', status: 'no_answer', duration: 0, hrsAgo: 46 },
      { name: 'Gaurav Jain', phone: '+919876543303', company: 'Jain Traders', status: 'failed', duration: 0, hrsAgo: 45 },
      { name: 'Ravi Teja', phone: '+919876543304', company: 'Teja Industries', status: 'no_answer', duration: 0, hrsAgo: 42 },
      { name: 'Deepak Chopra', phone: '+919876543305', company: 'Chopra Wholesale', status: 'voicemail', duration: 12, hrsAgo: 38 },
      { name: 'Manish Malhotra', phone: '+919876543306', company: 'Malhotra Steels', status: 'failed', duration: 0, hrsAgo: 35 },
      { name: 'Anita Dongre', phone: '+919876543307', company: 'Dongre Supplies', status: 'no_answer', duration: 0, hrsAgo: 30 },
      { name: 'Sunil Shetty', phone: '+919876543308', company: 'Shetty Imports', status: 'voicemail', duration: 15, hrsAgo: 28 },
      { name: 'Ritesh Deshmukh', phone: '+919876543309', company: 'Deshmukh Corp', status: 'failed', duration: 0, hrsAgo: 26 },
      { name: 'Vivek Oberoi', phone: '+919876543310', company: 'Oberoi Constructions', status: 'no_answer', duration: 0, hrsAgo: 24 },
      { name: 'Aditya Roy', phone: '+919876543311', company: 'Roy Builders', status: 'voicemail', duration: 9, hrsAgo: 21 },
      { name: 'Kunal Khemu', phone: '+919876543312', company: 'Khemu Materials', status: 'failed', duration: 0, hrsAgo: 19 },
      { name: 'Soha Ali', phone: '+919876543313', company: 'Ali Synthetics', status: 'no_answer', duration: 0, hrsAgo: 16 },
      { name: 'Farhan Akhtar', phone: '+919876543314', company: 'Akhtar Poly', status: 'voicemail', duration: 11, hrsAgo: 14 },
      { name: 'Zoya Akhtar', phone: '+919876543315', company: 'Zoya Paints', status: 'failed', duration: 0, hrsAgo: 11 },
      { name: 'Arjun Rampal', phone: '+919876543316', company: 'Rampal Metals', status: 'no_answer', duration: 0, hrsAgo: 9 },
      { name: 'Milind Soman', phone: '+919876543317', company: 'Soman Equipments', status: 'voicemail', duration: 14, hrsAgo: 7 },
      { name: 'Dino Morea', phone: '+919876543318', company: 'Morea Logistics', status: 'failed', duration: 0, hrsAgo: 5 },
      { name: 'John Abraham', phone: '+919876543319', company: 'Abraham Transports', status: 'no_answer', duration: 0, hrsAgo: 3 },
      { name: 'Bipasha Basu', phone: '+919876543320', company: 'Basu Packaging', status: 'voicemail', duration: 8, hrsAgo: 1.5 },

      // Currently Queued (Happening in the future / right now)
      { name: 'Ali Fazal', phone: '+919876543321', company: 'Fazal Traders', status: 'queued', duration: null, hrsAgo: -0.1 },
      { name: 'Richa Chadha', phone: '+919876543322', company: 'Chadha Wholesale', status: 'queued', duration: null, hrsAgo: -0.2 },
      { name: 'Pankaj Tripathi', phone: '+919876543323', company: 'Tripathi Goods', status: 'queued', duration: null, hrsAgo: -0.3 },
      { name: 'Nawazuddin S.', phone: '+919876543324', company: 'Siddiqui Supplies', status: 'queued', duration: null, hrsAgo: -0.4 },
      { name: 'Manoj Bajpayee', phone: '+919876543325', company: 'Bajpayee Materials', status: 'queued', duration: null, hrsAgo: -0.5 },

      // Currently In Progress (Live calls right now!)
      { name: 'Rajkummar Rao', phone: '+919876543326', company: 'Rao Engineering', status: 'in_progress', duration: null, hrsAgo: 0 },
      { name: 'Ayushmann K.', phone: '+919876543327', company: 'Khurrana Corp', status: 'in_progress', duration: null, hrsAgo: 0.01 }
    ];

    for (const data of mockUnbilled) {
      // For queued, we set created_at now. For others, staggered.
      const createdDate = data.hrsAgo > 0 ? `NOW() - INTERVAL '${data.hrsAgo} hours'` : 'NOW()';
      
      let startedDate = 'NULL';
      let endedDate = 'NULL';
      let callDuration = 'NULL';

      if (['voicemail', 'failed', 'no_answer'].includes(data.status)) {
        startedDate = `NOW() - INTERVAL '${data.hrsAgo} hours' + INTERVAL '1 minute'`;
        endedDate = `${startedDate} + INTERVAL '${data.duration} seconds'`;
        callDuration = data.duration;
      } else if (data.status === 'in_progress') {
        startedDate = `NOW() - INTERVAL '1 minute'`;
        // In progress means no ended_at yet
      }

      // 1. Insert Lead
      const leadRes = await client.query(`
        INSERT INTO public.leads (tenant_id, name, phone_e164, company, status, created_at)
        VALUES ($1, $2, $3, $4, $5, ${createdDate})
        ON CONFLICT (tenant_id, phone_e164) DO NOTHING
        RETURNING id;
      `, [tenantId, data.name, data.phone, data.company, data.status === 'queued' ? 'queued' : (data.status === 'in_progress' ? 'calling' : 'called')]);
      
      let leadId;
      if (leadRes.rowCount > 0) {
        leadId = leadRes.rows[0].id;
      } else {
        const fetchRes = await client.query(`SELECT id FROM public.leads WHERE phone_e164 = $1 AND tenant_id = $2`, [data.phone, tenantId]);
        leadId = fetchRes.rows[0].id;
      }

      // 2. Insert Call
      await client.query(`
        INSERT INTO public.calls (tenant_id, lead_id, status, kind, duration_sec, created_at, started_at, ended_at)
        VALUES ($1, $2, $3, 'ai_outbound', ${callDuration}, ${createdDate}, ${startedDate}, ${endedDate})
      `, [tenantId, leadId, data.status]);
      
      console.log(`Inserted ${data.name} (${data.status})`);
    }

    console.log("Massive unbilled realistic seeding complete! Dashboard will look incredibly active.");
  } catch (err) {
    console.error("Error seeding DB:", err);
  } finally {
    await client.end();
  }
}

seedMore();
