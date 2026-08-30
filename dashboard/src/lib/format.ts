import type { AnalysisResult } from "./api";

export function formatMetricValue(result: AnalysisResult): string {
  if (result.value === null) return "—";
  switch (result.metric_type) {
    case "trend":
      return `${result.value >= 0 ? "+" : ""}${(result.value * 100).toFixed(1)}%`;
    case "volatility":
      return `${(result.value * 100).toFixed(1)}% rel. std dev`;
    case "arbitrage":
      return `$${result.value.toFixed(2)} net gap`;
    case "underpriced_listing":
      return `${(result.value * 100).toFixed(1)}% below avg`;
    default:
      return String(result.value);
  }
}

export function formatPrice(value: number | null): string {
  return value === null ? "—" : `$${value.toFixed(2)}`;
}
