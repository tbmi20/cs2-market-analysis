// Shared types + fetch helpers for the FastAPI backend (api/main.py).
// Server Components import these directly; Client Components should prefer
// clientApiUrl() below since API_BASE_URL isn't visible to the browser.

export type Skin = {
  weapon: string;
  skin_name: string;
  wear_category: string;
  active_listing_count: number;
};

export type Listing = {
  marketplace: string;
  listing_id: string;
  weapon: string;
  skin_name: string;
  wear_category: string;
  float_bucket: string;
  float_value: number | null;
  listing_price: number | null;
  buy_order_price: number | null;
  last_updated: string;
};

export type AnalysisResult = {
  id: number;
  skin_variant_id: number;
  weapon: string;
  skin_name: string;
  wear_category: string;
  float_bucket: string;
  metric_type: "trend" | "volatility" | "arbitrage" | "underpriced_listing";
  window_days: number | null;
  value: number | null;
  sample_count: number;
  confidence_tier: "low" | "medium" | "high";
  computed_at: string;
  details: Record<string, unknown> | null;
  suppressed: boolean;
};

export type Freshness = {
  marketplace: string;
  last_successful_poll: string | null;
  last_status: string | null;
  last_records_ingested: number | null;
};

// Server-side only (Server Components, route handlers) — reaches the API
// through whatever network path the Next.js server process itself has.
function serverApiUrl(path: string): string {
  const base = process.env.API_BASE_URL ?? "http://localhost:8000";
  return `${base}${path}`;
}

// Safe to call from Client Components ('use client') — NEXT_PUBLIC_* vars
// are inlined into the browser bundle at build time.
export function clientApiUrl(path: string): string {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
  return `${base}${path}`;
}

export async function getSkins(q?: string): Promise<Skin[]> {
  const url = new URL(serverApiUrl("/skins"));
  if (q) url.searchParams.set("q", q);
  const res = await fetch(url);
  if (!res.ok) throw new Error(`GET /skins failed: ${res.status}`);
  return res.json();
}

export async function getFreshness(): Promise<Freshness[]> {
  const res = await fetch(serverApiUrl("/freshness"));
  if (!res.ok) throw new Error(`GET /freshness failed: ${res.status}`);
  return res.json();
}

export async function getAnalysis(params: {
  metric_type: AnalysisResult["metric_type"];
  window_days?: number;
  limit?: number;
}): Promise<AnalysisResult[]> {
  const url = new URL(serverApiUrl("/analysis"));
  url.searchParams.set("metric_type", params.metric_type);
  if (params.window_days !== undefined) url.searchParams.set("window_days", String(params.window_days));
  if (params.limit !== undefined) url.searchParams.set("limit", String(params.limit));
  const res = await fetch(url);
  if (!res.ok) throw new Error(`GET /analysis failed: ${res.status}`);
  return res.json();
}
