#!/usr/bin/env node
/**
 * JustDial scraper — manual, rate-limited, robots.txt-respecting.
 *
 * READ tools/justdial-scrape/README.md FIRST. This is intentionally
 * minimal: no headless browser, no proxy rotation, no anti-bot tricks.
 * If JustDial blocks the request, the script exits.
 */
import { writeFile } from "node:fs/promises";
import { setTimeout as sleep } from "node:timers/promises";
import { load as loadHtml } from "cheerio";

const RATE_LIMIT_MS = 3000;        // 1 req / 3s — do not lower
const USER_AGENT =
  "Mozilla/5.0 (compatible; SPC-LeadResearch/0.1; one-off-research)";

function parseArgs() {
  const out = { category: "", city: "", pages: 1, file: "leads.csv" };
  const args = process.argv.slice(2);
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a === "--category") out.category = args[++i];
    else if (a === "--city") out.city = args[++i];
    else if (a === "--pages") out.pages = Math.max(1, Math.min(10, Number(args[++i]) || 1));
    else if (a === "--out") out.file = args[++i];
  }
  if (!out.category || !out.city) {
    console.error("usage: --category <text> --city <text> [--pages 1-10] [--out leads.csv]");
    process.exit(2);
  }
  return out;
}

async function checkRobots(host) {
  try {
    const res = await fetch(`https://${host}/robots.txt`, {
      headers: { "user-agent": USER_AGENT },
    });
    if (!res.ok) return { allowed: true, note: `robots fetch ${res.status}` };
    const body = await res.text();
    // Tiny robots parser — look for blanket Disallow under User-agent: *
    const blocks = body.split(/\n\s*\n/);
    for (const b of blocks) {
      const lines = b.split("\n").map((l) => l.split("#")[0].trim()).filter(Boolean);
      const uas = lines.filter((l) => l.toLowerCase().startsWith("user-agent:")).map((l) =>
        l.split(":")[1].trim(),
      );
      if (!uas.includes("*")) continue;
      const dis = lines
        .filter((l) => l.toLowerCase().startsWith("disallow:"))
        .map((l) => l.split(":").slice(1).join(":").trim());
      if (dis.includes("/")) return { allowed: false, note: "robots disallows /" };
    }
    return { allowed: true, note: "ok" };
  } catch (e) {
    return { allowed: true, note: `robots fetch threw: ${e.message}` };
  }
}

function slug(s) {
  return s.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-");
}

function listingUrl({ category, city, page }) {
  const c = slug(city);
  const k = slug(category);
  // JustDial public listing URL pattern. They rotate this — if it breaks,
  // open one listing in a browser, copy the URL shape, and update here.
  const base = `https://www.justdial.com/${c}/${k}`;
  return page === 1 ? base : `${base}/page-${page}`;
}

function extractListings(html) {
  const $ = loadHtml(html);
  const items = [];

  if (
    /captcha/i.test(html) ||
    /verify you are human/i.test(html) ||
    /access denied/i.test(html)
  ) {
    return { blocked: true, items: [] };
  }

  $("[data-href], .resultbox, .cntanr, .store-details").each((_, el) => {
    const $el = $(el);
    const name = (
      $el.find(".lng_cont_name, .resultbox_title_anchor, h2").first().text() ||
      $el.find("h3, h4").first().text()
    ).trim();

    const phone = (
      $el.find("[data-href*='callto:'], a[href*='tel:']").attr("href") ||
      $el.find("p.contact-info, span.callcontent, .callNowAnchor").first().text() ||
      ""
    ).replace(/^.*?(tel:|callto:)/i, "").trim();

    const address = $el.find(".cont_sw_addr, .resultbox_address, .address").first().text().trim();

    if (name && /[0-9]/.test(phone)) {
      items.push({
        name: name.replace(/\s+/g, " ").slice(0, 200),
        phone: phone.replace(/[^\d+]/g, ""),
        address: address.replace(/\s+/g, " ").slice(0, 300),
      });
    }
  });

  return { blocked: false, items };
}

function csvCell(s) {
  const v = (s ?? "").toString();
  if (/[",\n]/.test(v)) return `"${v.replace(/"/g, '""')}"`;
  return v;
}

async function main() {
  const { category, city, pages, file } = parseArgs();
  console.log(`[justdial] sweep: ${category} in ${city}, pages 1..${pages}`);

  const robots = await checkRobots("www.justdial.com");
  if (!robots.allowed) {
    console.error(`[justdial] robots.txt disallows scraping: ${robots.note}`);
    console.error("[justdial] aborting. Use Google Places sync or manual CSV instead.");
    process.exit(3);
  }
  console.log(`[justdial] robots check: ${robots.note}`);

  const collected = [];
  const seen = new Set();
  let blocked = false;

  for (let p = 1; p <= pages; p++) {
    if (p > 1) await sleep(RATE_LIMIT_MS);
    const url = listingUrl({ category, city, page: p });
    console.log(`[justdial] GET ${url}`);
    let html;
    try {
      const res = await fetch(url, {
        headers: {
          "user-agent": USER_AGENT,
          accept: "text/html,application/xhtml+xml",
          "accept-language": "en-IN,en;q=0.9",
        },
      });
      if (res.status === 429 || res.status === 403) {
        console.error(`[justdial] HTTP ${res.status} — likely blocked, stopping.`);
        blocked = true;
        break;
      }
      if (!res.ok) {
        console.error(`[justdial] HTTP ${res.status}, stopping.`);
        break;
      }
      html = await res.text();
    } catch (e) {
      console.error(`[justdial] fetch failed: ${e.message}`);
      break;
    }

    const { blocked: capt, items } = extractListings(html);
    if (capt) {
      console.error("[justdial] CAPTCHA / bot challenge page returned. Stopping.");
      blocked = true;
      break;
    }
    console.log(`[justdial] page ${p}: ${items.length} listings`);
    for (const it of items) {
      if (seen.has(it.phone)) continue;
      seen.add(it.phone);
      collected.push(it);
    }
  }

  if (blocked) {
    console.error("[justdial] Use Google Places sync or paste a list into the CSV upload.");
  }

  const header = "name,phone,company,industry,source,notes\n";
  const lines = collected.map((it) =>
    [
      csvCell(it.name),
      csvCell(it.phone),
      csvCell(it.name),
      csvCell(category),
      csvCell("justdial"),
      csvCell(`${city} · ${it.address}`),
    ].join(","),
  );
  await writeFile(file, header + lines.join("\n") + "\n", "utf8");
  console.log(`[justdial] wrote ${collected.length} rows → ${file}`);
}

main().catch((e) => {
  console.error(`[justdial] fatal: ${e.stack ?? e.message}`);
  process.exit(1);
});
