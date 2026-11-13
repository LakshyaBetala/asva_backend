-- The agent posted lead_scores.extracted as json.dumps(...), so jsonb stored a JSON *string*
-- and the CRM verdict panel (extracted.bhk, extracted.locality, ...) read nothing.
-- Unwrap existing string rows into objects; the client now sends an object.
update public.lead_scores
   set extracted = (extracted #>> '{}')::jsonb
 where jsonb_typeof(extracted) = 'string';
