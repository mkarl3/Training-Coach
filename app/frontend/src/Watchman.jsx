import React, { useEffect, useMemo, useState } from "react";

function daysBetween(min, max) {
  const out = [];
  const d = new Date(min + "T00:00:00");
  const end = new Date(max + "T00:00:00");
  while (d <= end) {
    out.push(d.toISOString().slice(0, 10));
    d.setDate(d.getDate() + 1);
  }
  return out;
}

function Trajectory({ state }) {
  const data = state.trajectory;
  const W = 880, H = 290, pad = { l: 34, r: 12, t: 12, b: 22 };
  const valid = data.filter((d) => d.ctl != null);
  if (valid.length < 2) return <div className="empty-ok">Not enough data in window.</div>;

  const vals = [];
  data.forEach((d) => ["ctl", "atl", "tsb"].forEach((k) => d[k] != null && vals.push(d[k])));
  const ymin = Math.min(...vals, 0), ymax = Math.max(...vals, 10);
  const xs = (i) => pad.l + (i * (W - pad.l - pad.r)) / (data.length - 1);
  const ys = (v) => pad.t + ((ymax - v) * (H - pad.t - pad.b)) / (ymax - ymin);
  const idxByDate = Object.fromEntries(data.map((d, i) => [d.date, i]));
  const poly = (k) =>
    data.map((d, i) => (d[k] == null ? null : `${xs(i).toFixed(1)},${ys(d[k]).toFixed(1)}`))
      .filter(Boolean).join(" ");

  const provFrom = data.findIndex((d) => d.provisional);
  const provX = provFrom >= 0 ? xs(provFrom) : null;
  const zeroY = ys(0);
  const colors = { ctl: "var(--ctl)", atl: "var(--atl)", tsb: "var(--tsb)" };

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="fitness trajectory">
        {state.trend_annotations.map((a, n) => {
          const i0 = idxByDate[a.zone_start], i1 = idxByDate[a.zone_end];
          if (i0 == null && i1 == null) return null;
          const x0 = xs(i0 ?? 0), x1 = xs(i1 ?? data.length - 1);
          return (
            <g key={n}>
              <rect x={x0} y={pad.t} width={Math.max(2, x1 - x0)} height={H - pad.t - pad.b}
                fill="rgba(185,136,59,0.10)" />
              <text x={x0 + 3} y={pad.t + 11} fontSize="9" fill="var(--amber)">{a.mode_id}</text>
            </g>
          );
        })}
        {provX != null && (
          <rect x={provX} y={pad.t} width={W - pad.r - provX} height={H - pad.t - pad.b} fill="var(--prov)" />
        )}
        <line x1={pad.l} x2={W - pad.r} y1={zeroY} y2={zeroY} stroke="var(--line)" strokeDasharray="3 3" />
        {["ctl", "atl", "tsb"].map((k) => (
          <polyline key={k} points={poly(k)} fill="none" stroke={colors[k]} strokeWidth="2"
            strokeLinejoin="round" strokeLinecap="round" />
        ))}
        {state.tripwires.map((t, n) => {
          const i = idxByDate[t.window_end];
          if (i == null) return null;
          return (
            <g key={n}>
              <line x1={xs(i)} x2={xs(i)} y1={pad.t} y2={H - pad.b} stroke="var(--red)" strokeWidth="1" />
              <circle cx={xs(i)} cy={ys(data[i].ctl ?? ymin)} r="4" fill="var(--red)" />
            </g>
          );
        })}
        {[ymin, Math.round((ymin + ymax) / 2), ymax].map((v, n) => (
          <text key={n} x="2" y={ys(v) + 3} fontSize="9" fill="var(--muted)">{Math.round(v)}</text>
        ))}
      </svg>
      <div className="legend">
        <span><i style={{ background: "var(--ctl)" }} />CTL (fitness)</span>
        <span><i style={{ background: "var(--atl)" }} />ATL (fatigue)</span>
        <span><i style={{ background: "var(--tsb)" }} />TSB (form)</span>
        <span><i style={{ background: "var(--prov)" }} />provisional</span>
      </div>
    </div>
  );
}

function Direction({ dir }) {
  const Item = ({ k }) => {
    const d = dir[k];
    if (!d) return null;
    const cls = d.dir === "rising" ? "up" : d.dir === "falling" ? "down" : "flat";
    const arrow = d.dir === "rising" ? "↗" : d.dir === "falling" ? "↘" : "→";
    return (
      <div>
        <div className="k">{k}</div>
        <div className="v">{d.now}</div>
        <div className={"chg " + cls}>{arrow} {d.dir} ({d.change >= 0 ? "+" : ""}{d.change}/28d)</div>
      </div>
    );
  };
  return <div className="dir"><Item k="ctl" /><Item k="atl" /><Item k="tsb" /></div>;
}

