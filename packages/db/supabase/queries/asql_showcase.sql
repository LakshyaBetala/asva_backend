-- Advanced-SQL analytics over the CRM data. Read-only; run after seed-remote-ultimate.js.
-- Each query is self-contained and can be run on its own in the Supabase SQL editor.

-- Q1. Lead leaderboard: CTE + LATERAL (latest score per lead) + RANK() window per class.
with latest as (
  select l.id, l.name, l.company, s.classification, s.score_0_100
    from public.leads l
    cross join lateral (
      select classification, score_0_100 from public.lead_scores
       where lead_id = l.id order by scored_at desc limit 1) s
)
select classification, name, company, score_0_100,
       rank() over (partition by classification order by score_0_100 desc) as class_rank
  from latest
 order by array_position(array['hot','warm','cold'], classification), class_rank
 limit 15;

-- Q2. Conversion funnel with aggregate FILTER clauses.
select count(*)                                                      as leads,
       count(*) filter (where c.id is not null)                      as dialled,
       count(*) filter (where c.status = 'completed')                as connected,
       count(*) filter (where s.classification = 'hot')              as hot,
       count(*) filter (where h.id is not null)                      as handed_off,
       round(100.0 * count(*) filter (where s.classification = 'hot')
             / nullif(count(*) filter (where c.status = 'completed'), 0), 1) as hot_rate_pct
  from public.leads l
  left join public.calls c       on c.lead_id = l.id
  left join public.lead_scores s on s.call_id = c.id
  left join public.handoffs h    on h.call_id = c.id;

-- Q3. Daily credit burn with gap-filled calendar (generate_series) and running total window.
select d::date                                              as day,
       coalesce(sum(c.billed_units), 0)                     as credits,
       sum(coalesce(sum(c.billed_units), 0)) over (order by d) as running_credits
  from generate_series(date_trunc('day', now()) - interval '13 days', date_trunc('day', now()), interval '1 day') d
  left join public.calls c on date_trunc('day', c.ended_at) = d
 group by d
 order by d;

-- Q4. Subtotals by call status and credit tier: GROUP BY ROLLUP + GROUPING().
select case when grouping(status) = 1 then 'ALL' else status end           as status,
       case when grouping(billed_units) = 1 then 'ALL' else billed_units::text end as credits,
       count(*) as calls, sum(estimated_cost_inr) as cost_inr
  from public.calls
 group by rollup (status, billed_units)
 order by grouping(status), status, grouping(billed_units), billed_units;

-- Q5. Voice latency SLO: ordered-set aggregates (p50/p95) per pipeline stage.
select percentile_cont(0.50) within group (order by stt_final_ms)::int       as stt_p50,
       percentile_cont(0.50) within group (order by llm_first_token_ms)::int as llm_p50,
       percentile_cont(0.50) within group (order by total_turn_ms)::int      as turn_p50,
       percentile_cont(0.95) within group (order by total_turn_ms)::int      as turn_p95,
       round(100.0 * count(*) filter (where total_turn_ms < 1000) / count(*), 1) as pct_under_1s
  from public.turn_latencies;

-- Q6. Call setup time from the event log: LAG() over each call's ordered events.
select kind,
       round(avg(extract(epoch from occurred_at - prev_at))::numeric, 1) as avg_secs_since_prev_event
  from (select kind, occurred_at,
               lag(occurred_at) over (partition by call_id order by occurred_at) as prev_at
          from public.call_events) e
 where prev_at is not null
 group by kind
 order by avg_secs_since_prev_event;

-- Q7. Semi-structured data: JSONB extraction joined with typed qualification slots.
select s.extracted ->> 'material'          as material_from_llm,
       count(*)                            as hot_leads,
       round(avg(q.volume_monthly_kg))     as avg_monthly_kg,
       round(avg(q.buying_confidence), 2)  as avg_confidence
  from public.lead_scores s
  join public.qualification_slots q on q.call_id = s.call_id
 where s.classification = 'hot' and s.extracted ? 'material'
 group by 1
 order by hot_leads desc;

-- Q8. Index usage: the composite (tenant_id, status) index serves the CRM list query.
explain select id, name from public.leads
 where tenant_id = '00000000-0000-0000-0000-0000000000c1' and status = 'hot';
