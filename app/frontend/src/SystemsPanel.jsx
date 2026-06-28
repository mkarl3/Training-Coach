import React, { useEffect, useState } from "react";

// "Your systems" — per-system trend small-multiples (Threshold / Aerobic power / Sprint / Time to
// exhaustion). Each card shows the current value, recent direction, and a weekly sparkline. The
// block-relevant system(s) lead the grid, ringed + tagged "Current focus"; off-focus systems dim
// back. Scrub a sparkline for a week's value; tap a card to open the detail drawer (bigger chart +
// Wattson's "why this matters now" note). The backend (/api/systems) computes every number and every
// line of copy (THE ONE RULE); this only renders.

const DIR = {
  rising: { a: "↑", c: "var(--green)" },
  falling: { a: "↓", c: "var(--ramp-lose)" },
  flat: { a: "→", c: "var(--ink-2)" },
};

const MO = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function fmtWeek(iso) {                               // "2026-05-12" -> "May 12"
  if (!iso) return "";
  const [, m, d] = iso.split("-").map(Number);
  return `${MO[m - 1]} ${d}`;
}
function fmtMonth(iso) {                              // "2026-05-12" -> "May"
  return iso ? MO[Number(iso.split("-")[1]) - 1] : "";
}
// n evenly-spaced labels across a week-date array (fmt = fmtWeek or fmtMonth)
function axisTicks(weeks, n, fmt) {
  if (!weeks || !weeks.length) return [];
  const k = Math.min(n, weeks.length), out = [];
  for (let i = 0; i < k; i++) out.push(fmt(weeks[Math.round((i * (weeks.length - 1)) / (k - 1))]));
  return out;
}

// Minimal x-axis for the collapsed sparkline — a few month labels so the line has a time scale.
function SparkAxis({ weeks }) {
  const t = axisTicks(weeks, 3, fmtMonth);
  if (t.length < 2) return null;
  return <div className="spark-xax">{t.map((m, i) => <span key={i}>{m}</span>)}</div>;
}

// Data-confidence cue: how long since an effort actually informed this system. Fresh systems show
// nothing (clean read); aging/stale show how long ago, and stale dims the whole card + flags it —
// matching Wattson's narrative hedge so the number isn't read as a real move (THE ONE RULE upstream).
function confCue(s) {
  if (!s.confidence || s.confidence === "fresh" || s.confidence === "none") return null;
  const wk = s.days_since != null ? Math.max(1, Math.round(s.days_since / 7)) : null;
  if (wk == null) return s.confidence === "stale" ? "stale" : null;
  const ago = `Last effort ${wk} week${wk === 1 ? "" : "s"} ago`;
  return s.confidence === "stale" ? `stale · ${ago}` : ago;
}

// Sparkline with a hover/scrub readout: drag across the line and a crosshair + tooltip show that
// week's value (no delta — the headline % already carries the trend).
function Spark({ pts, weeks, unit, color, height = 44 }) {
  const [hi, setHi] = useState(null);
  if (!pts || pts.length < 2) return null;
  const w = 240, h = height, pad = 4;
  const mn = Math.min(...pts), mx = Math.max(...pts), sp = (mx - mn) || 1;
  const xy = pts.map((v, i) => [(i / (pts.length - 1)) * w, (h - pad) - ((v - mn) / sp) * (h - 2 * pad)]);
  const d = xy.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  const onMove = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    const frac = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    setHi(Math.round(frac * (pts.length - 1)));
  };
  const pct = hi != null ? (hi / (pts.length - 1)) * 100 : 0;
  return (
    <div className="spark-wrap" style={{ position: "relative" }}
      onMouseMove={onMove} onMouseLeave={() => setHi(null)}>
      <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none"
        style={{ display: "block" }} aria-hidden="true">
        <polyline points={d} fill="none" stroke={color} strokeWidth="2"
          strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
      </svg>
      {hi != null && (
        <>
          <div className="spark-cross" style={{ left: `${pct}%` }} />
          <div className="spark-dot" style={{ left: `${pct}%`, top: `${xy[hi][1]}px`, background: color }} />
          <div className="spark-tip" style={{ left: `${pct}%` }}>
            {weeks && weeks[hi] && <span className="spark-tip-wk">wk of {fmtWeek(weeks[hi])}</span>}
            <span className="spark-tip-val">{pts[hi]}{unit ? ` ${unit}` : ""}</span>
          </div>
        </>
      )}
    </div>
  );
}

