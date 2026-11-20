// ASVA PBL-II refined deck. Run: NODE_PATH=./node_modules node build.js
const pptxgen = require("pptxgenjs");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const sharp = require("sharp");
const lu = require("react-icons/lu");
const path = require("path");
const { applyTheme } = require("C:/Users/laksh/.claude/skills/synced/c4a79f97-a250-450c-9828-c9ed22fa6b9a_87dd6128-358a-415e-b3bd-ba1d1e38fa82/pptx/scripts/apply_theme.js");

const THEME = {
  name: "ASVA Pine", headFontFace: "Cambria", bodyFontFace: "Calibri",
  colors: { dk1: "17202A", lt1: "FFFFFF", dk2: "0E4D45", lt2: "EEF3F1", accent1: "0E4D45", accent2: "2A9D8F",
            accent3: "E9A23B", accent4: "C8553D", accent5: "6C7A89", accent6: "BFD8D2", hlink: "2A9D8F", folHlink: "6C7A89" },
};
const HEX = THEME.colors;
const OUT = "ASVA_PBL2_Review_Refined.pptx";
const IMG = (f) => path.join(__dirname, "img", f);

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.title = "ASVA — PBL-II Review";
pres.author = "ASVA team";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
const C = pres.SchemeColor;
const M = 0.6;

async function icon(name, hex, px = 256) {
  const svg = renderToStaticMarkup(React.createElement(lu[name], { size: px, color: "#" + hex }));
  return "image/png;base64," + (await sharp(Buffer.from(svg)).png().toBuffer()).toString("base64");
}
async function picture(s, file, x, y, maxW, maxH, opts = {}) {  // contain-fit, centred in the box
  const { width, height } = await sharp(IMG(file)).metadata();
  const k = Math.min(maxW / width, maxH / height), w = width * k, h = height * k;
  s.addImage({ path: IMG(file), x: x + (maxW - w) / 2, y: y + (maxH - h) / 2, w, h, ...opts });
  return { x: x + (maxW - w) / 2, y: y + (maxH - h) / 2, w, h };
}

// ---------- layouts ----------
const footer = (dark) => ({ text: { text: "PBL-II · Review · ASVA", options: { x: M, y: 7.0, w: 6, h: 0.3, fontSize: 10, color: dark ? "BFD8D2" : "6C7A89", margin: 0 } } });
pres.defineSlideMaster({ title: "TITLE_DARK", background: { color: HEX.dk2 }, objects: [
  { placeholder: { options: { name: "title", type: "title", x: M, y: 1.7, w: 11.2, h: 1.9, fontFace: THEME.headFontFace, fontSize: 44, bold: true, color: C.background1, valign: "bottom", align: "left", margin: 0 }, text: "" } },
  { placeholder: { options: { name: "body", type: "body", x: M, y: 3.85, w: 11.2, h: 0.6, fontSize: 20, color: C.accent6, valign: "top", margin: 0 }, text: "" } } ] });
pres.defineSlideMaster({ title: "SECTION_DARK", background: { color: HEX.dk2 }, objects: [ footer(true),
  { placeholder: { options: { name: "title", type: "title", x: M, y: 2.4, w: 11, h: 1.2, fontFace: THEME.headFontFace, fontSize: 44, bold: true, color: C.background1, valign: "bottom", align: "left", margin: 0 }, text: "" } },
  { placeholder: { options: { name: "body", type: "body", x: M, y: 3.8, w: 11, h: 1.0, fontSize: 20, color: C.accent6, valign: "top", margin: 0 }, text: "" } } ],
  slideNumber: { x: 12.2, y: 7.0, w: 0.5, h: 0.3, fontSize: 10, color: "BFD8D2", align: "right" } });
pres.defineSlideMaster({ title: "CONTENT", background: { color: HEX.lt1 }, objects: [ footer(false),
  { placeholder: { options: { name: "title", type: "title", x: M, y: 0.4, w: 12.1, h: 0.85, fontFace: THEME.headFontFace, fontSize: 34, bold: true, color: C.text2, valign: "middle", align: "left", margin: 0 }, text: "" } } ],
  slideNumber: { x: 12.2, y: 7.0, w: 0.5, h: 0.3, fontSize: 10, color: "6C7A89", align: "right" } });

function slide(master, title, sectionTitle) { const s = pres.addSlide({ masterName: master, sectionTitle }); s.addText(title, { placeholder: "title" }); return s; }
const tx = (s, text, o) => s.addText(text, { isTextBox: true, fontSize: 14, color: C.text1, margin: 0, valign: "top", ...o });
const card = (s, x, y, w, h, fill = C.background2) => s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.08, fill: { color: fill }, line: { color: fill } });
async function dot(s, x, y, name, d = 0.55, bg = C.text2, fg = HEX.lt1) {
  s.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: bg }, line: { color: bg } });
  s.addImage({ data: await icon(name, fg), x: x + d * 0.22, y: y + d * 0.22, w: d * 0.56, h: d * 0.56 });
}
const arrow = (s, x1, y1, x2, y2) => s.addShape(pres.shapes.LINE, { x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1) || 0.001, h: Math.abs(y2 - y1) || 0.001, line: { color: C.accent5, width: 1.5, endArrowType: "triangle" } });
const hdr = (t) => ({ text: t, options: { bold: true, color: C.background1, fill: { color: C.text2 } } });
const caption = (s, t, y = 6.62) => tx(s, t, { x: M, y, w: 12.1, h: 0.3, fontSize: 11, color: C.accent5 });

