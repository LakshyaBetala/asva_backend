/**
 * Named lead-source presets. Each preset is an (industries × locations) bundle
 * the dashboard exposes as a single click, so Laksh doesn't have to retype the
 * same broker query strings every morning.
 *
 * Presets call `fetchPlacesLeads` under the hood — see ./sources/places.ts.
 */

export type LeadPreset = {
  id: string;
  label: string;
  description: string;
  industries: string[];
  locations: string[];
  /** Rough Places API call count = industries.length * locations.length. */
  estimatedQueries?: number;
};

/**
 * North-India real-estate brokers. Tuned for the Almmatix self-sales push:
 * Priya rings each broker and pitches them on hiring Priya.
 *
 * Locations chosen for high broker density + English/Hindi mix Priya handles
 * cleanly. Pin codes are deliberately a mix of new-construction belts
 * (Gurgaon Sector 88, Noida 150) and resale belts (Lajpat Nagar, Karol Bagh)
 * so the cohort isn't single-segment.
 */
export const NORTH_INDIA_BROKER_PRESET: LeadPreset = {
  id: "north-india-brokers",
  label: "North India real-estate brokers",
  description:
    "Property dealers + real-estate agencies across Delhi NCR, Punjab, UP — feed for almmatix-self-tenant voice agent.",
  industries: [
    "real estate agent",
    "property dealer",
    "real estate consultant",
    "real estate broker",
  ],
  locations: [
    // Delhi NCR
    "Gurgaon, Haryana",
    "Sector 56 Gurgaon",
    "DLF Phase 4 Gurgaon",
    "Sohna Road Gurgaon",
    "Noida, Uttar Pradesh",
    "Sector 18 Noida",
    "Greater Noida, Uttar Pradesh",
    "Dwarka, New Delhi",
    "Saket, New Delhi",
    "Vasant Kunj, New Delhi",
    "Karol Bagh, New Delhi",
    "Lajpat Nagar, New Delhi",
    "Rohini, New Delhi",
    "Faridabad, Haryana",
    "Ghaziabad, Uttar Pradesh",
    // Tri-city
    "Chandigarh",
    "Mohali, Punjab",
    "Panchkula, Haryana",
    // Tier-2 north
    "Lucknow, Uttar Pradesh",
    "Gomti Nagar Lucknow",
    "Jaipur, Rajasthan",
    "Mansarovar Jaipur",
  ],
};

/**
 * South/West real-estate brokers — feeds the demo-broker-tenant
 * (the realty-services product, not the self-sales pitch).
 */
export const SOUTH_WEST_BROKER_PRESET: LeadPreset = {
  id: "south-west-brokers",
  label: "Mumbai / Bangalore / Pune / Hyderabad brokers",
  description:
    "Property dealers across Mumbai, Bangalore, Pune, Hyderabad — feed for demo-broker-tenant (real-estate brain).",
  industries: ["real estate agent", "property dealer", "real estate broker"],
  locations: [
    "Bandra West Mumbai",
    "Andheri West Mumbai",
    "Powai Mumbai",
    "Lower Parel Mumbai",
    "Goregaon Mumbai",
    "Thane Mumbai",
    "Koregaon Park Pune",
    "Hinjewadi Pune",
    "Wakad Pune",
    "Kharadi Pune",
    "Koramangala Bangalore",
    "Indiranagar Bangalore",
    "Whitefield Bangalore",
    "HSR Layout Bangalore",
    "Sarjapur Road Bangalore",
    "Banjara Hills Hyderabad",
    "Madhapur Hyderabad",
    "Gachibowli Hyderabad",
    "Kondapur Hyderabad",
  ],
};

export const ALL_PRESETS: LeadPreset[] = [
  NORTH_INDIA_BROKER_PRESET,
  SOUTH_WEST_BROKER_PRESET,
];

export function getPreset(id: string): LeadPreset | undefined {
  return ALL_PRESETS.find((p) => p.id === id);
}
