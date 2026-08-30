"use client";

import { useMemo, useState } from "react";
import { clientApiUrl, type Listing, type Skin } from "@/lib/api";
import { formatPrice } from "@/lib/format";

// Browse/filter UX (plan Section 2): pick a skin + wear category (server-fetched
// initial `skins` list), then sub-filter by an arbitrary float range — this
// second step is client-fetched, hitting /listings directly from the browser.
export function SkinBrowser({ skins }: { skins: Skin[] }) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Skin | null>(null);
  const [floatMin, setFloatMin] = useState("");
  const [floatMax, setFloatMax] = useState("");
  const [listings, setListings] = useState<Listing[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const filteredSkins = useMemo(() => {
    if (!query) return skins;
    const q = query.toLowerCase();
    return skins.filter((s) => s.weapon.toLowerCase().includes(q) || s.skin_name.toLowerCase().includes(q));
  }, [skins, query]);

  async function loadListings(skin: Skin, min: string, max: string) {
    setLoading(true);
    setError(null);
    try {
      const url = new URL(clientApiUrl("/listings"));
      url.searchParams.set("weapon", skin.weapon);
      url.searchParams.set("skin_name", skin.skin_name);
      url.searchParams.set("wear_category", skin.wear_category);
      if (min) url.searchParams.set("float_min", min);
      if (max) url.searchParams.set("float_max", max);
      const res = await fetch(url);
      if (!res.ok) throw new Error(`request failed: ${res.status}`);
      setListings(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to load listings");
    } finally {
      setLoading(false);
    }
  }

  function selectSkin(skin: Skin) {
    setSelected(skin);
    setFloatMin("");
    setFloatMax("");
    void loadListings(skin, "", "");
  }

  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-lg font-semibold">Browse listings</h2>
      <input
        type="text"
        placeholder="Search weapon or skin (e.g. AK-47, Redline)"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        className="rounded border border-zinc-300 bg-transparent px-3 py-1.5 text-sm dark:border-zinc-700"
      />
      <div className="flex gap-4">
        <ul className="flex max-h-80 w-72 flex-col overflow-y-auto rounded border border-zinc-200 text-sm dark:border-zinc-800">
          {filteredSkins.map((s) => {
            const isSelected =
              selected &&
              selected.weapon === s.weapon &&
              selected.skin_name === s.skin_name &&
              selected.wear_category === s.wear_category;
            return (
              <li key={`${s.weapon}-${s.skin_name}-${s.wear_category}`}>
                <button
                  onClick={() => selectSkin(s)}
                  className={`w-full px-3 py-1.5 text-left hover:bg-zinc-100 dark:hover:bg-zinc-800 ${
                    isSelected ? "bg-zinc-100 font-medium dark:bg-zinc-800" : ""
                  }`}
                >
                  {s.weapon} | {s.skin_name} <span className="text-zinc-400">({s.wear_category})</span>
                  <span className="float-right text-zinc-400">{s.active_listing_count}</span>
                </button>
              </li>
            );
          })}
          {filteredSkins.length === 0 && <li className="px-3 py-2 text-zinc-400">No matches</li>}
        </ul>

        <div className="flex flex-1 flex-col gap-2">
          {selected ? (
            <>
              <div className="flex items-center gap-2 text-sm">
                <label>
                  Float min
                  <input
                    type="number"
                    step="0.001"
                    min={0}
                    max={1}
                    value={floatMin}
                    onChange={(e) => setFloatMin(e.target.value)}
                    className="ml-1 w-20 rounded border border-zinc-300 bg-transparent px-1.5 py-0.5 dark:border-zinc-700"
                  />
                </label>
                <label>
                  Float max
                  <input
                    type="number"
                    step="0.001"
                    min={0}
                    max={1}
                    value={floatMax}
                    onChange={(e) => setFloatMax(e.target.value)}
                    className="ml-1 w-20 rounded border border-zinc-300 bg-transparent px-1.5 py-0.5 dark:border-zinc-700"
                  />
                </label>
                <button
                  onClick={() => void loadListings(selected, floatMin, floatMax)}
                  className="rounded bg-zinc-900 px-3 py-1 text-white dark:bg-zinc-100 dark:text-zinc-900"
                >
                  Apply
                </button>
              </div>

              {loading && <p className="text-sm text-zinc-500">Loading…</p>}
              {error && <p className="text-sm text-red-600">{error}</p>}
              {!loading && !error && (
                <table className="w-full text-sm">
                  <thead className="text-left text-zinc-500">
                    <tr>
                      <th className="py-1 pr-4">Marketplace</th>
                      <th className="py-1 pr-4">Float</th>
                      <th className="py-1 pr-4">Price</th>
                      <th className="py-1">Buy order</th>
                    </tr>
                  </thead>
                  <tbody>
                    {listings.map((l) => (
                      <tr key={`${l.marketplace}-${l.listing_id}`} className="border-t border-zinc-100 dark:border-zinc-800">
                        <td className="py-1.5 pr-4 capitalize">{l.marketplace}</td>
                        <td className="py-1.5 pr-4">{l.float_value?.toFixed(4) ?? "—"}</td>
                        <td className="py-1.5 pr-4 font-medium">{formatPrice(l.listing_price)}</td>
                        <td className="py-1.5">{formatPrice(l.buy_order_price)}</td>
                      </tr>
                    ))}
                    {listings.length === 0 && (
                      <tr>
                        <td colSpan={4} className="py-2 text-zinc-400">
                          No listings in this range.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              )}
            </>
          ) : (
            <p className="text-sm text-zinc-500">Select a skin to see current listings.</p>
          )}
        </div>
      </div>
    </section>
  );
}
