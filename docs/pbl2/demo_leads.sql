-- Demo data for the PBL review: one hand-written warm Tamil lead (Venkatesh, Porur).
-- Synthetic sample, not a real call. Load after `supabase db reset` and seed-remote-ultimate.js:
--   docker exec -i supabase_db_ai-voice psql -U postgres -v ON_ERROR_STOP=1 < docs/pbl2/demo_leads.sql
\set T '00000000-0000-0000-0000-0000000000c1'
\set L 'f216342e-59c5-47c4-bd69-6dfde9bc2158'
\set C '7c1d5c6e-3b52-4b8e-9d0e-0a5f2c9e7a11'

delete from public.leads where id = :'L';

insert into public.leads (id, tenant_id, name, phone_e164, company, source, status, preferred_lang, created_at)
values (:'L', :'T', 'Venkatesh', '+919840271563', null, 'Website enquiry', 'warm', 'ta-IN', now() - interval '1 day');

insert into public.calls (id, tenant_id, lead_id, status, kind, language_used, duration_sec, created_at, started_at, ended_at)
values (:'C', :'T', :'L', 'completed', 'ai_outbound', 'ta-IN', 196,
        now() - interval '2 hours', now() - interval '2 hours', now() - interval '2 hours' + interval '196 seconds');

insert into public.transcripts (call_id, speaker, text, lang, ts_ms, idx) values
(:'C','agent','Vanakkam Venkatesh sir, naan Priya, XYZ Broker-la irundhu pesuren. Porur-la neenga flat paathutu irundheenga, rendu nimisham pesalama?','ta-IN',0,0),
(:'C','lead','ஆமா, சொல்லுங்க. போரூர்ல ஒரு 2 BHK பார்த்துட்டு இருக்கேன்.','ta-IN',9000,1),
(:'C','agent','Super sir. Sontha use-ku-a, illa investment-ku-a paakreenga?','ta-IN',15000,2),
(:'C','lead','சொந்தமா இருக்கத்தான். இப்போ வாடகை வீடு, ஆபீஸ் கிண்டில இருக்கு, அதனால போரூர் வசதியா இருக்கும்.','ta-IN',21000,3),
(:'C','agent','Purinjudhu sir. Budget evlo range-la vechirukeenga?','ta-IN',33000,4),
(:'C','lead','அறுபத்தைந்து முதல் எழுபது லட்சம் வரைக்கும் பார்க்கலாம். SBI-ல லோன் pre-approval வாங்கிட்டேன்.','ta-IN',39000,5),
(:'C','agent','Romba nalladhu sir. Mount Poonamallee Road pakkathula oru ready-to-move project irukku, 2 BHK 68 lakh-la aarambikkudhu. Eppo shift aaganum?','ta-IN',52000,6),
(:'C','lead','ஒரு மூணு நாலு மாசத்துக்குள்ள. ஆனா முதல்ல என் மனைவியோட பேசிட்டு தான் site visit முடிவு பண்ணுவேன்.','ta-IN',66000,7),
(:'C','agent','Kandippa sir. Project details, floor plan ellam unga WhatsApp-ku anuppuren. Adutha vaaram oru call panni visit fix pannalama?','ta-IN',80000,8),
(:'C','lead','சரி, அனுப்புங்க. அடுத்த வாரம் புதன்கிழமை சாயங்காலம் கூப்பிடுங்க.','ta-IN',93000,9),
(:'C','agent','Done sir, Wednesday saayangaalam call panren. Nandri Venkatesh sir!','ta-IN',101000,10);

insert into public.qualification_slots (call_id, tenant_id, lead_id, product_interest, buying_frequency, pain_point, decision_role, timeline_days, buying_confidence, slot_confidence, last_turn_idx)
values (:'C', :'T', :'L', '2 BHK Porur, buy, 65-70 lakh', 'one_off', 'Rented home far from office in Guindy', 'owner', 105, 0.62,
        '{"product_interest": 0.9, "timeline_days": 0.8, "pain_point": 0.7, "decision_role": 0.6}', 5);

insert into public.lead_scores (lead_id, call_id, classification, score_0_100, reason, summary, next_action, extracted, scored_at)
values (:'L', :'C', 'warm', 74,
 'Clear requirement, budget and a pre-approved loan, but the site visit is not committed yet pending a family discussion.',
 'Venkatesh wants a 2 BHK in Porur for self-use because his office is in Guindy. Budget is 65-70 lakh with an SBI home-loan pre-approval, moving in within 3-4 months. He liked the ready-to-move project on Mount Poonamallee Road but will discuss with his wife before a site visit, and asked for a call back next Wednesday evening.',
 'followup_3d',
 '{"intent": "buy", "budget_range": "65-70 lakh", "locality": "Porur", "bhk": "2 BHK", "possession_timeline": "within 3-4 months", "purpose": "self_use", "loan_status": "SBI pre-approved", "product_interest": "2 BHK Porur, ready-to-move", "pain_point": "Rented home far from office in Guindy", "decision_maker_whatsapp": "+919840271563", "buying_confidence": 0.62}',
 now() - interval '2 hours' + interval '210 seconds');

insert into public.turn_latencies (call_id, tenant_id, turn_idx, stt_final_ms, llm_first_token_ms, tts_first_chunk_ms, total_turn_ms, occurred_at)
select :'C', :'T', i, 60 + (i * 7) % 40, 380 + (i * 53) % 220, 290 + (i * 37) % 180, 930 + (i * 71) % 300,
       now() - interval '2 hours' + make_interval(secs => 15 * i)
from generate_series(1, 5) i;

insert into public.handoffs (lead_id, call_id, channel, sent_to, sent_at)
values (:'L', :'C', 'whatsapp', '+919840271563', now() - interval '2 hours' + interval '220 seconds');
