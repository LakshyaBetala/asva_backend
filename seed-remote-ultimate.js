const { Client } = require('pg');

const firstNames = ["Amit", "Rahul", "Pooja", "Neha", "Vikram", "Sneha", "Anjali", "Rohan", "Sanjay", "Kavita", "Arun", "Raj", "Sunil", "Manish", "Deepak", "Simran", "Anita", "Karan", "Vivek", "Ritesh", "Nitin", "Prakash", "Gaurav", "Suresh", "Ramesh", "Mukesh", "Naveen", "Tarun", "Vishal", "Ashish"];
const lastNames = ["Kumar", "Sharma", "Verma", "Gupta", "Singh", "Desai", "Patel", "Reddy", "Dutt", "Chawla", "Joshi", "Iyer", "Mehra", "Kaur", "Jain", "Teja", "Chopra", "Malhotra", "Dongre", "Shetty", "Deshmukh", "Oberoi", "Roy", "Khemu", "Ali", "Akhtar", "Rampal", "Soman", "Morea", "Abraham"];
const companyWords = ["Traders", "Exports", "Logistics", "Industries", "Wholesale", "Steels", "Supplies", "Imports", "Corp", "Constructions", "Builders", "Materials", "Synthetics", "Poly", "Paints", "Metals", "Equipments", "Transports", "Packaging", "Plastics", "Polymers", "Chemicals", "Petrochem", "Manufacturing", "Enterprises", "Agencies", "Distributors", "Global", "India", "Ventures"];

const products = ["LLDPE", "HDPE", "PP", "PVC", "PET", "Polystyrene"];
const buyingFreqs = ['one_off', 'monthly', 'ad_hoc', 'unknown'];
const decisionRoles = ['owner', 'procurement', 'engineer', 'assistant', 'unknown'];

const outcomes = [
  { class: 'hot', summary: 'Highly interested in bulk procurement. Wants pricing for 50 MT immediately.', reason: 'Lead explicitly asked for pricing and availability.', score: 95, volume: 50000, freq: 'monthly', role: 'owner' },
  { class: 'hot', summary: 'Ready to order next week. Needs sample first.', reason: 'Confirmed requirement timeline is very short.', score: 88, volume: 10000, freq: 'one_off', role: 'procurement' },
  { class: 'hot', summary: 'Looking to switch suppliers. Requested a meeting with our sales head.', reason: 'Expressed dissatisfaction with current supplier pricing.', score: 92, volume: 100000, freq: 'monthly', role: 'owner' },
  { class: 'warm', summary: 'Evaluating options for next quarter. Call back in 2 weeks.', reason: 'Has demand but timeline is not immediate.', score: 65, volume: 5000, freq: 'ad_hoc', role: 'procurement' },
  { class: 'warm', summary: 'Prices seemed high, but asked us to send a catalog.', reason: 'Price sensitive but willing to engage.', score: 55, volume: 2000, freq: 'ad_hoc', role: 'assistant' },
  { class: 'warm', summary: 'Currently tied up in an annual contract. Will review in December.', reason: 'Contractually blocked but interested.', score: 70, volume: 25000, freq: 'monthly', role: 'procurement' },
  { class: 'cold', summary: 'Not looking for new suppliers at the moment.', reason: 'Satisfied with current vendor.', score: 30, volume: null, freq: 'unknown', role: 'unknown' },
  { class: 'cold', summary: 'Hung up midway. Not interested.', reason: 'Lead was abrupt and disconnected.', score: 10, volume: null, freq: 'unknown', role: 'unknown' },
  { class: 'cold', summary: 'They only deal in specialized medical grade polymers, not our catalog.', reason: 'Product mismatch.', score: 20, volume: null, freq: 'unknown', role: 'engineer' },
];

function getRandom(arr) { return arr[Math.floor(Math.random() * arr.length)]; }

function generateLead() {
  const name = `${getRandom(firstNames)} ${getRandom(lastNames)}`;
  const company = `${getRandom(lastNames)} ${getRandom(companyWords)}`;
  const phone = `+91${Math.floor(6000000000 + Math.random() * 3999999999)}`;
  return { name, company, phone };
}

const hotTranscriptTemplate = [
  { speaker: 'agent', text: 'Hello, am I speaking with {name} from {company}?' },
  { speaker: 'lead', text: 'Yes, speaking. Who is this?' },
  { speaker: 'agent', text: 'Hi {name}, I am calling from Supreme Petrochemicals. We are currently offering highly competitive rates on premium {product} granules for bulk brokers. Are you looking to procure any material this month?' },
  { speaker: 'lead', text: 'Actually yes, we do have a requirement coming up for about 40 tons of {product}. What is your current ex-factory price?' },
  { speaker: 'agent', text: 'That is great to hear. For 40 tons, we can offer a very special broker rate. However, prices fluctuate daily. Would you like me to have our regional sales manager send you today\'s price sheet on WhatsApp?' },
  { speaker: 'lead', text: 'Sure, you can send it to this number. Also include the technical data sheet.' },
  { speaker: 'agent', text: 'Perfect, I will have that sent over immediately. Is there any other material you regularly procure?' },
  { speaker: 'lead', text: 'Mostly {product} and sometimes PVC. Send prices for both.' },
  { speaker: 'agent', text: 'Understood. Thank you for your time, {name}. Have a great day!' }
];