function WatchPanel({ state }) {
  const { tripwires, trend_annotations, context, watch_rollup } = state;
  const nothing = !tripwires.length && !trend_annotations.length;
  return (
    <div className="panel">
      <h2>Watch out for</h2>
      {nothing && <div className="empty-ok">✓ Nothing active — no failure-mode signal right now.</div>}
      {tripwires.map((t, n) => (
        <div className="alert-row" key={"t" + n}>
          <span className={"badge " + (t.provisional ? "prov" : "tripwire")}>
            {t.provisional ? "provisional" : "alert"}
          </span>
          <div className="body">
            <div className="title">{t.mode_id.replace(/_/g, " ")}</div>
            <div className="meta">
              event {t.window_start} → {t.window_end}
              {t.evidence.ctl_drop != null && ` · CTL −${t.evidence.ctl_drop} from peak ${t.evidence.recent_peak_ctl}`}
              {t.evidence.acwr != null && ` · ACWR ${t.evidence.acwr}`}
              {t.data_flags.length > 0 && <span className="flag"> · ⚑ {t.data_flags.join(", ")}</span>}
            </div>
          </div>
        </div>
      ))}
      {trend_annotations.map((a, n) => (
        <div className="zone-row" key={"z" + n}>
          <span className="badge trend">trend</span>
          <div className="body">
            <div className="title">{a.mode_id.replace(/_/g, " ")}</div>
            <div className="meta">ongoing zone {a.zone_start} → {a.zone_end}</div>
          </div>
        </div>
      ))}
      {context.map((c, n) => (
        <div className="ctx-row" key={"c" + n}>◦ {c.label} (CTL {c.value} vs normal ≥{c.reference})</div>
      ))}
      {watch_rollup.length > 0 && (
        <div className="rollup">
          watch-tier (collapsed): {watch_rollup.map((w) => `${w.mode_id.replace(/_/g, " ")} ×${w.count}`).join(", ")}
        </div>
      )}
    </div>
  );
}

function Gauge({ gauge }) {
  if (!gauge) return null;
  return (
    <div className="panel">
      <h2>Durability gauge</h2>
      <div className="gauges">
        {gauge.legs.decoupling && (
          <div className="gauge">
            <div className="lab">Aerobic decoupling (Pw:Hr)</div>
            <div className="big" style={{ color: gauge.legs.decoupling.severity === "confirmed" ? "var(--red)" : "var(--amber)" }}>
              {gauge.legs.decoupling.decoupling_pct}%
            </div>
            <div className="sub">last long ride {gauge.legs.decoupling.last_assessed}</div>
          </div>
        )}
        {gauge.legs.power_duration && (
          <div className="gauge">
            <div className="lab">1 h → 2 h power fade</div>
            <div className="big" style={{ color: gauge.legs.power_duration.severity === "confirmed" ? "var(--red)" : "var(--amber)" }}>
              {gauge.legs.power_duration.gap_1h_2h_w} W
            </div>
            <div className="sub">last assessed {gauge.legs.power_duration.last_assessed}</div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function Watchman({ meta }) {
  const dates = useMemo(() => daysBetween(meta.date_min, meta.date_max), [meta]);
  const [idx, setIdx] = useState(dates.length - 1);
  const [state, setState] = useState(null);
  const asOf = dates[idx];

  useEffect(() => {
    if (!asOf) return;
    fetch(`/api/watchman?as_of=${asOf}&window=120`)
      .then((r) => r.json()).then(setState).catch(() => {});
  }, [asOf]);

  if (!state) return <div className="panel">Loading trajectory…</div>;

  return (
    <>
      <div className="controls">
        <button onClick={() => setIdx(Math.max(0, idx - 7))}>‹ wk</button>
        <span className="date">{asOf}</span>
        <input type="range" min={0} max={dates.length - 1} value={idx}
          onChange={(e) => setIdx(Number(e.target.value))} />
        <button onClick={() => setIdx(Math.min(dates.length - 1, idx + 7))}>wk ›</button>
        <span className={"pill " + state.status}>{state.status}</span>
      </div>
      <div className="panel">
        <h2>Trajectory — direction of travel</h2>
        <Direction dir={state.direction} />
        <Trajectory state={state} />
      </div>
      <WatchPanel state={state} />
      <Gauge gauge={state.gauge} />
    </>
  );
}
