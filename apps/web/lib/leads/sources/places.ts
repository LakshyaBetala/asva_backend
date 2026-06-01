import type { LeadCandidate } from "../ingest";

const SEARCH_URL = "https://places.googleapis.com/v1/places:searchText";

const FIELD_MASK = [
  "places.id",
  "places.displayName",
  "places.formattedAddress",
  "places.internationalPhoneNumber",
  "places.nationalPhoneNumber",
  "places.types",
  "places.primaryType",
].join(",");

type PlaceResult = {
  id: string;
  displayName?: { text?: string };
  formattedAddress?: string;
  internationalPhoneNumber?: string;
  nationalPhoneNumber?: string;
  types?: string[];
  primaryType?: string;
};

export type PlacesFetchResult = {
  candidates: LeadCandidate[];
  queries: number;
  errors: string[];
};

async function searchOne(
  query: string,
  apiKey: string,
  signal?: AbortSignal,
): Promise<PlaceResult[]> {
  // Places API New supports pageToken for up to 60 results (3 pages of 20).
  // Each page costs the same as one search, but yields 3x the leads per
  // industry/locality pair — important for cities like Chennai where 20
  // results barely cover one sub-locality.
  const FIELD_MASK_WITH_TOKEN = `${FIELD_MASK},nextPageToken`;
  const collected: PlaceResult[] = [];
  let pageToken: string | undefined;
  for (let page = 0; page < 3; page++) {
    const body: Record<string, unknown> = {
      textQuery: query,
      pageSize: 20,
      regionCode: "IN",
      languageCode: "en",
    };
    if (pageToken) body.pageToken = pageToken;
    const res = await fetch(SEARCH_URL, {
      method: "POST",
      signal,
      headers: {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": apiKey,
        "X-Goog-FieldMask": FIELD_MASK_WITH_TOKEN,
      },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const detail = await res.text().catch(() => "");
      throw new Error(`places ${res.status}: ${detail.slice(0, 200)}`);
    }
    const json = (await res.json()) as {
      places?: PlaceResult[];
      nextPageToken?: string;
    };
    if (json.places) collected.push(...json.places);
    if (!json.nextPageToken) break;
    pageToken = json.nextPageToken;
    // Google requires a short delay before the page-token request is honored.
    await new Promise((r) => setTimeout(r, 1500));
  }
  return collected;
}

/**
 * Run textsearch across every (industry × location) combination and return
 * de-duplicated lead candidates that have a phone number attached. Returns an
 * empty result if GOOGLE_PLACES_API_KEY is unset so callers can degrade
 * gracefully instead of crashing.
 */
export async function fetchPlacesLeads(opts: {
  industries: string[];
  locations: string[];
  maxQueries?: number;
}): Promise<PlacesFetchResult> {
  const apiKey = process.env.GOOGLE_PLACES_API_KEY;
  if (!apiKey) {
    return {
      candidates: [],
      queries: 0,
      errors: ["GOOGLE_PLACES_API_KEY not set"],
    };
  }

  const industries = opts.industries.filter((s) => s.trim());
  const locations = opts.locations.filter((s) => s.trim());
  if (industries.length === 0 || locations.length === 0) {
    return { candidates: [], queries: 0, errors: ["no industries or locations configured"] };
  }

  const maxQueries = opts.maxQueries ?? 60;
  const pairs: { industry: string; location: string }[] = [];
  for (const ind of industries) {
    for (const loc of locations) {
      pairs.push({ industry: ind, location: loc });
    }
  }
  const limited = pairs.slice(0, maxQueries);

  const seen = new Set<string>();
  const seenPhone = new Set<string>();
  const candidates: LeadCandidate[] = [];
  const errors: string[] = [];

  for (const p of limited) {
    const query = `${p.industry} in ${p.location}`;
    try {
      const places = await searchOne(query, apiKey);
      for (const pl of places) {
        if (seen.has(pl.id)) continue;
        seen.add(pl.id);
        const phone = pl.internationalPhoneNumber ?? pl.nationalPhoneNumber;
        if (!phone) continue;
        const normPhone = phone.replace(/[^\d+]/g, "");
        if (seenPhone.has(normPhone)) continue;
        seenPhone.add(normPhone);
        const name = pl.displayName?.text;
        if (!name) continue;
        candidates.push({
          name,
          phone,
          company: name,
          industry: p.industry,
          source: "google_places",
          notes: pl.formattedAddress ?? null,
        });
      }
    } catch (e) {
      errors.push(`${query}: ${(e as Error).message}`);
    }
  }

  return { candidates, queries: limited.length, errors };
}
