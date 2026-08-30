import type { AnalysisResult } from "@/lib/api";
import { formatMetricValue } from "@/lib/format";

const TIER_STYLES: Record<AnalysisResult["confidence_tier"], string> = {
  high: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  medium: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  low: "bg-zinc-200 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
};

// Shared table for every metric_type. `honestyLabel` is the plan's honesty
// framing (Section 6) rendered right next to the title — "opportunity" for
// arbitrage/underpriced_listing, "trend, not a forecast" for trend/volatility
// — so the confidence class is visible at a glance, not just in the data.
export function AnalysisResultsTable({
  results,
  title,
  honestyLabel,
}: {
  results: AnalysisResult[];
  title: string;
  honestyLabel: string;
}) {
  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-baseline gap-2">
        <h2 className="text-lg font-semibold">{title}</h2>
        <span className="text-xs uppercase tracking-wide text-zinc-500">{honestyLabel}</span>
      </div>
      {results.length === 0 ? (
        <p className="text-sm text-zinc-500">Nothing to show yet.</p>
      ) : (
        <table className="w-full text-sm">
          <thead className="text-left text-zinc-500">
            <tr>
              <th className="py-1 pr-4">Skin</th>
              <th className="py-1 pr-4">Value</th>
              <th className="py-1 pr-4">Confidence</th>
              <th className="py-1">Sample</th>
            </tr>
          </thead>
          <tbody>
            {results.map((r) => (
              <tr
                key={`${r.skin_variant_id}-${r.metric_type}-${r.window_days ?? "now"}`}
                className="border-t border-zinc-100 dark:border-zinc-800"
              >
                <td className="py-1.5 pr-4">
                  {r.weapon} | {r.skin_name} <span className="text-zinc-400">({r.wear_category})</span>
                </td>
                <td className="py-1.5 pr-4 font-medium">
                  {r.suppressed ? <span className="text-zinc-400 italic">not enough data</span> : formatMetricValue(r)}
                </td>
                <td className="py-1.5 pr-4">
                  <span className={`rounded px-1.5 py-0.5 text-xs ${TIER_STYLES[r.confidence_tier]}`}>{r.confidence_tier}</span>
                </td>
                <td className="py-1.5 text-zinc-500">n={r.sample_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
