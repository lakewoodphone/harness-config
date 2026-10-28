"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

type Ev = { occurred_at?: string; entity_id?: string; new_state?: string; door_id?: string | null; area?: string | null };
type Entry = { occurred_at?: string; door_id?: string; system?: string; slot?: string | null; subject_id?: string | null; confidence?: number };
type Dec = { created_at?: string; rule_id?: string; decision?: string; avs_level?: number; confidence?: number; reason_one_line?: string };
type Pic = { captured_at?: string; camera_id?: string; door_id?: string | null; sha256?: string; bytes?: number; osd_offset_s?: number; result?: string; image_url?: string | null };

type Day = {
  day?: string;
  declared_state?: { state?: string; declared_at?: string } | null;
  counts?: { events?: number; entries?: number; decisions?: number; evidence?: number };
  events?: Ev[];
  entries?: Entry[];
  decisions?: Dec[];
  evidence?: Pic[];
  error?: string;
};

type Row = { t: string; kind: "door" | "credential" | "verdict" | "picture"; title: string; detail?: string; image?: string | null; tone: string };

function clock(iso?: string) {
  if (!iso) return "--:--";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "--:--" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function today() {
  return new Date().toLocaleDateString("en-CA");
}

export function ShopClient() {
  const [day, setDay] = useState<string>(today());
  const [data, setData] = useState<Day | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (d: string) => {
    setBusy(true);
    try {
      const r = await fetch(`/api/shop?day=${encodeURIComponent(d)}`, { cache: "no-store" });
      setData(await r.json());
    } catch {
      setData({ error: "could not reach the shop record" });
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void load(day);
  }, [day, load]);

  const rows = useMemo<Row[]>(() => {
    if (!data) return [];
    const out: Row[] = [];
    for (const e of data.events || []) {
      const name = (e.area || e.entity_id || "").replace(/^binary_sensor\./, "").replace(/_/g, " ");
      const isDoor = (e.entity_id || "").includes("door");
      out.push({
        t: e.occurred_at || "",
        kind: isDoor ? "door" : "door",
        title: `${name} → ${e.new_state || "?"}`,
        detail: e.door_id ? `door: ${e.door_id}` : undefined,
        tone: isDoor && e.new_state === "on" ? "text-amber-600 dark:text-amber-400" : "text-zinc-500",
      });
    }
    for (const c of data.entries || []) {
      out.push({
        t: c.occurred_at || "",
        kind: "credential",
        title: `${c.door_id || "door"} keypad${c.subject_id ? ` — ${c.subject_id}` : " — no one recognised"}`,
        detail: `${c.system || ""}${c.slot ? ` slot ${c.slot}` : ""} confidence ${c.confidence ?? 0}`,
        tone: c.subject_id ? "text-emerald-600 dark:text-emerald-400" : "text-amber-600 dark:text-amber-400",
      });
    }
    for (const d of data.decisions || []) {
      out.push({
        t: d.created_at || "",
        kind: "verdict",
        title: `${d.decision || "?"} · level ${d.avs_level ?? "?"} · ${d.rule_id || ""}`,
        detail: d.reason_one_line || undefined,
        tone: (d.avs_level ?? 0) >= 3 ? "text-red-600 dark:text-red-400" : "text-zinc-500",
      });
    }
    for (const p of data.evidence || []) {
      out.push({
        t: p.captured_at || "",
        kind: "picture",
        title: p.camera_id || "camera",
        detail: p.result === "ok" ? `${Math.round((p.bytes || 0) / 1024)} KB${p.osd_offset_s != null ? ` · stamp ${p.osd_offset_s}s behind` : ""}` : `capture failed: ${p.result}`,
        image: p.image_url || null,
        tone: p.result === "ok" ? "text-sky-600 dark:text-sky-400" : "text-red-600 dark:text-red-400",
      });
    }
    return out.sort((a, b) => (a.t < b.t ? -1 : a.t > b.t ? 1 : 0));
  }, [data]);

  const imgRow = rows.find((r) => r.image);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <input
          type="date"
          value={day}
          onChange={(e) => setDay(e.target.value || today())}
          className="rounded border border-zinc-300 bg-transparent px-2 py-1 text-sm dark:border-zinc-700"
        />
        <button
          onClick={() => void load(day)}
          className="rounded border border-zinc-300 px-2 py-1 text-sm hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
        >
          {busy ? "loading…" : "refresh"}
        </button>
        <span className="text-sm text-zinc-600 dark:text-zinc-400">
          building declared{" "}
          <strong className="font-medium">{data?.declared_state?.state?.replace(/_/g, " ") || "— nothing declared"}</strong>
          {data?.counts ? ` · ${data.counts.events ?? 0} signals · ${data.counts.entries ?? 0} keypad · ${data.counts.decisions ?? 0} verdicts · ${data.counts.evidence ?? 0} pictures` : ""}
        </span>
      </div>

      {data?.error ? (
        <p className="text-sm text-red-600 dark:text-red-400">{data.error}</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-zinc-500">
          Nothing recorded for this day. That is an absence of events, not a failure — the listener records every
          door edge and every keypad press it sees.
        </p>
      ) : (
        <ul className="divide-y divide-zinc-200 dark:divide-zinc-800">
          {rows.map((r, i) => (
            <li key={i} className="flex gap-4 py-2">
              <span className="w-20 shrink-0 font-mono text-xs text-zinc-500">{clock(r.t)}</span>
              <span className="w-24 shrink-0 text-xs uppercase tracking-wide text-zinc-400">{r.kind}</span>
              <span className="min-w-0 flex-1">
                <span className={`block text-sm ${r.tone}`}>{r.title}</span>
                {r.detail ? <span className="block text-xs text-zinc-500">{r.detail}</span> : null}
              </span>
              {r.image ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={r.image} alt="captured at this moment" className="h-16 w-24 shrink-0 rounded object-cover" />
              ) : null}
            </li>
          ))}
        </ul>
      )}

      {imgRow?.image ? (
        <div className="pt-2">
          <p className="mb-1 text-xs uppercase tracking-wide text-zinc-400">largest picture this day</p>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={imgRow.image} alt="shop" className="max-h-96 rounded border border-zinc-200 dark:border-zinc-800" />
        </div>
      ) : null}
    </div>
  );
}