(async () => {
  // 1 ---------- title
  pres.addSection({ title: "Introduction" });
  let s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "Introduction" });
  s.addText("ASVA: a multilingual AI voice agent on a multi-tenant SQL backbone", { placeholder: "title" });
  s.addText("PBL-II · Advanced SQL · Review", { placeholder: "body" });
  const team = [["Lakshya Betala", "RA2311003012059"], ["Shubham Bhandari", "RA2311003012063"], ["Rishabh Singh Parmar", "RA2311003012079"], ["Ganesh M", "RA2311003012093"]];
  team.forEach(([n, r], i) => tx(s, [{ text: n, options: { bold: true, fontSize: 16, color: C.background1, breakLine: true } }, { text: r, options: { fontSize: 12, color: C.accent6 } }],
    { x: M + (i % 2) * 3.9, y: 4.75 + Math.floor(i / 2) * 0.72, w: 3.7, h: 0.65 }));
  tx(s, [{ text: "Guide", options: { fontSize: 12, color: C.accent6, breakLine: true } }, { text: "Venkatesh CHINNASAMY", options: { bold: true, fontSize: 16, color: C.background1 } }], { x: 9.0, y: 4.75, w: 3.7, h: 0.65 });
  s.addImage({ data: await icon("LuDatabase", HEX.accent6), x: 11.4, y: 0.7, w: 1.2, h: 1.2 });
  s.addNotes("Introduce the team. ASVA phones sales leads in English, Hindi or Tamil, and everything it hears and decides is stored in a multi-tenant PostgreSQL database. Since the last review it runs end to end on a laptop, with replies in under about two seconds.");

  // 2 ---------- problem
  s = slide("CONTENT", "Why we built it", "Introduction");
  tx(s, "Brokers buy hundreds of leads a month but call only a fraction. Calls are manual, limited to the caller's languages, and the outcome lives in a notebook instead of a database.", { x: M, y: 1.6, w: 4.9, h: 2.2, fontSize: 18 });
  card(s, M, 3.95, 4.9, 1.75);
  tx(s, [{ text: "Our goal", options: { bold: true, fontSize: 16, color: C.text2, breakLine: true } }, { text: "Call every lead within minutes, qualify it in the lead's own language, and make every call queryable with SQL." }], { x: M + 0.3, y: 4.15, w: 4.3, h: 1.4, fontSize: 16 });
  const objs = [["LuLanguages", "Speak English, Hindi and Tamil", "Switches language the moment the lead asks, mid-call."],
                ["LuDatabase", "Record every call in PostgreSQL", "13 related tables: leads, calls, transcripts, scores, latency."],
                ["LuShieldCheck", "Isolate each customer's data", "Row-level security inside the database keeps tenants apart."]];
  for (let i = 0; i < 3; i++) {
    const y = 1.6 + i * 1.65; await dot(s, 6.2, y + 0.1, objs[i][0], 0.7);
    tx(s, [{ text: objs[i][1], options: { bold: true, fontSize: 18, color: C.text2, breakLine: true } }, { text: objs[i][2], options: { fontSize: 15 } }], { x: 7.2, y, w: 5.5, h: 1.4 });
  }

  // 3 ---------- SDGs
  s = slide("CONTENT", "Aligned with the UN Sustainable Development Goals", "Introduction");
  const sdg = [["9", "FD6925", "Industry, Innovation and Infrastructure", "Targets 9.5, 9.c", "AI voice and database infrastructure that gives small firms enterprise-grade calling and analytics."],
               ["8", "A21942", "Decent Work and Economic Growth", "Targets 8.2, 8.3", "Automates first-contact calls, so brokers and small businesses follow up every lead and staff focus on real buyers."],
               ["10", "DD1367", "Reduced Inequalities", "Target 10.2", "Serves buyers in Hindi and Tamil, not only English, so non-English speakers get the same service."]];
  for (let i = 0; i < 3; i++) {
    const x = M + i * 4.07;
    card(s, x, 1.55, 3.85, 3.95);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x + 0.3, y: 1.9, w: 1.0, h: 1.0, rectRadius: 0.08, fill: { color: sdg[i][1] }, line: { color: sdg[i][1] } });
    tx(s, sdg[i][0], { x: x + 0.3, y: 1.9, w: 1.0, h: 1.0, fontSize: 32, bold: true, color: "FFFFFF", align: "center", valign: "middle", fontFace: THEME.headFontFace });
    tx(s, `SDG ${sdg[i][0]}`, { x: x + 1.5, y: 1.95, w: 2.2, h: 0.35, fontSize: 13, bold: true, color: sdg[i][1] });
    tx(s, sdg[i][2], { x: x + 1.5, y: 2.3, w: 2.2, h: 0.75, fontSize: 15, bold: true, color: C.text2 });
    tx(s, sdg[i][3], { x: x + 0.3, y: 3.3, w: 3.3, h: 0.35, fontSize: 13, bold: true, color: C.accent2 });
    tx(s, sdg[i][4], { x: x + 0.3, y: 3.75, w: 3.3, h: 1.6, fontSize: 15 });
  }
  card(s, M, 5.75, 12.1, 0.75, C.accent6);
  tx(s, [{ text: "In one line:  ", options: { bold: true, color: C.text2 } }, { text: "ASVA brings enterprise-grade, multilingual lead follow-up to small Indian businesses, in the buyer's own language." }],
     { x: M + 0.25, y: 5.75, w: 11.6, h: 0.75, valign: "middle", fontSize: 15 });

  // 4 ---------- architecture (real figure)
  s = slide("CONTENT", "System architecture", "Introduction");
  await picture(s, "fig_architecture.png", M, 1.4, 12.1, 5.15);
  caption(s, "Every box names the real module: the session handler, the turn engine (STT, language state machine, LLM, TTS) and PostgreSQL with RLS and the billing trigger.");
  s.addNotes("Walk left to right: the call, the turn engine, then everything persisted in PostgreSQL. The CRM and workers read the same tables under row-level security.");

  // 5 ---------- section
  pres.addSection({ title: "Database design" });
  s = pres.addSlide({ masterName: "SECTION_DARK", sectionTitle: "Database design" });
  s.addText("Database design", { placeholder: "title" });
  s.addText("13 tables · 36 indexes · 37 RLS policies · 20 migrations", { placeholder: "body" });

  // 6 ---------- schema (real figure)
  s = slide("CONTENT", "Schema: 13 tables, one tenant root", "Database design");
  await picture(s, "fig_schema.png", M, 1.35, 12.1, 5.25);
  caption(s, "Arrows are foreign keys with their ON DELETE rule (C = cascade, N = set null, R = restrict). Tables marked T also reference tenants.");

  // 7 ---------- constraints
  s = slide("CONTENT", "Integrity enforced by the database", "Database design");
  const rows = [["PRIMARY KEY uuid_generate_v4()", "all 13 tables", "IDs never collide across tenants"],
    ["FK … ON DELETE CASCADE", "calls → leads, transcripts → calls", "Deleting a lead removes its history"],
    ["FK … ON DELETE RESTRICT", "users → tenants", "A tenant with users cannot be dropped"],
    ["FK … ON DELETE SET NULL", "leads.assigned_to, calls.campaign_id", "History survives a removed rep"],
    ["UNIQUE (tenant_id, phone_e164)", "leads", "No duplicate lead per customer"],
    ["UNIQUE (call_id, idx)", "transcripts", "Each line of a call stored once, in order"],
    ["CHECK", "status, classification, score 0–100, credits 0–4", "Invalid states are rejected"],
    ["Partial UNIQUE … WHERE NOT NULL", "tenants.ingest_api_key", "Unique keys, any number of NULLs"]];
  s.addTable([[hdr("Constraint"), hdr("Applied to"), hdr("What it guarantees")],
    ...rows.map((r, i) => r.map((c, j) => ({ text: c, options: { fontFace: j === 0 ? "Courier New" : undefined, fontSize: j === 0 ? 13 : 14, fill: { color: i % 2 ? C.background1 : C.background2 } } })))],
    { x: M, y: 1.5, w: 12.1, colW: [4.3, 4.2, 3.6], rowH: 0.52, fontSize: 14, color: C.text1, border: { type: "none" }, valign: "middle", margin: [0, 0.12, 0, 0.12] });

  // 8 ---------- RLS
  s = slide("CONTENT", "Row-level security isolates every tenant", "Database design");
  const steps = ["User logs in", "Login hook adds tenant_id claim", "current_tenant_id() reads it", "Policy compares row.tenant_id", "Only own rows returned"];
  for (let i = 0; i < 5; i++) {
    const x = M + i * 2.46;
    card(s, x, 1.55, 2.2, 1.1, i === 3 ? C.text2 : C.background2);
    tx(s, steps[i], { x: x + 0.15, y: 1.55, w: 1.9, h: 1.1, valign: "middle", fontSize: 15, bold: true, color: i === 3 ? C.background1 : C.text2 });
    if (i < 4) arrow(s, x + 2.22, 2.1, x + 2.44, 2.1);
  }
  card(s, M, 3.0, 5.9, 1.55);
  tx(s, [{ text: "Tables with tenant_id", options: { bold: true, color: C.text2, breakLine: true } },
    { text: "CREATE POLICY leads_tenant_read ON leads FOR SELECT USING (tenant_id = current_tenant_id());", options: { fontFace: "Courier New", fontSize: 13 } }], { x: M + 0.25, y: 3.15, w: 5.4, h: 1.3 });
  card(s, M, 4.75, 5.9, 1.65);
  tx(s, [{ text: "Child tables without tenant_id", options: { bold: true, color: C.text2, breakLine: true } },
    { text: "USING (EXISTS (SELECT 1 FROM calls c WHERE c.id = transcripts.call_id AND c.tenant_id = current_tenant_id()))", options: { fontFace: "Courier New", fontSize: 13 } }], { x: M + 0.25, y: 4.9, w: 5.4, h: 1.4 });
  tx(s, "Verified, including through the live CRM", { x: 7.0, y: 3.0, w: 5.7, h: 0.4, bold: true, fontSize: 16, color: C.text2 });
  const checks = ["Tenant A sees only its own leads; tenant B only its own", "Cross-tenant INSERT blocked by WITH CHECK", "Logged-in CRM user sees 120 leads; anonymous request sees 0", "Duplicate phone, score 150, unknown status rejected"];
  for (let i = 0; i < 4; i++) { await dot(s, 7.0, 3.55 + i * 0.72, "LuCheck", 0.42, C.accent2); tx(s, checks[i], { x: 7.6, y: 3.55 + i * 0.72, w: 5.1, h: 0.42, valign: "middle", fontSize: 15 }); }

  // 9 ---------- trigger
  s = slide("CONTENT", "A trigger computes billing on every call", "Database design");
  card(s, M, 1.5, 6.9, 4.45, "17202A");
  tx(s, ["CREATE TRIGGER calls_compute_billed_units", "  BEFORE INSERT OR UPDATE OF status, duration_sec", "  ON public.calls FOR EACH ROW", "  EXECUTE FUNCTION compute_billed_units();", "", "-- inside the PL/pgSQL function",
         "IF NEW.status = 'completed' THEN", "  NEW.billed_units := CASE", "    WHEN NEW.duration_sec <= 150 THEN 1", "    WHEN NEW.duration_sec <= 300 THEN 2", "    WHEN NEW.duration_sec <= 450 THEN 3", "    ELSE 4 END;", "END IF;"]
     .map((l, i, a) => ({ text: l, options: { breakLine: i < a.length - 1, color: l.startsWith("--") ? "8FB8AE" : "E8EEF0" } })), { x: M + 0.3, y: 1.75, w: 6.4, h: 4.0, fontFace: "Courier New", fontSize: 14 });
  const tiers = [["0 – 150 s", "1 credit"], ["151 – 300 s", "2 credits"], ["301 – 450 s", "3 credits"], ["451 – 600 s", "4 credits"]];
  tx(s, "Credit tiers", { x: 8.0, y: 1.5, w: 4.7, h: 0.4, bold: true, fontSize: 16, color: C.text2 });
  for (let i = 0; i < 4; i++) { card(s, 8.0, 2.0 + i * 0.75, 4.7, 0.62, i % 2 ? C.background1 : C.background2);
    tx(s, tiers[i][0], { x: 8.25, y: 2.0 + i * 0.75, w: 2.2, h: 0.62, valign: "middle", fontSize: 16 });
    tx(s, tiers[i][1], { x: 10.4, y: 2.0 + i * 0.75, w: 2.1, h: 0.62, valign: "middle", fontSize: 16, bold: true, color: C.text2 }); }
  tx(s, "Example from the CRM: a 196-second Tamil call was billed 2 credits (₹24) by the trigger, with no application code involved.", { x: 8.0, y: 5.15, w: 4.7, h: 1.2, fontSize: 14, color: C.accent5 });

  // 10 ---------- views/functions
  s = slide("CONTENT", "Views and functions behind the CRM", "Database design");
  const fns = [["LuTable", "tenant_monthly_units", "VIEW", "GROUP BY tenant and month with SUM and COUNT … FILTER. Powers the credits meter in the CRM header."],
               ["LuGauge", "tenant_spend_today(uuid)", "SQL FUNCTION · STABLE", "Sums today's cost on an India-time day boundary. The dispatcher calls it before every outbound call."],
               ["LuKeyRound", "current_tenant_id()", "SQL FUNCTION · STABLE", "Reads tenant_id from the request's JWT claims. All 37 tenant policies use it."],
               ["LuFileCode", "custom_access_token_hook(jsonb)", "PL/pgSQL", "Runs at login; adds tenant_id and user_role to the token with jsonb_set."]];
  for (let i = 0; i < 4; i++) {
    const x = M + (i % 2) * 6.15, y = 1.55 + Math.floor(i / 2) * 2.2;
    card(s, x, y, 5.95, 1.95); await dot(s, x + 0.25, y + 0.3, fns[i][0], 0.6);
    tx(s, fns[i][1], { x: x + 1.05, y: y + 0.28, w: 4.7, h: 0.4, fontFace: "Courier New", bold: true, fontSize: 15, color: C.text2 });
    tx(s, fns[i][2], { x: x + 1.05, y: y + 0.68, w: 4.7, h: 0.3, fontSize: 12, bold: true, color: C.accent2 });
    tx(s, fns[i][3], { x: x + 1.05, y: y + 1.0, w: 4.7, h: 0.9, fontSize: 14 });
  }
  card(s, M, 6.0, 12.1, 0.6, C.accent6);
  tx(s, [{ text: "Realtime:  ", options: { bold: true, color: C.text2 } }, { text: "calls, transcripts and lead_scores are published, so the CRM updates while a call is in progress." }], { x: M + 0.25, y: 6.0, w: 11.6, h: 0.6, valign: "middle", fontSize: 14 });

  // 11 ---------- seven bugs
  s = slide("CONTENT", "Running the system exposed seven database bugs", "Database design");
  const bugs = [["Calls over 300 s rejected", "CHECK capped credits at 2; trigger assigned 3", "Constraint widened to 0–4"],
    ["One call 'cost' ₹2,00,000", "Cost used average order value; ₹600 daily cap halted dispatch", "₹12/credit fallback; rows repaired"],
    ["Every user saw zero leads", "Login hook blocked by RLS on users", "Role-scoped GRANT + policy"],
    ["Every CRM query failed", "Hook wrote app role into JWT role: role \"admin\" does not exist", "App role moved to user_role claim"],
    ["CRM login returned 500", "Seeded auth user had NULL created_at", "Seed sets timestamps"],
    ["Half of each transcript lost", "Lead and agent lines shared one idx; UNIQUE dropped one", "Interleaved idx = 2·turn (+1 agent)"],
    ["AI verdict fields blank", "extracted stored as a JSON string, not an object", "Send object; migration unwraps old rows"]];
  s.addTable([[hdr("#"), hdr("Symptom"), hdr("Root cause"), hdr("Fix (forward migration / code)")],
    ...bugs.map((b, i) => [`D${i + 1}`, ...b].map((c, j) => ({ text: c, options: { bold: j === 1, color: j === 1 ? C.text2 : C.text1, fill: { color: i % 2 ? C.background1 : C.background2 } } })))],
    { x: M, y: 1.45, w: 12.1, colW: [0.55, 3.0, 5.0, 3.55], rowH: 0.6, fontSize: 13, color: C.text1, border: { type: "none" }, valign: "middle", margin: [0, 0.1, 0, 0.1] });
  caption(s, "D1–D3 found by executing migrations on a fresh PostgreSQL; D4–D7 found by running real calls through the CRM. Each fix is a forward migration or a code change with a test.", 6.5);

  // 12 ---------- queries
  s = slide("CONTENT", "Advanced SQL over live call data", "Database design");
  const qs = [["CTE + LATERAL + RANK()", "Latest score per lead, ranked within Hot, Warm and Cold"], ["COUNT(*) FILTER (WHERE …)", "One-pass funnel: 120 leads → 111 dialled → 46 connected → 11 hot"],
    ["generate_series + SUM() OVER", "14-day credit burn with empty days filled and a running total"], ["GROUP BY ROLLUP + GROUPING()", "Calls and cost by status and credit tier, with subtotals"],
    ["percentile_cont … WITHIN GROUP", "p50 / p95 turn latency per pipeline stage"], ["LAG() OVER (PARTITION BY call)", "Time between call events: rings in 2 s, answered in 6 s"],
    ["JSONB ->> and ? operators", "Hot leads by product the LLM extracted from the conversation"], ["EXPLAIN", "The CRM list query uses an Index Scan, not a Seq Scan"]];
  for (let i = 0; i < 8; i++) {
    const x = M + (i % 2) * 6.15, y = 1.5 + Math.floor(i / 2) * 1.3;
    card(s, x, y, 5.95, 1.12);
    tx(s, `Q${i + 1}`, { x: x + 0.2, y, w: 0.6, h: 1.12, valign: "middle", fontFace: THEME.headFontFace, fontSize: 20, bold: true, color: C.accent2 });
    tx(s, [{ text: qs[i][0], options: { fontFace: "Courier New", bold: true, fontSize: 13, color: C.text2, breakLine: true } }, { text: qs[i][1], options: { fontSize: 14 } }], { x: x + 0.85, y: y + 0.1, w: 4.95, h: 0.95, valign: "middle" });
  }
  caption(s, "All eight queries: packages/db/supabase/queries/asql_showcase.sql (also in the implementation-code PDF).", 6.75);

  // 13 ---------- results + EXPLAIN
  s = slide("CONTENT", "What the queries return, and how fast", "Database design");
  s.addChart(pres.charts.BAR, [{ name: "Leads", labels: ["Leads", "Dialled", "Connected", "Handed off", "Hot"], values: [120, 111, 46, 27, 11] }], {
    x: M, y: 1.45, w: 6.6, h: 4.9, barDir: "bar", catAxisOrientation: "maxMin", chartColors: [HEX.accent2], showValue: true, dataLabelPosition: "outEnd", dataLabelColor: HEX.dk1,
    dataLabelFontSize: 13, dataLabelFontFace: "+mn-lt", catAxisLabelColor: HEX.dk1, catAxisLabelFontSize: 14, catAxisLabelFontFace: "+mn-lt", valAxisHidden: true,
    valGridLine: { style: "none" }, catGridLine: { style: "none" }, showLegend: false, showTitle: true, title: "Conversion funnel (Q2, seeded data)", titleFontSize: 16, titleColor: HEX.dk2, titleFontFace: "+mn-lt", barGapWidthPct: 45 });
  card(s, 7.6, 1.5, 5.1, 2.5, "17202A");
  tx(s, [{ text: "EXPLAIN SELECT id, name FROM leads", options: { breakLine: true, color: "8FB8AE" } }, { text: " WHERE tenant_id = $1 AND status = 'hot';", options: { breakLine: true, color: "8FB8AE" } },
         { text: " ", options: { breakLine: true } }, { text: "Index Scan using leads_tenant_status_idx", options: { breakLine: true, color: "FFFFFF", bold: true } },
         { text: "  Index Cond: tenant_id = …", options: { breakLine: true, color: "E8EEF0" } }, { text: "    AND status = 'hot'", options: { color: "E8EEF0" } }],
     { x: 7.85, y: 1.7, w: 4.7, h: 2.1, fontFace: "Courier New", fontSize: 13 });
  tx(s, "36 indexes, each tied to a query. Composite indexes lead with tenant_id because every query row-level security rewrites is already filtered by tenant.", { x: 7.6, y: 4.25, w: 5.1, h: 1.5, fontSize: 15 });
  caption(s, "Funnel numbers come from 120 seeded demo leads; the query plan is from the live database.", 6.5);

  // 14 ---------- section working system
  pres.addSection({ title: "Working system" });
  s = pres.addSlide({ masterName: "SECTION_DARK", sectionTitle: "Working system" });
  s.addText("The working system", { placeholder: "title" });
  s.addText("Voice agent → PostgreSQL → CRM, running end to end on one laptop", { placeholder: "body" });

  // 15 ---------- CRM screenshot
  s = slide("CONTENT", "The CRM, reading the database through RLS", "Working system");
  const shot = await picture(s, "leads.png", M, 1.4, 7.6, 5.2, { line: { color: HEX.accent6, width: 1 } });
  const pts = [["LuLogIn", "Real login", "Supabase Auth issues a token; the hook adds the tenant claim"], ["LuFilter", "Live filters", "All 120 · Hot · Warm · Cold · Unscored, from lead_scores"],
               ["LuGauge", "Credits meter", "tenant_monthly_units view: credits used this month"], ["LuRadio", "Realtime", "New calls and transcripts appear without a refresh"]];
  for (let i = 0; i < 4; i++) { const y = 1.5 + i * 1.25; await dot(s, 8.6, y, pts[i][0], 0.55);
    tx(s, [{ text: pts[i][1], options: { bold: true, fontSize: 16, color: C.text2, breakLine: true } }, { text: pts[i][2], options: { fontSize: 14 } }], { x: 9.3, y: y - 0.05, w: 3.4, h: 1.1 }); }

  // 16 ---------- a call lands in the CRM
  s = slide("CONTENT", "A local voice call lands in the CRM", "Working system");
  await picture(s, "verdict.png", 6.9, 1.35, 5.8, 5.3, { line: { color: HEX.accent6, width: 1 } });
  const flow = [["LuMic", "Lead speaks", "Laptop mic; speech-to-text streams while they talk"], ["LuBrain", "Priya replies", "LLM answers in the lead's language; voice plays in ~1–2 s"],
                ["LuDatabase", "Every turn is written", "calls, transcripts, qualification_slots, turn_latencies"], ["LuSparkles", "Post-call scoring", "LLM verdict + broker fields into lead_scores; lead status updated"]];
  for (let i = 0; i < 4; i++) { const y = 1.45 + i * 1.3; await dot(s, M, y, flow[i][0], 0.6);
    tx(s, [{ text: flow[i][1], options: { bold: true, fontSize: 17, color: C.text2, breakLine: true } }, { text: flow[i][2], options: { fontSize: 14 } }], { x: M + 0.8, y: y - 0.05, w: 5.3, h: 1.15 });
    if (i < 3) arrow(s, M + 0.3, y + 0.65, M + 0.3, y + 1.25); }
  caption(s, "Screenshot: a real local call, scored Hot 95 with buy / 80 lakhs / 2 BHK / site visit Saturday 10 AM extracted automatically.", 6.7);

  // 17 ---------- language switching
  s = slide("CONTENT", "Language switching, stored line by line", "Working system");
  await picture(s, "transcript_en_hi.png", M, 1.4, 6.0, 4.4, { line: { color: HEX.accent6, width: 1 } });
  await picture(s, "transcript_ta.png", 6.75, 1.4, 6.0, 4.4, { line: { color: HEX.accent6, width: 1 } });
  tx(s, [{ text: "English → Hindi  ", options: { bold: true, color: C.text2 } }, { text: "the lead asks \"Hindi mein baat kar sakte hain?\" and Priya switches immediately." }], { x: M, y: 5.95, w: 6.0, h: 0.7, fontSize: 14 });
  tx(s, [{ text: "Tamil  ", options: { bold: true, color: C.text2 } }, { text: "a warm Porur lead (2 BHK, ₹65–70 lakh); every line tagged TA-IN in transcripts.lang." }], { x: 6.75, y: 5.95, w: 6.0, h: 0.7, fontSize: 14 });

  // 18 ---------- latency
  s = slide("CONTENT", "Latency: from 7–16 s down to under 2 s", "Working system");
  const big = [["7–16 s", "before: time to first audio (13 Nov)", C.accent4], ["1.7–2.1 s", "after: measured, 4- and 6-turn calls", C.accent2], ["56 ms", "streaming speech-to-text: final transcript after speech ends", C.text2]];
  for (let i = 0; i < 3; i++) { card(s, M, 1.5 + i * 1.6, 3.6, 1.42);
    tx(s, big[i][0], { x: M + 0.25, y: 1.6 + i * 1.6, w: 3.2, h: 0.7, fontFace: THEME.headFontFace, fontSize: 30, bold: true, color: big[i][2] });
    tx(s, big[i][1], { x: M + 0.25, y: 2.3 + i * 1.6, w: 3.2, h: 0.6, fontSize: 13 }); }
  s.addChart(pres.charts.BAR, [{ name: "First sentence (ms)", labels: ["Qwen3 27B (Groq), thinking off", "gpt-oss-120b (Groq), low", "gpt-oss-20b (Groq), low", "Gemini 2.5 Flash"], values: [373, 614, 627, 1321] }], {
    x: 4.55, y: 1.45, w: 8.2, h: 3.25, barDir: "bar", catAxisOrientation: "maxMin", chartColors: [HEX.accent2], showValue: true, dataLabelPosition: "outEnd", dataLabelColor: HEX.dk1,
    dataLabelFontSize: 12, dataLabelFontFace: "+mn-lt", catAxisLabelColor: HEX.dk1, catAxisLabelFontSize: 12, catAxisLabelFontFace: "+mn-lt", valAxisHidden: true,
    valGridLine: { style: "none" }, catGridLine: { style: "none" }, showLegend: false, showTitle: true, title: "LLM time to first sentence, real 9k-character prompt (ms)", titleFontSize: 14, titleColor: HEX.dk2, titleFontFace: "+mn-lt", barGapWidthPct: 40 });
  const changes = ["Speech-to-text runs while the lead speaks (Sarvam streaming, India-hosted)", "Fastest LLM chosen by benchmark; reasoning switched off", "Removed a cloud cache lookup that cost seconds per sentence", "Failover: Groq Qwen → Groq gpt-oss → Gemini, so a turn never stalls"];
  tx(s, changes.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < changes.length - 1 } })), { x: 4.75, y: 4.85, w: 7.95, h: 1.7, fontSize: 14, paraSpaceAfter: 5 });

  // 19 ---------- scaling
  pres.addSection({ title: "Scale and status" });
  s = slide("CONTENT", "How the database scales", "Scale and status");
  card(s, M, 1.5, 3.6, 5.0, C.text2);
  tx(s, "≈ 4.2 M", { x: M + 0.3, y: 1.8, w: 3.1, h: 0.9, fontFace: THEME.headFontFace, fontSize: 40, bold: true, color: C.background1 });
  tx(s, "rows a month at 100 tenants × 2,000 calls, about 21 rows per call.", { x: M + 0.3, y: 2.8, w: 3.05, h: 1.2, fontSize: 15, color: C.accent6 });
  tx(s, "≈ 50 M", { x: M + 0.3, y: 4.2, w: 3.1, h: 0.8, fontFace: THEME.headFontFace, fontSize: 32, bold: true, color: C.background1 });
  tx(s, "rows a year: past what an unpartitioned table should hold.", { x: M + 0.3, y: 5.0, w: 3.05, h: 1.1, fontSize: 15, color: C.accent6 });
  const plan = [["LuLayers", "Partition by month", "RANGE-partition calls, transcripts, call_events, turn_latencies; drop old partitions instead of DELETE."],
                ["LuServer", "Pool connections", "Transaction-mode pooler so thousands of short requests share a few backends."],
                ["LuSigma", "Pre-aggregate", "Materialized views for dashboards refreshed by pg_cron; BRIN index on occurred_at."],
                ["LuSplit", "Split reads from writes", "A read replica for analytics; the primary stays fast for live calls."],
                ["LuGlobe", "Move closer to users", "Host in Mumbai (ap-south-1): India-hosted APIs answered in 34 ms vs 260–360 ms."]];
  for (let i = 0; i < 5; i++) { const y = 1.5 + i * 1.0; await dot(s, 4.55, y + 0.12, plan[i][0], 0.55);
    tx(s, [{ text: plan[i][1] + "  ", options: { bold: true, color: C.text2 } }, { text: plan[i][2] }], { x: 5.3, y, w: 7.4, h: 0.85, fontSize: 14, valign: "middle" }); }

  // 20 ---------- verification + outputs
  s = slide("CONTENT", "Verification and research output", "Scale and status");
  const ev = [["389", "Python agent tests passing"], ["116", "Worker tests passing"], ["20", "Migrations applied to fresh PostgreSQL 17"], ["7", "Database bugs found and fixed"]];
  for (let i = 0; i < 4; i++) { const x = M + i * 3.07; card(s, x, 1.5, 2.85, 2.0);
    tx(s, ev[i][0], { x: x + 0.2, y: 1.65, w: 2.5, h: 0.8, fontFace: THEME.headFontFace, fontSize: 34, bold: true, color: C.text2 });
    tx(s, ev[i][1], { x: x + 0.2, y: 2.5, w: 2.5, h: 0.85, fontSize: 15 }); }
  const outs = [["LuFileText", "IEEE conference paper draft", "7 pages: sentence-pipelined streaming, hysteresis language control, database-enforced tenancy; every number from measured data"],
                ["LuCode", "Implementation-code document", "17 pages: schema, RLS, trigger, views, analytics queries and persistence code"],
                ["LuPlay", "One-command demo", "run-all: starts database + CRM, opens a lead, starts the voice call"]];
  for (let i = 0; i < 3; i++) { const y = 3.85 + i * 0.95; await dot(s, M, y, outs[i][0], 0.55);
    tx(s, [{ text: outs[i][1] + "  ", options: { bold: true, color: C.text2 } }, { text: outs[i][2] }], { x: M + 0.75, y: y - 0.08, w: 11.3, h: 0.75, fontSize: 14, valign: "middle" }); }

  // 21 ---------- progress
  s = slide("CONTENT", "Progress: about 80 % complete", "Scale and status");
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: M, y: 1.5, w: 12.1, h: 0.32, rectRadius: 0.16, fill: { color: C.background2 }, line: { color: C.background2 } });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: M, y: 1.5, w: 12.1 * 0.8, h: 0.32, rectRadius: 0.16, fill: { color: C.accent2 }, line: { color: C.accent2 } });
  const done = ["Schema, constraints, RLS, trigger, views, functions (20 migrations)", "Eight advanced analytics queries", "Voice pipeline in English, Hindi, Tamil with live switching", "CRM login, transcripts, AI verdict, all through RLS", "Latency cut from 7–16 s to under 2 s", "IEEE paper draft and implementation-code document"];
  const todo = ["Live phone calls (telephony account top-up)", "Monthly partitioning and materialized views", "Stored procedure to close a campaign", "Hosted deployment in Mumbai", "Speech accuracy and naturalness evaluation with external users"];
  tx(s, "Done", { x: M, y: 2.1, w: 5.8, h: 0.4, bold: true, fontSize: 18, color: C.accent2 });
  tx(s, "Next", { x: 6.9, y: 2.1, w: 5.8, h: 0.4, bold: true, fontSize: 18, color: C.accent3 });
  tx(s, done.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < done.length - 1 } })), { x: M, y: 2.65, w: 5.9, h: 4.0, fontSize: 16, paraSpaceAfter: 10 });
  tx(s, todo.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < todo.length - 1 } })), { x: 6.9, y: 2.65, w: 5.8, h: 4.0, fontSize: 16, paraSpaceAfter: 10 });

  // 22 ---------- close
  s = pres.addSlide({ masterName: "SECTION_DARK", sectionTitle: "Scale and status" });
  s.addText("Thank you", { placeholder: "title" });
  s.addText("Live demo next: a call in English, Hindi and Tamil, then the record in the CRM", { placeholder: "body" });
  s.addImage({ data: await icon("LuDatabase", HEX.accent6), x: 11.2, y: 2.6, w: 1.4, h: 1.4 });

  await pres.writeFile({ fileName: path.join(__dirname, OUT) });
  await applyTheme(path.join(__dirname, OUT), THEME);
  console.log("wrote", OUT);
})().catch((e) => { console.error(e); process.exit(1); });
