import React, { useEffect, useMemo, useState } from "react";
import Wattson, { VB_HEAD } from "./Wattson";

// Watt Smith fitness-trend dashboard. ONE instrument: a single ramp-coloured CTL line with
// weekly-TSS bars, insights pinned as markers on the timeline, and Coach Wattson reading the
// selected moment below. Range is the lens (6mo / 1yr / All) — high-level trends only; fine
// grain lives elsewhere. The chart computes ramp COLOUR from the safe ramp the backend supplies;
// it invents no numbers (THE ONE RULE).

const RANGES = [
  { k: "6mo", w: 26 },
  { k: "1yr", w: 52 },
  { k: "All", w: 9999 },
];
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// ramp-state colours (must match the four-state legend); marker tones reference the same vars.
const STATE = {
  build: "var(--ctl)", hot: "var(--ramp-hot)", hold: "var(--ramp-hold)", lose: "var(--ramp-lose)",
};
const TONE = { hot: STATE.hot, lose: STATE.lose, hold: STATE.hold, green: STATE.build, gold: "var(--gold)" };
const MOOD = { alarmed: "alarmed", approving: "approving", calm: "calm" };

function segColor(slope, safe) {
  if (slope < -0.4) return STATE.lose;
  if (slope > safe + 0.3) return STATE.hot;
  if (slope > 0.4) return STATE.build;
  return STATE.hold;
}

function Chart({ data, safe, insights, sel, onSel }) {
  const W = 760, H = 200, pL = 34, pR = 14, pT = 12, pB = 26;
  const plotW = W - pL - pR, plotH = H - pT - pB;
  if (data.length < 2) return <div className="empty-ok">Not enough history yet — keep logging rides.</div>;

  const ctls = data.map((d) => d.ctl);
  const ymin = Math.max(0, Math.floor((Math.min(...ctls) - 8) / 10) * 10);
  const ymax = Math.ceil((Math.max(...ctls) + 6) / 10) * 10;
  const X = (i) => pL + (data.length < 2 ? 0 : (i * plotW) / (data.length - 1));
  const Y = (v) => pT + ((ymax - v) * plotH) / (ymax - ymin);
  const idxByDate = Object.fromEntries(data.map((d, i) => [d.date, i]));
  const barMax = Math.max(...data.map((d) => d.tss), 1);

  const visible = insights.filter((m) => m.anchor_date && idxByDate[nearestWeek(m.anchor_date, data)] != null);
  const selM = insights.find((m) => m.id === sel);
  const focusZone =
    selM && selM.zone_start && idxByDate[nearestWeek(selM.zone_end, data)] != null;

  const step = Math.max(1, Math.ceil(data.length / 7));
  let seenMonth = -1;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet"
      style={{ width: "100%", height: "auto", display: "block" }} role="img" aria-label="Fitness trend">
      <rect width={W} height={H} fill="var(--panel-3)" rx="8" />
      {data.map((d, i) => {
        const h = (d.tss / barMax) * plotH * 0.5;
        const bw = Math.max(1.5, (plotW / data.length) * 0.62);
        return <rect key={"b" + i} x={X(i) - bw / 2} y={H - pB - h} width={bw} height={h} fill="var(--bar)" />;
      })}
      {focusZone && (() => {
        const za = X(Math.max(0, idxByDate[nearestWeek(selM.zone_start, data)] ?? 0));
        const zb = X(Math.min(data.length - 1, idxByDate[nearestWeek(selM.zone_end, data)]));
        return (
          <g>
            <rect x={pL} y={pT} width={Math.max(0, za - pL)} height={plotH} fill="rgba(11,11,20,0.6)" />
            <rect x={zb} y={pT} width={Math.max(0, W - pR - zb)} height={plotH} fill="rgba(11,11,20,0.6)" />
            <rect x={za} y={pT} width={Math.max(3, zb - za)} height={plotH} fill={TONE[selM.color]} opacity="0.08" />
          </g>
        );
      })()}
      {data.map((d, i) => {
        if (i === 0) return null;
        return (
          <line key={"l" + i} x1={X(i - 1)} y1={Y(data[i - 1].ctl)} x2={X(i)} y2={Y(d.ctl)}
            stroke={segColor(d.ctl - data[i - 1].ctl, safe)} strokeWidth="3" strokeLinecap="round" />
        );
      })}
      {[ymin, Math.round((ymin + ymax) / 2), ymax].map((v, n) => (
        <text key={"y" + n} x="4" y={Y(v) + 3} fontSize="10" fill="var(--ink-3)">{v}</text>
      ))}
      {data.map((d, i) => {
        if (i % step !== 0) return null;
        const dd = new Date(d.date + "T00:00:00");
        const mo = dd.getMonth();
        const lab = mo !== seenMonth ? MON[mo] : `${mo + 1}/${dd.getDate()}`;
        seenMonth = mo;
        return <text key={"x" + i} x={X(i)} y={H - 8} fontSize="9.5" fill="var(--ink-3)" textAnchor="middle">
          {lab}'{String(dd.getFullYear()).slice(2)}</text>;
      })}
      {visible.map((m) => {
        const i = idxByDate[nearestWeek(m.anchor_date, data)];
        const px = X(i), py = Y(data[i].ctl), on = m.id === sel, col = TONE[m.color];
        return (
          <g key={m.id} onClick={() => onSel(m.id)} style={{ cursor: "pointer" }}>
            <line x1={px} y1={pT} x2={px} y2={H - pB} stroke={col} strokeWidth="1" opacity={on ? 0.5 : 0.18} />
            {on && <circle cx={px} cy={py} r="9" fill={col} opacity="0.22" />}
            <circle cx={px} cy={py} r={on ? 5.5 : 4} fill={col} stroke="var(--bg)" strokeWidth="1.5" />
            <circle cx={px} cy={py} r="13" fill="transparent" />
          </g>
        );
      })}
    </svg>
  );
}

