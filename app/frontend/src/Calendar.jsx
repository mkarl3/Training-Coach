import React, { useEffect, useState } from "react";

// Watt Smith season plan. A thin full-width history→plan strip (TrainerRoad-style), a "this week"
// focus card, and a collapsible NES block accordion with expandable week pills. Setup + adjustments
// live below. Every number is computed in code (THE ONE RULE); the 8-bit lives in the chrome only.

const FAM = { base: "#3a6ad8", build: "#4ac94a", peak: "#f7d51d", taper: "#9aa6c4" };
const C = { p3: "#0f1830", line: "#2b3a63", cream: "#f4f4f0", ink: "#9fb0d8", ink3: "#5e6e96",
  gold: "#f7d51d", green: "#4ac94a", steel: "#45557a", amber: "#ffb020" };
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const dt = (iso) => new Date(iso + "T00:00:00");
const dlabel = (iso) => { const d = dt(iso); return MON[d.getMonth()] + " " + d.getDate(); };
const statusOf = (s) => (s === "elapsed" ? "done" : s === "current" ? "now" : "next");

// ---------------------------------------------------------------- strip
function Strip({ history, weeks }) {
  const planStart = weeks[0].week_start;
  const hist = (history || []).filter((s) => s.date < planStart).slice(-26)
    .map((s) => ({ tss: s.tss, ctl: s.ctl, date: s.date, status: "done", plan: false }));
  const plan = weeks.map((w) => ({
    tss: w.weekly_tss_target, ctl: w.ctl_target, date: w.week_end, status: statusOf(w.status),
    actual: w.actual_tss, fam: w.family, ft: w.field_test, plan: true,
  }));
  const CH = hist.concat(plan);
  const PLAN0 = hist.length;
  const curIdx = CH.findIndex((c) => c.status === "now");
  const markIdx = curIdx >= 0 ? curIdx : PLAN0;

  const Wd = 700, H = 74, pL = 8, pR = 8, pT = 14, baseY = 52, n = CH.length, plotW = Wd - pL - pR;
  const X = (i) => pL + (plotW * (i + 0.5)) / n;
  const barMax = Math.max(...CH.map((c) => c.tss), 1);
  const cMin = 14, cMax = Math.max(...CH.map((c) => c.ctl), 20) + 2;
  const Yc = (v) => pT + ((cMax - v) * (baseY - pT)) / (cMax - cMin);
  const bw = Math.max(3, (plotW / n) * 0.74);
  const col = (s) => (s === "done" ? C.green : s === "now" ? C.gold : C.steel);
  const fams = [];
  weeks.forEach((w, i) => { const ci = PLAN0 + i, last = fams[fams.length - 1];
    if (last && last.fam === w.family) last.e = ci; else fams.push({ fam: w.family, s: ci, e: ci }); });
  let seen = -1;
  const px = X(PLAN0) - plotW / n / 2;

  return (
    <svg viewBox={`0 0 ${Wd} ${H}`} width="100%" shapeRendering="crispEdges" role="img" aria-label="Training history into the planned season">
      <rect width={Wd} height={H} fill={C.p3} />
      <rect x={X(markIdx) - plotW / n / 2} y={pT} width={plotW / n} height={baseY - pT} fill="rgba(247,213,29,0.14)" />
      <line x1={px} x2={px} y1={pT - 3} y2={baseY + 8} stroke={C.ink3} strokeDasharray="2 2" />
      {CH.map((c, i) => {
        const h = Math.max(1, (c.tss / barMax) * (baseY - pT));
        return <rect key={i} x={X(i) - bw / 2} y={baseY - h} width={bw} height={h} fill={col(c.status)} opacity={c.status === "next" ? 0.7 : 1} />;
      })}
      <polyline points={CH.map((c, i) => `${X(i).toFixed(1)},${Yc(c.ctl).toFixed(1)}`).join(" ")} fill="none" stroke={C.cream} strokeWidth="1.5" />
      <line x1={pL} x2={Wd - pR} y1={baseY} y2={baseY} stroke={C.line} />
      {fams.map((g, k) => {
        const x0 = X(g.s) - bw / 2 - 1, x1 = X(g.e) + bw / 2 + 1;
        return <rect key={"f" + k} x={x0} y={baseY + 3} width={x1 - x0} height={4} fill={FAM[g.fam]} />;
      })}
      {CH.map((c, i) => (c.plan && c.ft ? (
        <rect key={"ft" + i} x={X(i) - 2} y={baseY + 9} width={4} height={4} fill={C.ink} transform={`rotate(45 ${X(i)} ${baseY + 11})`} />
      ) : null))}
      <rect x={X(n - 1) - 3.5} y={baseY + 7.5} width={7} height={7} fill={C.gold} transform={`rotate(45 ${X(n - 1)} ${baseY + 11})`}><title>A-race</title></rect>
      {CH.map((c, i) => { const mo = dt(c.date).getMonth(); if (mo === seen) return null; seen = mo;
        return <text key={"m" + i} x={X(i)} y="9" fontSize="7.5" fill={C.ink3} textAnchor="middle">{MON[mo]}</text>; })}
    </svg>
  );
}

