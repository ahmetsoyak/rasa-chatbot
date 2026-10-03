/**
 * ============================================================================
 * CUSTOM PAYLOAD CONTRACTS, mirroring `dispatcher.utter_message(json_message=...)`
 * calls in `actions/actions.py`. Every field is optional and read defensively
 * (runtime checks in the components), so a missing or mismatched field
 * degrades to less detail instead of crashing. Each action also sends a
 * plain-text version of the same content for text-only channels.
 * ============================================================================
 *
 * type                    sent by
 * ----------------------  -----------------------------------------------
 * carbon_card             action_calculate_carbon_footprint
 * hotel_carousel          action_search_accommodations
 * transport_options       action_search_transport
 * experience_list         action_search_cultural_experiences
 * weather_card            action_get_weather
 * offset_info             action_carbon_offset_info
 * recommendation_summary  action_rank_recommendations (data only, not rendered)
 * handover_notice         action_human_handover
 */

/** Emission-severity band. Transport bands are by intensity (g CO2e per passenger-km). */
export type CarbonBand = "green" | "amber" | "red";

export function isBand(value: unknown): value is CarbonBand {
  return value === "green" || value === "amber" || value === "red";
}

/** One travel mode in the carbon comparison. */
export interface CarbonOption {
  mode?: string;
  kg_co2e?: number;
  band?: CarbonBand;
  intensity_g_per_pkm?: number;
}

export interface CarbonScoreCardPayload {
  type: "carbon_card";
  /** Label of the headline mode (the one the user asked about, or the best one). */
  mode?: string;
  kg_co2e?: number;
  band?: CarbonBand;
  distance_km?: number;
  /** e.g. "Berlin to Lisbon" or "an example 500 km trip". */
  route?: string;
  /** True when no origin was known and an example distance was used. */
  is_example?: boolean;
  /** "Climatiq API (DESNZ 2026 factors)" or "DESNZ 2026 factors (local table)". */
  source?: string;
  summary?: string;
  /** Present only when the headline mode is red. */
  alert?: string | null;
  /** Plain-language explanation of kg CO2e and the colour bands. */
  tooltip?: string;
  /** All compared modes, lowest emissions first. */
  options?: CarbonOption[];
}

/**
 * `verification` is how much the sustainability claim can be trusted:
 *  - "none": OpenStreetMap place with no eco tag (only proxies)
 *  - "unverified_osm_tag": OSM carries a user-edited eco tag
 *  - "sample_data": illustrative entry from the curated sample set
 */
export type Verification = "none" | "unverified_osm_tag" | "sample_data";

export interface EcoHotel {
  name?: string;
  type?: string;
  /** Only ever set for illustrative sample data. */
  eco_certification?: string | null;
  /** Raw OSM tag value when verification is "unverified_osm_tag". */
  eco_tag?: string | null;
  verification?: Verification;
  /** Observable indicators, e.g. "180 m from tram (Rossio)". */
  proxies?: string[];
  price_per_night?: number;
  currency?: string;
  price_band?: string;
  price_is_estimate?: boolean;
  kg_co2e_per_night?: number;
  carbon_is_estimate?: boolean;
  band?: CarbonBand;
  within_budget?: boolean;
  wheelchair?: string | null;
  description?: string;
  booking_url?: string | null;
  data_source?: string;
}

export interface HotelCarouselPayload {
  type: "hotel_carousel";
  destination?: string;
  data_source?: string;
  note?: string;
  hotels?: EcoHotel[];
}

export interface TransportRoute {
  mode?: string;
  route?: string;
  kg_co2e?: number;
  band?: CarbonBand;
  price?: number;
  currency?: string;
  duration_hours?: number;
  score?: number;
}

export interface TransportOptionsPayload {
  type: "transport_options";
  destination?: string;
  local_transit?: { counts?: Record<string, number>; radius_km?: number; source?: string };
  routes?: TransportRoute[];
  routes_note?: string;
}

export interface Experience {
  name?: string;
  kind?: string;
  description?: string;
  supports_local_community?: boolean;
  price?: number;
  currency?: string;
  wheelchair?: string | null;
  data_source?: string;
}

export interface ExperienceListPayload {
  type: "experience_list";
  destination?: string;
  items?: Experience[];
}

export interface WeatherDay {
  date?: string;
  summary?: string;
  t_max?: number;
  t_min?: number;
  rain_chance?: number | null;
}

export interface WeatherCardPayload {
  type: "weather_card";
  destination?: string;
  current?: { temp?: number; summary?: string; wind_kmh?: number };
  days?: WeatherDay[];
  tip?: string;
  source?: string;
}

export interface OffsetStandard {
  name?: string;
  type?: string;
  registry_url?: string;
  notes?: string;
}

export interface OffsetInfoPayload {
  type: "offset_info";
  standards?: OffsetStandard[];
  principles?: string[];
  return_trip_tonnes?: number;
  indicative_cost_eur?: { low?: number; high?: number; per_tonne_low?: number; per_tonne_high?: number };
  /** Set when the user's chosen mode isn't the lowest-carbon one. */
  lower_carbon_alternative?: string;
}

export interface HandoverNoticePayload {
  type: "handover_notice";
  reason?: string;
  ticket_id?: string;
  summary?: string;
  message?: string;
  context?: {
    trip?: Record<string, string | number | null | undefined>;
    transcript_turns?: number;
    privacy?: string;
  };
}

/** Payload types rendered as cards. The plain-text message an action sends
 *  right after one of these repeats the card for text-only channels. */
export const RICH_TYPES = new Set([
  "carbon_card", "hotel_carousel", "transport_options", "experience_list", "weather_card", "offset_info", "handover_notice",
]);

export type CustomPayload =
  | CarbonScoreCardPayload
  | HotelCarouselPayload
  | TransportOptionsPayload
  | ExperienceListPayload
  | WeatherCardPayload
  | OffsetInfoPayload
  | HandoverNoticePayload
  | { type?: string; [key: string]: unknown };

/** Narrow an unknown custom payload object to a specific `type` discriminant. */
export function payloadIs<T extends { type?: string }>(
  payload: unknown,
  type: string,
): payload is T {
  return (
    typeof payload === "object" &&
    payload !== null &&
    (payload as { type?: unknown }).type === type
  );
}

/** Array.isArray narrowed to T[], tolerating undefined/null. */
export function asArray<T>(value: T[] | undefined | null): T[] {
  return Array.isArray(value) ? value : [];
}

/** Format a number with at most `digits` fraction digits, or a dash. */
export function fmt(value: unknown, digits = 0): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString(undefined, { maximumFractionDigits: digits })
    : "–";
}