// snap an insight's anchor/zone date to the nearest weekly bucket present in the series
function nearestWeek(date, data) {
  if (idxCacheKey !== data) { idxCache = data.map((d) => d.date); idxCacheKey = data; }
  if (idxCache.includes(date)) return date;
  const t = new Date(date + "T00:00:00").getTime();
  let best = data[0]?.date, bd = Infinity;
  for (const d of data) {
    const gap = Math.abs(new Date(d.date + "T00:00:00").getTime() - t);
    if (gap < bd) { bd = gap; best = d.date; }
  }
  return best;
}
let idxCache = null, idxCacheKey = null;

function ReadStrip({ m }) {
  if (!m) return null;
  const col = TONE[m.color];
  return (
    <div className="read-strip">
      <div className="read-avatar"><Wattson mood={MOOD[m.mood] || "calm"} viewBox={VB_HEAD} /></div>
      <div className="read-body">
        <div className="read-head">
          <span className="read-coach">COACH WATTSON</span>
          <span className="read-title">{m.title}</span>
          {m.strength && <span className="read-strength">strength</span>}
        </div>
        <div className="read-text">{m.read}</div>
        <div className="read-pills">
          <span className="pill-chip" style={{ color: col, borderColor: col }}>{m.direction}</span>
          {m.plan && <span className="pill-chip">→ {m.plan}</span>}
        </div>
      </div>
    </div>
  );
}

export default function Watchman({ meta }) {
  const [data, setData] = useState(null);
  const [win, setWin] = useState(52);          // default 1yr
  const [sel, setSel] = useState("now");

  useEffect(() => {
    fetch(`/api/trend`).then((r) => r.json()).then(setData).catch(() => {});
  }, [meta]);

  const view = useMemo(() => {
    if (!data) return null;
    const s = win >= data.series.length ? data.series : data.series.slice(-win);
    const first = s.length ? s[0].date : null;
    const ins = data.insights.filter((m) => !first || !m.anchor_date || m.anchor_date >= first || m.id === "now");
    return { series: s, insights: ins };
  }, [data, win]);

  if (!data) return <div className="panel">Loading trend…</div>;
  if (!data.series.length) return <div className="panel empty-ok">No training history loaded yet.</div>;

  const visIds = new Set(view.insights.map((m) => m.id));
  const effSel = visIds.has(sel) ? sel : "now";
  const selM = data.insights.find((m) => m.id === effSel) || data.insights.find((m) => m.id === "now");
  const legend = [
    ["build", "building"], ["hot", "ramping hot"], ["hold", "holding"], ["lose", "losing fitness"],
  ];

  return (
    <div className="panel trend-panel">
      <div className="trend-head">
        <h2>Fitness trend</h2>
        <div className="range-bar">
          {RANGES.map((r) => (
            <button key={r.k} className={"range-btn" + (win === r.w ? " on" : "")}
              onClick={() => setWin(r.w)}>{r.k}</button>
          ))}
        </div>
      </div>
      <div className="trend-hint">tap a marker on the line</div>
      <div className="trend-grid">
        <div className="trend-left">
          <Chart data={view.series} safe={data.safe_ramp} insights={view.insights} sel={effSel} onSel={setSel} />
          <div className="trend-legend">
            {legend.map(([k, t]) => (
              <span key={k}><i style={{ background: STATE[k] }} />{t}</span>
            ))}
            <span className="muted">▏bars = weekly TSS</span>
          </div>
          <div className="trend-chips">
            {view.insights.map((m) => (
              <button key={m.id} className={"chip" + (m.id === effSel ? " on" : "")}
                style={m.id === effSel ? { borderColor: TONE[m.color] } : {}}
                onClick={() => setSel(m.id)}>
                <i style={{ background: TONE[m.color] }} />{chipLabel(m.title)}
              </button>
            ))}
          </div>
        </div>
        <div className="trend-right">
          <ReadStrip m={selM} />
        </div>
      </div>
    </div>
  );
}

function chipLabel(t) {
  return t.replace(/^Your /, "").replace(/ ~?\d+ weeks?$/, "");
}