// ---------------------------------------------------------------- this week
function ThisWeek({ w, isCurrent, refresh }) {
  const col = FAM[w.family];
  const sb = (l, v) => (
    <div key={l}><div className="cal-sblab">{l}</div><div className="cal-sbval">{v}</div></div>
  );
  return (
    <div className="cal-thisweek" style={{ borderColor: col }}>
      <div className="cal-tw-head">
        <div>
          <span className="cal-tw-tag">{isCurrent ? "THIS WEEK" : "UP NEXT"} · WK {w.week}</span>
          <div className="cal-tw-title"><span className="dot" style={{ background: col }} />{w.block}
            <span className="muted"> · week of {dlabel(w.week_start)}</span></div>
        </div>
        <div className="cal-tw-tss"><div className="v">{w.weekly_tss_target}</div><div className="l">TSS this week</div></div>
      </div>
      <div className="cal-tw-focus">{w.focus}.</div>
      {isCurrent && refresh && (
        <div className="cal-tw-refresh">
          <span className="cal-tw-refresh-tag">⚡ Keep the analysis fresh</span>
          <span>{refresh.sentence}</span>
        </div>
      )}
      <div className="cal-tw-stats">
        {sb("Long ride", w.long_ride_hours ? w.long_ride_hours + " h" : "—")}
        {sb("Single-ride cap", "≤" + w.single_ride_tss_cap + " TSS")}
        {sb("Est. hours", w.est_hours + " h")}
        {sb("Fitness target", "→ " + w.ctl_target)}
      </div>
      {w.rationale && (
        <div className="cal-tw-note">
          <span className="cal-tw-note-i"><i className="ti ti-mountain" aria-hidden="true" /></span>
          <span>{w.rationale}</span>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- block accordion
function Blocks({ weeks }) {
  const groups = [];
  weeks.forEach((w) => { const last = groups[groups.length - 1];
    if (last && last.block === w.block) last.weeks.push(w); else groups.push({ block: w.block, fam: w.family, weeks: [w] }); });
  const [openB, setOpenB] = useState(() => {
    const o = {}; groups.forEach((g) => { if (g.weeks.some((w) => w.status === "current")) o[g.block] = true; }); return o;
  });
  const [openW, setOpenW] = useState({});

  return (
    <div className="cal-blocks">
      {groups.map((g) => {
        const col = FAM[g.fam], ts = g.weeks.map((w) => w.weekly_tss_target), hrs = g.weeks.map((w) => w.est_hours);
        const tmin = Math.min(...ts), tmax = Math.max(...ts), hmin = Math.min(...hrs), hmax = Math.max(...hrs);
        const hasNow = g.weeks.some((w) => w.status === "current");
        const allDone = g.weeks.every((w) => w.status === "elapsed");
        const hr = hmin === hmax ? `${hmin} h` : `${hmin}–${hmax} h`;
        return (
          <div key={g.block}>
            <div className="cal-blocktab" style={{ background: col }}>{g.block.toUpperCase()}{hasNow ? " · NOW" : ""}</div>
            <div className={"cal-blockrow" + (hasNow ? " now" : "")} style={{ borderColor: hasNow ? col : C.line, borderLeftColor: col, opacity: allDone ? 0.7 : 1 }}
              onClick={() => setOpenB((s) => ({ ...s, [g.block]: !s[g.block] }))}>
              <div className="cal-blocksum"><b>{g.weeks.length} week{g.weeks.length > 1 ? "s" : ""}</b>
                <span className="muted"> · </span>{hr}/wk<span className="muted"> · </span>{tmin}–{tmax} TSS/wk</div>
              <i className={"ti ti-chevron-" + (openB[g.block] ? "up" : "down")} aria-hidden="true" />
            </div>
            {openB[g.block] && (
              <div className="cal-pills">
                {g.weeks.map((w) => {
                  const open = openW[w.week], isNow = w.status === "current", done = w.status === "elapsed";
                  const hit = w.actual_tss != null && w.actual_tss >= w.weekly_tss_target * 0.95;
                  return (
                    <div key={w.week} className={"cal-pill" + (isNow ? " now" : "")} style={{ opacity: done ? 0.65 : 1, borderColor: isNow ? FAM[w.family] : C.line }}
                      onClick={() => setOpenW((s) => ({ ...s, [w.week]: !s[w.week] }))}>
                      <div className="cal-pill-row">
                        <span className="cal-pill-wk">{w.week}</span>
                        <span className="cal-pill-date">{dlabel(w.week_start)}</span>
                        <span className="cal-pill-focus">{w.focus}{w.is_recovery ? <span className="muted"> · recovery</span> : null}</span>
                        <span className="cal-pill-tss">{w.weekly_tss_target}
                          {w.actual_tss != null && <> <span className="muted">/</span> <b style={{ color: hit ? C.green : C.amber }}>{w.actual_tss}</b></>}
                        </span>
                        <i className={"ti ti-chevron-" + (open ? "up" : "down")} aria-hidden="true" />
                      </div>
                      {open && (
                        <div className="cal-pill-detail">
                          <div><div className="cal-dlab">Cap</div><div className="cal-dval">≤{w.single_ride_tss_cap} TSS</div></div>
                          <div><div className="cal-dlab">Hours</div><div className="cal-dval">{w.est_hours} h</div></div>
                          <div><div className="cal-dlab">Long</div><div className="cal-dval">{w.long_ride_hours ? w.long_ride_hours + " h" : "—"}</div></div>
                          <div><div className="cal-dlab">Fitness</div><div className="cal-dval">→ {w.ctl_target}</div></div>
                          {w.actual_tss != null && <div><div className="cal-dlab">Δ plan</div><div className="cal-dval">{w.actual_tss - w.weekly_tss_target >= 0 ? "+" : ""}{w.actual_tss - w.weekly_tss_target}</div></div>}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------- setup forms (preserved)
function SeasonForm({ season, onSaved }) {
  const [name, setName] = useState(season?.name || "2026 Season");
  const [start, setStart] = useState(season?.start_date || "");
  const [hours, setHours] = useState(season?.weekly_hours_budget || 7);
  async function save() {
    await fetch("/api/season", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, start_date: start, weekly_hours_budget: Number(hours) }) });
    onSaved();
  }
  return (
    <div className="cal-form">
      <label><span>Season</span><input value={name} onChange={(e) => setName(e.target.value)} /></label>
      <label><span>Start date</span><input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></label>
      <label><span>Weekly hours available</span><input type="number" step="0.5" value={hours} onChange={(e) => setHours(e.target.value)} /></label>
      <button className="primary" onClick={save} disabled={!start}>Save season</button>
    </div>
  );
}
function EventForm({ eventTypes, onAdded }) {
  const [f, setF] = useState({ name: "", event_date: "", priority: "A", event_type: eventTypes[0] || "gran_fondo" });
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));
  async function add() {
    const r = await fetch("/api/season/event", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(f) });
    if (r.ok) { setF({ ...f, name: "", event_date: "" }); onAdded(); }
  }
  return (
    <div className="cal-form wrap">
      <input placeholder="event name" value={f.name} onChange={(e) => set("name", e.target.value)} />
      <input type="date" value={f.event_date} onChange={(e) => set("event_date", e.target.value)} />
      <select value={f.priority} onChange={(e) => set("priority", e.target.value)}>{["A", "B", "C"].map((p) => <option key={p}>{p}</option>)}</select>
      <select value={f.event_type} onChange={(e) => set("event_type", e.target.value)}>{eventTypes.map((t) => <option key={t} value={t}>{t.replace(/_/g, " ")}</option>)}</select>
      <button onClick={add} disabled={!f.name || !f.event_date}>+ event</button>
    </div>
  );
}

// ---------------------------------------------------------------- page
// ---------------------------------------------------------------- training log (Strava daily grid)
const ZCOL = { 1: "#2b3a63", 2: "#3a6ad8", 3: "#2bb6a8", 4: "#f7d51d", 5: "#ff7a45", 6: "#e84444" };
const ZLAB = { 1: "Z1 rec", 2: "Z2 endur", 3: "Z3 tempo", 4: "Z4 thresh", 5: "Z5 VO2", 6: "Z6 anaer" };
const hms = (s) => { const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60); return `${h}:${String(m).padStart(2, "0")}`; };

// Google encoded-polyline → [[lat,lng]] (for the route thumbnail).
function decodePoly(str) {
  let i = 0, lat = 0, lng = 0; const c = [];
  while (i < str.length) {
    let b, sh = 0, r = 0;
    do { b = str.charCodeAt(i++) - 63; r |= (b & 31) << sh; sh += 5; } while (b >= 32);
    lat += (r & 1) ? ~(r >> 1) : (r >> 1); sh = 0; r = 0;
    do { b = str.charCodeAt(i++) - 63; r |= (b & 31) << sh; sh += 5; } while (b >= 32);
    lng += (r & 1) ? ~(r >> 1) : (r >> 1);
    c.push([lat / 1e5, lng / 1e5]);
  }
  return c;
}

function Route({ poly, color = "#5c8cde", indoor, h = 44 }) {
  const pts = poly ? decodePoly(poly) : [];
  if (pts.length < 2) return <div className="log-glyph">{indoor ? "indoor" : "—"}</div>;
  const la = pts.map((p) => p[0]), ln = pts.map((p) => p[1]);
  const mLa = Math.min(...la), XLa = Math.max(...la), mLn = Math.min(...ln), XLn = Math.max(...ln);
  const w = (XLn - mLn) || 1, hh = (XLa - mLa) || 1, pad = 4;
  const sc = Math.min((100 - 2 * pad) / w, (h - 2 * pad) / hh);   // uniform → true route shape
  const ox = (100 - w * sc) / 2, oy = (h - hh * sc) / 2;
  const path = pts.map((p) => `${(ox + (p[1] - mLn) * sc).toFixed(1)},${(oy + (XLa - p[0]) * sc).toFixed(1)}`).join(" ");
  return (
    <svg className="log-route" viewBox={`0 0 100 ${h}`} preserveAspectRatio="xMidYMid meet">
      <polyline points={path} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function LogCell({ day, onSel }) {
  if (day.is_rest) return <div className={"log-rest" + (day.in_month ? "" : " off")}><span>{day.dom}</span></div>;
  const primary = day.rides.reduce((a, b) => (b.tss > a.tss ? b : a), day.rides[0]);
  const z = day.dominant_zone || 2;
  return (
    <button className={"log-cell" + (day.in_month ? "" : " off")} style={{ borderTopColor: ZCOL[z] }} onClick={() => onSel(day)}>
      <span className="lc-dom">{day.dom}</span>
      {day.rides.length > 1 && <span className="lc-multi">+{day.rides.length - 1}</span>}
      <div className="lc-name">{primary.name}</div>
      <div className="lc-big">{day.tss}<span className="lc-sub"> · {primary.if.toFixed(2)}</span></div>
      <div className="lc-sub">{hms(primary.duration_s)}{primary.distance_mi ? ` · ${primary.distance_mi}mi` : ""}</div>
      <Route poly={primary.polyline} color={ZCOL[z]} indoor={primary.indoor} h={36} />
    </button>
  );
}

function LStat({ k, v }) { return (<div className="lstat"><div className="lstat-k">{k}</div><div className="lstat-v">{v}</div></div>); }

function DayDetail({ day, onClose }) {
  const PK = { "5": "5s", "60": "1m", "300": "5m", "1200": "20m" };
  return (
    <div className="panel log-detail">
      <div className="ld-head"><b>{dlabel(day.date)}</b>
        <span className="muted">{day.rides.length} ride{day.rides.length > 1 ? "s" : ""}</span>
        <button className="del" onClick={onClose}>×</button></div>
      {day.rides.map((r, i) => (
        <div className="ld-ride" key={i}>
          <div className="ld-name">{r.name}{r.indoor && <span className="ld-badge">indoor</span>}
            <span className="ld-zone" style={{ color: ZCOL[r.dominant_zone || 2] }}>● {ZLAB[r.dominant_zone || 2]}</span></div>
          <div className="ld-stats">
            <LStat k="TSS" v={r.tss} /><LStat k="IF" v={r.if.toFixed(2)} /><LStat k="NP" v={r.np + "w"} />
            <LStat k="Time" v={hms(r.duration_s)} />{r.distance_mi != null && <LStat k="Dist" v={r.distance_mi + "mi"} />}
            {r.elev_ft != null && <LStat k="Elev" v={r.elev_ft + "ft"} />}
            {r.ef != null && <LStat k="EF" v={r.ef.toFixed(2)} />}{r.decoupling != null && <LStat k="Decouple" v={r.decoupling + "%"} />}
          </div>
          <div className="ld-tiz">{r.tiz.map((s, zi) => (s > 0 ? <span key={zi} style={{ flex: s, background: ZCOL[zi + 1] }} /> : null))}</div>
          <div className="ld-peaks">
            {["5", "60", "300", "1200"].map((k) => (r.mmp[k] ? <span key={k} className="ld-peak">{PK[k]} {Math.round(r.mmp[k])}w</span> : null))}
            {r.pr.map((p) => <span key={p} className="ld-pr">★ {p} 90-day best</span>)}
          </div>
          {r.polyline && <div className="ld-map"><Route poly={r.polyline} h={70} /></div>}
        </div>
      ))}
    </div>
  );
}

function gutCls(act, plan) { if (plan == null || act == null) return "muted"; return act >= plan ? "ok" : "under"; }

function LogView() {
  const [log, setLog] = useState(null);
  const [ym, setYm] = useState(null);
  const [sel, setSel] = useState(null);
  useEffect(() => {
    setLog(null);
    const q = ym ? `?year=${ym.year}&month=${ym.month}` : "";
    fetch("/api/log" + q).then((r) => r.json()).then((d) => { setLog(d); if (!ym) setYm({ year: d.year, month: d.month }); }).catch(() => {});
  }, [ym]);
  if (!log) return <div className="panel">Loading log…</div>;
  const nav = (delta) => { let y = log.year, mo = log.month + delta; if (mo < 1) { mo = 12; y--; } if (mo > 12) { mo = 1; y++; } setSel(null); setYm({ year: y, month: mo }); };
  return (
    <div className="panel cal-log">
      <div className="log-head">
        <button className="log-nav" onClick={() => nav(-1)}>‹</button>
        <span className="pix log-title">{MON[log.month - 1]} {log.year}</span>
        <button className="log-nav" onClick={() => nav(1)}>›</button>
      </div>
      <div className="log-dow">{["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => <span key={d}>{d}</span>)}<span className="gw">wk</span></div>
      <div className="log-grid">
        {log.weeks.map((wk, wi) => (
          <React.Fragment key={wi}>
            {wk.days.map((d) => <LogCell key={d.date} day={d} onSel={setSel} />)}
            <div className="log-gut">
              <div><div className="lg-lab">TSS</div><div className={"lg-val " + gutCls(wk.tss_actual, wk.tss_plan)}>{wk.tss_actual}{wk.tss_plan ? `/${wk.tss_plan}` : ""}</div></div>
              <div><div className="lg-lab">Fit</div><div className={"lg-val " + gutCls(wk.ctl_actual, wk.ctl_plan)}>{wk.ctl_actual ?? "–"}{wk.ctl_plan ? `/${wk.ctl_plan}` : ""}</div></div>
            </div>
          </React.Fragment>
        ))}
      </div>
      <div className="log-legend">
        <span className="muted">dominant zone:</span>
        {[2, 3, 4, 5].map((z) => <span key={z}><i style={{ background: ZCOL[z] }} />{ZLAB[z]}</span>)}
        <span className="muted">· big = TSS·IF · +N = extra rides · gutter = actual/plan</span>
      </div>
      {sel && <DayDetail day={sel} onClose={() => setSel(null)} />}
    </div>
  );
}

export default function Calendar() {
  const [view, setView] = useState("plan");
  const [data, setData] = useState(null);
  const [plan, setPlan] = useState(null);
  const [history, setHistory] = useState([]);
  const [adjustments, setAdjustments] = useState([]);
  const [loading, setLoading] = useState(true);

  async function load() {
    const [s, p, t, a] = await Promise.all([
      fetch("/api/season").then((r) => r.json()),
      fetch("/api/plan").then((r) => r.json()),
      fetch("/api/trend").then((r) => r.json()).catch(() => ({ series: [] })),
      fetch("/api/plan/adjustments").then((r) => r.json()).catch(() => ({ adjustments: [] })),
    ]);
    setData(s); setPlan(p.error ? null : p); setHistory(t.series || []);
    setAdjustments(a.adjustments || []); setLoading(false);
  }
  async function undoAdjustment(id) { await fetch(`/api/plan/adjustment/${id}/undo`, { method: "POST" }).catch(() => {}); load(); }
  useEffect(() => { load(); }, []);

  if (loading) return <div className="panel">Loading calendar…</div>;
  const eventTypes = data.event_types;
  const cur = plan && (plan.weeks.find((w) => w.status === "current") || plan.weeks.find((w) => w.status === "upcoming") || plan.weeks[0]);
  const m = plan && plan.meta;

  return (
    <div>
      <div className="cal-viewtoggle">
        <button className={view === "plan" ? "on" : ""} onClick={() => setView("plan")}>Plan</button>
        <button className={view === "log" ? "on" : ""} onClick={() => setView("log")}>Log</button>
      </div>

      {view === "log" ? <LogView /> : (<>
      {plan && (
        <div className="panel cal-plan">
          <div className="cal-plan-head">
            <div className="cal-title pix">SEASON PLAN</div>
            <div className="cal-race"><b>{m.a_race.name}</b> · {m.a_race.date}
              <span className="pix cal-wk"> WK {cur.week}/{m.weeks}</span></div>
          </div>
          <Strip history={history} weeks={plan.weeks} />
          <div className="cal-legend">
            <span><i style={{ background: C.green }} />done</span>
            <span><i style={{ background: C.gold }} />current</span>
            <span><i style={{ background: C.steel }} />planned</span>
            <span><i className="ln" style={{ background: C.cream }} />fitness</span>
            <span style={{ color: C.gold }}>◆ race</span>
          </div>
          {!m.target_reached && (
            <div className="honest">⚠ Honest miss: in {m.weeks} weeks at {m.weekly_hours_budget} h/wk you reach
              fitness ~{m.peak_ctl_achieved}, short of the {m.target_peak_ctl} target. More time or hours
              would close it — the plan won't pretend otherwise.</div>
          )}
          <ThisWeek w={cur} isCurrent={cur.status === "current"} refresh={plan.refresh} />
          <div className="cal-blocks-head pix"><span className="tick" />BLOCKS</div>
          <div className="cal-blocks-hint">tap a block, then a week</div>
          <Blocks weeks={plan.weeks} />
        </div>
      )}

      <div className="panel">
        <h2>Season settings</h2>
        <SeasonForm season={data.season} onSaved={load} />
        {data.season && (
          <>
            <div className="cal-sub">Goal events</div>
            {data.events.map((e) => (
              <div className="cal-row" key={e.id}>
                <span className={"prio prio-" + e.priority}>{e.priority}</span>
                <b>{e.name}</b> <span className="muted">{e.event_date} · {e.event_type.replace(/_/g, " ")}</span>
                <button className="del" onClick={async () => { await fetch(`/api/season/event/${e.id}`, { method: "DELETE" }); load(); }}>×</button>
              </div>
            ))}
            <EventForm eventTypes={eventTypes} onAdded={load} />
            {data.unavailable.length > 0 && (
              <>
                <div className="cal-sub">Unavailable</div>
                {data.unavailable.map((u) => (
                  <div className="cal-row" key={u.id}>
                    <span className="muted">{u.start_date} → {u.end_date} · {u.reason || "blocked"}</span>
                    <button className="del" onClick={async () => { await fetch(`/api/season/unavailable/${u.id}`, { method: "DELETE" }); load(); }}>×</button>
                  </div>
                ))}
              </>
            )}
          </>
        )}
      </div>

      {!data.season && <div className="panel empty-ok">Add a season above to generate your plan.</div>}
      {data.season && !plan && <div className="panel">Add at least one goal event to generate the plan.</div>}

      {adjustments.length > 0 && (
        <div className="panel">
          <h2>Plan adjustments</h2>
          <p className="muted small">Diary-driven changes you confirmed. Undo restores the plan; the entry stays as history.</p>
          {adjustments.map((a) => (
            <div className={"adj-row" + (a.active ? "" : " inactive")} key={a.id}>
              <span className={"adj-dot " + (a.active ? "on" : "off")} />
              <span className="adj-sum">{a.summary}</span>
              <span className="muted small">{a.created_at.slice(0, 10)}</span>
              {a.active ? <button className="del" onClick={() => undoAdjustment(a.id)}>undo</button>
                : <span className="muted small adj-tag">reverted</span>}
            </div>
          ))}
        </div>
      )}
      </>)}
    </div>
  );
}
