import { parsePhoneNumberFromString, type CountryCode } from "libphonenumber-js";

export function toE164(
  raw: string,
  opts: { defaultRegion?: CountryCode } = {}
): string {
  const region = opts.defaultRegion ?? "IN";
  const cleaned = raw.replace(/[\s\-()]/g, "");
  const parsed = parsePhoneNumberFromString(cleaned, region);
  if (!parsed || !parsed.isValid()) {
    throw new Error(`invalid phone number: ${raw}`);
  }
  return parsed.number;
}
