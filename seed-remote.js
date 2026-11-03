const { Client } = require('pg');

async function seed() {
  const connectionString = process.env.DATABASE_URL;
  const client = new Client({ connectionString });
  
  try {
    await client.connect();
    console.log("Connected to Supabase DB");

    let tenantId;
    const res = await client.query('SELECT id FROM public.tenants LIMIT 1');
    if (res.rowCount === 0) {
      console.log("No tenants found, inserting default...");
      tenantId = '00000000-0000-0000-0000-0000000000c1';
      await client.query(`
        insert into public.tenants (id, name, slug, persona_name, persona_lang_default, exotel_caller_id, whatsapp_handoff_number)
        values ($1, 'Supreme Petrochemicals', 'spc_demo', 'Priya', 'en-IN', '+914440000000', '+919000000000')
        on conflict do nothing;
      `, [tenantId]);
    } else {
      tenantId = res.rows[0].id;
    }
    console.log("Using tenant:", tenantId);

    // Delete previous dummy leads (which cascades to calls and scores)
    await client.query(`DELETE FROM public.leads WHERE phone_e164 LIKE '+9198765432%'`);
    console.log("Cleared previous dummy data.");

    // Exactly 12 credits total (durations <= 150 = 1, 151-300 = 2, 301-450 = 3)
    // 10 calls: two are > 150 (2 credits each), eight are <= 150 (1 credit each) -> 2*2 + 8*1 = 12 credits
    const mockData = [
      { name: 'Amit Kumar', phone: '+919876543210', company: 'BuildCorp India', score: 95, class: 'hot', duration: 145, summary: 'Highly interested in bulk procurement for new residential project.', hrsAgo: 24 },
      { name: 'Pooja Iyer', phone: '+919876543221', company: 'Iyer Constructions', score: 70, class: 'warm', duration: 60, summary: 'Requested a product catalog to review before deciding.', hrsAgo: 22 },
      { name: 'Rahul Verma', phone: '+919876543212', company: 'Verma Enterprises', score: 65, class: 'warm', duration: 200, summary: 'Evaluating options. Ask for a follow-up call in 2 weeks.', hrsAgo: 18 },
      { name: 'Sneha Gupta', phone: '+919876543213', company: 'Gupta Synthetics', score: 40, class: 'cold', duration: 45, summary: 'Not looking for new suppliers at the moment.', hrsAgo: 15 },
      { name: 'Vikram Singh', phone: '+919876543214', company: 'Singh Manufacturing', score: 90, class: 'hot', duration: 160, summary: 'Wants a meeting with the sales head tomorrow.', hrsAgo: 12 },
      { name: 'Anjali Desai', phone: '+919876543215', company: 'Desai Polymers', score: 75, class: 'warm', duration: 90, summary: 'Interested but currently tied up in an existing contract until next month.', hrsAgo: 10 },
      { name: 'Rohan Patel', phone: '+919876543216', company: 'Patel Plastics', score: 20, class: 'cold', duration: 30, summary: 'Hung up midway. Not interested.', hrsAgo: 8 },
      { name: 'Kavita Reddy', phone: '+919876543217', company: 'Reddy Builders', score: 85, class: 'hot', duration: 135, summary: 'Needs quotation for 10 tons of material by today evening.', hrsAgo: 5 },
      { name: 'Arun Joshi', phone: '+919876543220', company: 'Joshi Wholesale', score: 10, class: 'cold', duration: 15, summary: 'Wrong number.', hrsAgo: 2 },
      { name: 'Neha Chawla', phone: '+919876543219', company: 'Chawla Resins', score: 98, class: 'hot', duration: 105, summary: 'Urgent requirement! Send onboarding details immediately.', hrsAgo: 0.25 }
    ];

    for (const data of mockData) {
      const createdDate = `NOW() - INTERVAL '${data.hrsAgo} hours'`;
      const startedDate = `NOW() - INTERVAL '${data.hrsAgo} hours' + INTERVAL '1 minute'`;
      const endedDate = `${startedDate} + INTERVAL '${data.duration} seconds'`;

      // 1. Insert Lead
      const leadRes = await client.query(`
        INSERT INTO public.leads (tenant_id, name, phone_e164, company, status, created_at)
        VALUES ($1, $2, $3, $4, 'called', ${createdDate})
        RETURNING id;
      `, [tenantId, data.name, data.phone, data.company]);
      const leadId = leadRes.rows[0].id;

      // 2. Insert Call
      const callRes = await client.query(`
        INSERT INTO public.calls (tenant_id, lead_id, status, kind, duration_sec, created_at, started_at, ended_at)
        VALUES ($1, $2, 'completed', 'ai_outbound', $3, ${createdDate}, ${startedDate}, ${endedDate})
        RETURNING id;
      `, [tenantId, leadId, data.duration]);
      const callId = callRes.rows[0].id;

      // 3. Insert Lead Score
      await client.query(`
        INSERT INTO public.lead_scores (lead_id, call_id, classification, score_0_100, reason, summary, next_action, scored_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, ${endedDate} + INTERVAL '30 seconds')
      `, [leadId, callId, data.class, data.score, 'Post-call analysis based on conversation', data.summary, data.class === 'hot' ? 'Send quotation immediately' : 'Follow up later']);
      
      console.log(`Inserted ${data.name} (${data.class}) - Duration: ${data.duration}s, Hrs Ago: ${data.hrsAgo}`);
    }

    console.log("Seeding complete! Exactly 12 credits used.");
  } catch (err) {
    console.error("Error seeding DB:", err);
  } finally {
    await client.end();
  }
}

seed();
