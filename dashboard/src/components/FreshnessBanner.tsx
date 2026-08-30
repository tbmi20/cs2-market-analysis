import type { Freshness } from "@/lib/api";

// Honesty framing (plan Section 6): a stale/failing poll should be visible,
// not silently presented as current.
function relativeAge(iso: string | null): string {
  if (!iso) return "never";
  const ms = Date.now() - new Date(iso).getTime();
  const minutes = Math.round(ms / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function FreshnessBanner({ freshness }: { freshness: Freshness[] }) {
  if (freshness.length === 0) {
    return (
      <div className="rounded-md border border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200">
        No ingestion data yet.
      </div>
    );
  }

  return (
    <div className="flex flex-wrap gap-3 text-sm">
      {freshness.map((f) => {
        const stale = f.last_status !== "success";
        return (
          <div
            key={f.marketplace}
            className={`rounded-md border px-3 py-1.5 ${
              stale
                ? "border-red-300 bg-red-50 text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200"
                : "border-zinc-200 bg-zinc-50 text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300"
            }`}
          >
            <span className="font-medium capitalize">{f.marketplace}</span>
            {": "}
            {stale ? `last poll ${f.last_status ?? "unknown"}` : `updated ${relativeAge(f.last_successful_poll)}`}
          </div>
        );
      })}
    </div>
  );
}