// The expanded detail chart — same weekly data, but now with axes: min/mid/max on the left, a few
// month ticks below, and reference gridlines. The heavy version lives behind a tap; the grid stays clean.
function DetailChart({ pts, weeks, color, unit }) {
  const [hi, setHi] = useState(null);
  if (!pts || pts.length < 2) return null;
  const w = 320, h = 132, pad = 8;
  const mn = Math.min(...pts), mx = Math.max(...pts), sp = (mx - mn) || 1;
  const xy = pts.map((v, i) => [(i / (pts.length - 1)) * w, (h - pad) - ((v - mn) / sp) * (h - 2 * pad)]);
  const d = xy.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  const ticks = axisTicks(weeks, 4, fmtWeek);
  const onMove = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    const frac = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    setHi(Math.round(frac * (pts.length - 1)));
  };
  const px = hi != null ? (hi / (pts.length - 1)) * 100 : 0;
  return (
    <div className="detail-chart">
      <div className="detail-yax">
        <span>{mx}{unit ? ` ${unit}` : ""}</span><span>{Math.round(((mn + mx) / 2) * 10) / 10}</span><span>{mn}</span>
      </div>
      <div className="detail-plot">
        <div className="detail-plotwrap" style={{ position: "relative" }}
          onMouseMove={onMove} onMouseLeave={() => setHi(null)}>
          <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none"
            style={{ display: "block" }} aria-hidden="true">
            <line x1="0" x2={w} y1={pad} y2={pad} className="detail-grid" vectorEffect="non-scaling-stroke" />
            <line x1="0" x2={w} y1={h / 2} y2={h / 2} className="detail-grid" vectorEffect="non-scaling-stroke" />
            <line x1="0" x2={w} y1={h - pad} y2={h - pad} className="detail-grid" vectorEffect="non-scaling-stroke" />
            <polyline points={d} fill="none" stroke={color} strokeWidth="2"
              strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
          </svg>
          {hi != null && (
            <>
              <div className="spark-cross" style={{ left: `${px}%` }} />
              <div className="spark-dot" style={{ left: `${px}%`, top: `${xy[hi][1]}px`, background: color }} />
              <div className="spark-tip" style={{ left: `${px}%` }}>
                {weeks && weeks[hi] && <span className="spark-tip-wk">wk of {fmtWeek(weeks[hi])}</span>}
                <span className="spark-tip-val">{pts[hi]}{unit ? ` ${unit}` : ""}</span>
              </div>
            </>
          )}
        </div>
        <div className="detail-xax">{ticks.map((t, i) => <span key={i}>{t}</span>)}</div>
      </div>
    </div>
  );
}

export default function SystemsPanel({ meta }) {
  const [data, setData] = useState(null);
  const [openKey, setOpenKey] = useState(null);
  useEffect(() => {
    fetch("/api/systems").then((r) => r.json()).then(setData).catch(() => {});
  }, [meta]);

  const sys = data && data.systems;
  if (!sys || !sys.length) return null;
  const open = sys.find((s) => s.key === openKey);
  const hasFocus = sys.some((s) => s.relevant);     // no power-system focus this block → don't dim anything
  return (
    <div className="panel systems-panel">
      <div className="trend-head">
        <h2>Your systems</h2>
        <span className="trend-hint">
          {data.block ? `${data.block} block` : "what's rising, what's stale (last ~3 mo)"}
        </span>
      </div>
      {data.building && <p className="systems-frame">Watching for <span>{data.building}</span>.</p>}
      <div className="systems-grid">
        {sys.map((s) => {
          const dd = DIR[s.dir] || DIR.flat;
          const cue = confCue(s);
          const stale = s.confidence === "stale";
          const off = hasFocus && !s.relevant;
          const accent = s.relevant ? "var(--gold)" : (stale ? "var(--ink-3)" : dd.c);
          const isOpen = s.key === openKey;
          const sparkColor = stale ? "var(--ink-3)" : dd.c;
          return (
            <div className={"sys-card" + (stale ? " sys-stale" : "") + (off ? " sys-offfocus" : "") + (isOpen ? " sys-open" : "")}
              key={s.key} style={{ borderTopColor: accent }}>
              <div className="sys-top">
                <div className="sys-top-l">
                  <span className="sys-label">{s.label}</span>
                  {s.relevant && <span className="sys-focus-badge">Current focus</span>}
                </div>
                <div className="sys-top-r">
                  <span className="sys-sub">{s.sub}</span>
                  <button className="sys-expand" aria-expanded={isOpen}
                    aria-label={isOpen ? `Hide ${s.label} detail` : `Show ${s.label} detail`}
                    onClick={() => setOpenKey(isOpen ? null : s.key)}>{isOpen ? "▾" : "▸"}</button>
                </div>
              </div>
              <div className="sys-val">
                {s.value}<span className="sys-unit">{s.unit}</span>
                <span className="sys-dir" style={{ color: sparkColor }}>
                  {dd.a} {s.delta_pct >= 0 ? "+" : ""}{s.delta_pct}%
                </span>
              </div>
              <Spark pts={s.spark} weeks={s.spark_weeks} unit={s.unit} color={sparkColor} />
              <SparkAxis weeks={s.spark_weeks} />
              {s.note && <div className="sys-note" style={{ color: s.relevant && !stale ? dd.c : "var(--ink-2)" }}>{s.note}</div>}
              {cue && <div className={"sys-conf" + (stale ? " sys-conf-stale" : "")}>{cue}</div>}
            </div>
          );
        })}
      </div>
      {open && (
        <div className="sys-drawer">
          <div className="sys-drawer-head">
            <span className="sys-drawer-title">
              {open.label}<span className="sys-drawer-sub"> · {open.sub}</span>
              <span className="sys-drawer-delta" style={{ color: (DIR[open.dir] || DIR.flat).c }}>
                {(DIR[open.dir] || DIR.flat).a} {open.delta_pct >= 0 ? "+" : ""}{open.delta_pct}% · 30d
              </span>
            </span>
            <button className="sys-expand" aria-label="Close detail" onClick={() => setOpenKey(null)}>✕</button>
          </div>
          <DetailChart pts={open.spark} weeks={open.spark_weeks} unit={open.unit}
            color={open.confidence === "stale" ? "var(--ink-3)" : (DIR[open.dir] || DIR.flat).c} />
          {open.why && <p className="sys-why">{open.why}</p>}
        </div>
      )}
    </div>
  );
}