async function seedUltimate() {
  const connectionString = process.env.DATABASE_URL;
  const client = new Client({ connectionString });
  
  try {
    await client.connect();
    console.log("Connected to Supabase DB for ULTIMATE REALTIME ALL-TABLE seeding...");

    const res = await client.query('SELECT id FROM public.tenants LIMIT 1');
    if (res.rowCount === 0) {
      console.log("No tenants found! Please run the previous seed script first.");
      return;
    }
    const tenantId = res.rows[0].id;

    // Fetch existing user for 'created_by' / 'assigned_to'
    let adminUserId = null;
    const userRes = await client.query('SELECT id FROM public.users WHERE tenant_id = $1 LIMIT 1', [tenantId]);
    if (userRes.rowCount > 0) adminUserId = userRes.rows[0].id;

    console.log("Wiping previous dummy leads to start fresh...");
    await client.query(`DELETE FROM public.leads WHERE phone_e164 LIKE '+91%' AND tenant_id = $1`, [tenantId]);
    await client.query(`DELETE FROM public.campaigns WHERE name LIKE 'Demo Campaign%' AND tenant_id = $1`, [tenantId]);

    // 1. Create a Campaign
    const campRes = await client.query(`
      INSERT INTO public.campaigns (tenant_id, name, script_version, created_by, started_at, created_at)
      VALUES ($1, 'Demo Campaign Q4 Outbound', 1, $2, NOW() - INTERVAL '14 days', NOW() - INTERVAL '14 days')
      RETURNING id;
    `, [tenantId, adminUserId]);
    const campaignId = campRes.rows[0].id;

    let totalCredits = 0;
    
    // Generate 120 leads for massive scale
    for (let i = 0; i < 120; i++) {
      const lead = generateLead();
      let status, duration, callStatus;
      
      const rand = Math.random();
      if (rand < 0.35) { callStatus = 'completed'; status = 'called'; }
      else if (rand < 0.65) { callStatus = 'no_answer'; status = 'called'; duration = 0; }
      else if (rand < 0.80) { callStatus = 'voicemail'; status = 'called'; duration = Math.floor(Math.random() * 20) + 5; }
      else if (rand < 0.90) { callStatus = 'failed'; status = 'called'; duration = 0; }
      else { callStatus = 'queued'; status = 'queued'; duration = null; }

      let scoreObj = null;
      if (callStatus === 'completed') {
        const scoreRand = Math.random();
        if (scoreRand < 0.25) { scoreObj = outcomes[Math.floor(Math.random() * 3)]; duration = Math.floor(Math.random() * (420 - 150 + 1) + 150); }
        else if (scoreRand < 0.6) { scoreObj = outcomes[3 + Math.floor(Math.random() * 3)]; duration = Math.floor(Math.random() * (200 - 90 + 1) + 90); }
        else { scoreObj = outcomes[6 + Math.floor(Math.random() * 3)]; duration = Math.floor(Math.random() * (90 - 15 + 1) + 15); }
      }

      const hrsAgo = (Math.pow(Math.random(), 2) * 336);
      const createdDate = `NOW() - INTERVAL '${hrsAgo} hours'`;
      const startedDate = callStatus === 'queued' ? 'NULL' : `NOW() - INTERVAL '${hrsAgo} hours' + INTERVAL '1 minute'`;
      const endedDate = callStatus === 'queued' ? 'NULL' : `${startedDate} + INTERVAL '${duration} seconds'`;

      // Insert Lead
      const leadRes = await client.query(`
        INSERT INTO public.leads (tenant_id, name, phone_e164, company, status, created_at, assigned_to)
        VALUES ($1, $2, $3, $4, $5, ${createdDate}, $6)
        RETURNING id;
      `, [tenantId, lead.name, lead.phone, lead.company, status, scoreObj?.class === 'hot' ? adminUserId : null]);
      const leadId = leadRes.rows[0].id;

      // Insert Lead Intro Audio
      await client.query(`
        INSERT INTO public.lead_intro_audio (tenant_id, lead_id, lang, r2_key, text_hash, synthesized_at)
        VALUES ($1, $2, 'en-IN', 'intros/${leadId}.mp3', 'hash123', ${createdDate})
      `, [tenantId, leadId]);

      // Add to DNC list if failed or cold hangup randomly
      if (callStatus === 'failed' || (scoreObj && scoreObj.class === 'cold' && Math.random() > 0.5)) {
        await client.query(`
          INSERT INTO public.dnc_list (tenant_id, phone_e164, reason, added_at)
          VALUES ($1, $2, $3, ${endedDate} + INTERVAL '1 hour')
          ON CONFLICT DO NOTHING
        `, [tenantId, lead.phone, callStatus === 'failed' ? 'Invalid Number' : 'Requested DNC']);
      }

      // Insert Call
      if (callStatus !== 'queued') {
        const callRes = await client.query(`
          INSERT INTO public.calls (tenant_id, lead_id, campaign_id, samvaad_call_id, status, kind, duration_sec, created_at, started_at, ended_at, language_used)
          VALUES ($1, $2, $3, $4, $5, 'ai_outbound', $6, ${createdDate}, ${startedDate}, ${endedDate}, 'en-IN')
          RETURNING id, billed_units;
        `, [tenantId, leadId, campaignId, `call_ext_${Math.random().toString(36).substring(7)}`, callStatus, duration]);
        const callId = callRes.rows[0].id;
        
        if (callRes.rows[0].billed_units) totalCredits += callRes.rows[0].billed_units;

        // Insert Call Events
        await client.query(`INSERT INTO public.call_events (call_id, event_id, kind, payload, occurred_at) VALUES ($1, $2, 'call.initiated', '{}', ${startedDate})`, [callId, 'evt_init_'+callId]);
        if (callStatus === 'completed' || callStatus === 'voicemail' || callStatus === 'no_answer') {
          await client.query(`INSERT INTO public.call_events (call_id, event_id, kind, payload, occurred_at) VALUES ($1, $2, 'call.ringing', '{}', ${startedDate} + INTERVAL '2 seconds')`, [callId, 'evt_ring_'+callId]);
        }
        if (callStatus === 'completed') {
          await client.query(`INSERT INTO public.call_events (call_id, event_id, kind, payload, occurred_at) VALUES ($1, $2, 'call.answered', '{}', ${startedDate} + INTERVAL '8 seconds')`, [callId, 'evt_ans_'+callId]);
          await client.query(`INSERT INTO public.call_events (call_id, event_id, kind, payload, occurred_at) VALUES ($1, $2, 'call.completed', '{}', ${endedDate})`, [callId, 'evt_comp_'+callId]);
        }

        if (callStatus === 'completed' && scoreObj) {
          // Lead Scores
          await client.query(`
            INSERT INTO public.lead_scores (lead_id, call_id, classification, score_0_100, reason, summary, next_action, scored_at, extracted)
            VALUES ($1, $2, $3, $4, $5, $6, $7, ${endedDate} + INTERVAL '10 seconds', $8)
          `, [
            leadId, callId, scoreObj.class, scoreObj.score, scoreObj.reason, scoreObj.summary, 
            scoreObj.class === 'hot' ? 'Send quotation immediately' : (scoreObj.class === 'warm' ? 'Follow up next week' : null),
            JSON.stringify({ material: scoreObj.class === 'hot' ? getRandom(products) : null })
          ]);

          // Qualification Slots
          await client.query(`
            INSERT INTO public.qualification_slots (call_id, tenant_id, lead_id, product_interest, volume_monthly_kg, buying_frequency, decision_role, timeline_days, buying_confidence)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
          `, [callId, tenantId, leadId, getRandom(products), scoreObj.volume, scoreObj.freq, scoreObj.role, scoreObj.class==='hot'?7:30, scoreObj.score/100.0]);

          // Handoffs for Hot/Warm
          if (scoreObj.class === 'hot' || scoreObj.class === 'warm') {
            await client.query(`
              INSERT INTO public.handoffs (lead_id, call_id, channel, sent_to, sent_at, opened_at)
              VALUES ($1, $2, 'whatsapp', $3, ${endedDate} + INTERVAL '2 minutes', ${endedDate} + INTERVAL '10 minutes')
            `, [leadId, callId, lead.phone]);
          }

          // Transcripts
          const product = getRandom(products);
          let currentTs = 1000;
          for (let t = 0; t < hotTranscriptTemplate.length; t++) {
            const line = hotTranscriptTemplate[t];
            let text = line.text.replace('{name}', lead.name.split(' ')[0]).replace('{company}', lead.company).replace('{product}', product);
            await client.query(`
              INSERT INTO public.transcripts (call_id, speaker, text, lang, ts_ms, idx)
              VALUES ($1, $2, $3, 'en-IN', $4, $5)
            `, [callId, line.speaker, text, currentTs, t]);
            
            // Turn Latencies (simulating real network timings)
            if (line.speaker === 'agent') {
              await client.query(`
                INSERT INTO public.turn_latencies (call_id, tenant_id, turn_idx, stt_final_ms, llm_first_token_ms, tts_first_chunk_ms, total_turn_ms, occurred_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, ${startedDate} + INTERVAL '${currentTs/1000} seconds')
              `, [callId, tenantId, t, Math.floor(Math.random()*200+100), Math.floor(Math.random()*400+300), Math.floor(Math.random()*150+50), Math.floor(Math.random()*800+500)]);
            }
            
            currentTs += text.length * 50 + 1000;
            if (scoreObj.class === 'cold' && t >= 3) break;
            if (scoreObj.class === 'warm' && t >= 5) break;
          }
        }
      }
      if (i % 20 === 0) console.log(`Inserted ${i+1}/120...`);
    }

    console.log(`Massive ALL-TABLE realistic seeding complete! Total estimated credits used: ${totalCredits}`);
  } catch (err) {
    console.error("Error seeding DB:", err);
  } finally {
    await client.end();
  }
}

seedUltimate();
