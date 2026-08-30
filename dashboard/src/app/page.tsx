import { AnalysisResultsTable } from "@/components/AnalysisResultsTable";
import { FreshnessBanner } from "@/components/FreshnessBanner";
import { SkinBrowser } from "@/components/SkinBrowser";
import { getAnalysis, getFreshness, getSkins } from "@/lib/api";

// Without this, Next prerenders "/" once at build time (baking in whatever
// the fetches returned then — even the API-unreachable error state, since
// the build environment has no FastAPI running) instead of refetching per
// request. Confirmed against this project's installed Next docs
// (node_modules/next/dist/docs/01-app/02-guides/caching-without-cache-components.md)
// rather than assumed from general Next.js knowledge, since this version's
// AGENTS.md warns the App Router has changed since most training data.
export const dynamic = "force-dynamic";

// Server-fetch initial load (skins, freshness, analysis results); the skin
// browser's float-range sub-filter re-fetches client-side (plan Section 7).
export default async function Home() {
  let skins, freshness, arbitrage, underpriced, trend;
  try {
    [skins, freshness, arbitrage, underpriced, trend] = await Promise.all([
      getSkins(),
      getFreshness(),
      getAnalysis({ metric_type: "arbitrage", limit: 20 }),
      getAnalysis({ metric_type: "underpriced_listing", limit: 20 }),
      getAnalysis({ metric_type: "trend", window_days: 7, limit: 20 }),
    ]);
  } catch {
    return (
      <div className="mx-auto max-w-2xl px-6 py-10">
        <p className="rounded-md border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          Couldn&apos;t reach the API. Is it running? (<code>uv run uvicorn api.main:app --reload</code>)
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-8 px-6 py-10">
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold">CS2 Market Analysis</h1>
        <FreshnessBanner freshness={freshness} />
      </header>

      <SkinBrowser skins={skins} />

      <AnalysisResultsTable results={arbitrage} title="Cross-marketplace arbitrage" honestyLabel="opportunity" />
      <AnalysisResultsTable results={underpriced} title="Underpriced listings" honestyLabel="opportunity" />
      <AnalysisResultsTable results={trend} title="7-day trend" honestyLabel="trend, not a forecast" />
    </div>
  );
}
