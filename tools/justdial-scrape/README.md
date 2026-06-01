# JustDial scraper (manual, rate-limited)

> ⚠️ **Read this before running.** Scraping JustDial is against their
> Terms of Service. Use only:
> 1. With explicit operator authorization for a one-off, low-volume sweep.
> 2. From a residential or business IP you control — not a server farm.
> 3. With the rate limit set to **1 request per 3 seconds** (the default
>    here). Do not lower it.
> 4. For collecting publicly listed business contact info only — never
>    personal data, reviews, or anything that needs to be paid for.
>
> JustDial may rotate their HTML, add CAPTCHAs, or block your IP at any
> time. This script makes **no attempt** to defeat those defenses. If it
> stops working, that's the signal to switch to the manual CSV path.

## What it does

Fetches public JustDial business listings for a given `(category, city)`,
respects `robots.txt`, throttles to 1 req / 3 s, and writes a CSV that
matches the columns the Web app's CSV upload expects:

    name,phone,company,industry,source,notes

## Usage

```bash
cd tools/justdial-scrape
npm install
npm run scrape -- --category "Chemical Manufacturers" --city "Chennai" --pages 2 --out leads.csv
```

Then open `/leads` in the Web app and **Upload CSV** → `leads.csv`. The
existing ingest pipeline normalizes phones to E.164 and dedupes against
the tenant's existing leads.

## What it doesn't do

- No proxy rotation, no headless browser, no CAPTCHA solver. Plain
  `fetch` + `cheerio`. If JustDial returns a CAPTCHA page, the script
  exits and tells you.
- No automated cron. Run by hand, when you need it.
- No commits anywhere — the CSV is the only output.

## Fallback

If you get blocked, use Google Places sync (already wired) or paste a
list into the CSV upload UI. Both are zero-risk paths.
