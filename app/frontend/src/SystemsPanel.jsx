import React, { useEffect, useState } from "react";

// "Your systems" — per-system trend small-multiples (Threshold / Aerobic power / Sprint / Threshold
// hold). Each card shows the current value, recent direction, and a weekly sparkline. The backend
// (/api/systems) computes every number (THE ONE RULE); this only renders.

const DIR = {
  rising: { a: "↑", c: "var(--green)" },
  falling: { a: "↓", c: "var(--ramp-lose)" },
  flat: { a: "→", c: "var(--ink-2)" },
};

function Spark({ pts, color }) {
  if (!pts || pts.length < 2) return null;
  const w = 132, h = 30, mn = Math.min(...pts), mx = Math.max(...pts), sp = (mx - mn) || 1;
  const d = pts.map((v, i) => `${(i / (pts.length - 1)) * w},${(h - 2) - ((v - mn) / sp) * (h - 4)}`).join(" ");
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none"
      style={{ display: "block", width: "100%", height: h }} aria-hidden="true">
      <polyline points={d} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

export default function SystemsPanel({ meta }) {
  const [sys, setSys] = useState(null);
  useEffect(() => {
    fetch("/api/systems").then((r) => r.json()).then((d) => setSys(d.systems || [])).catch(() => {});
  }, [meta]);

  if (!sys || !sys.length) return null;
  return (
    <div className="panel systems-panel">
      <div className="trend-head">
        <h2>Your systems</h2>
        <span className="trend-hint">what's rising, what's stale (last ~3 mo)</span>
      </div>
      <div className="systems-grid">
        {sys.map((s) => {
          const dd = DIR[s.dir] || DIR.flat;
          return (
            <div className="sys-card" key={s.key} style={{ borderTopColor: dd.c }}>
              <div className="sys-top">
                <span className="sys-label">{s.label}</span>
                <span className="sys-sub">{s.sub}</span>
              </div>
              <div className="sys-val">
                {s.value}<span className="sys-unit">{s.unit}</span>
                <span className="sys-dir" style={{ color: dd.c }}>
                  {dd.a} {s.delta_pct >= 0 ? "+" : ""}{s.delta_pct}%
                </span>
              </div>
              <Spark pts={s.spark} color={dd.c} />
            </div>
          );
        })}
      </div>
    </div>
  );
}
