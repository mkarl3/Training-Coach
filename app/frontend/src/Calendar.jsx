import React, { useEffect, useState } from "react";

const PHASE_COLOR = { base: "#3a6ad8", build: "#4ac94a", peak: "#f7d51d", taper: "#5e6e96" };

function CtlChart({ weeks, meta }) {
  const W = 820, H = 150, pad = { l: 28, r: 10, t: 10, b: 18 };
  if (!weeks.length) return null;
  const ctls = weeks.flatMap((w) => [w.ctl_start, w.ctl_target]);
  const ymin = Math.min(...ctls, 0), ymax = Math.max(...ctls, meta.target_peak_ctl, 10);
  const xs = (i) => pad.l + (i * (W - pad.l - pad.r)) / Math.max(1, weeks.length - 1);
  const ys = (v) => pad.t + ((ymax - v) * (H - pad.t - pad.b)) / (ymax - ymin);
  const line = weeks.map((w, i) => `${xs(i).toFixed(1)},${ys(w.ctl_target).toFixed(1)}`).join(" ");
  const actual = weeks.map((w, i) => (w.actual_ctl != null ? `${xs(i).toFixed(1)},${ys(w.actual_ctl).toFixed(1)}` : null)).filter(Boolean).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%">
      {/* phase bands */}
      {weeks.map((w, i) => (
        <rect key={i} x={xs(i) - (W - pad.l - pad.r) / weeks.length / 2} y={pad.t}
          width={(W - pad.l - pad.r) / weeks.length} height={H - pad.t - pad.b}
          fill={PHASE_COLOR[w.family]} opacity={w.is_recovery ? 0.05 : 0.12} />
      ))}
      {/* target + floor reference lines */}
      <line x1={pad.l} x2={W - pad.r} y1={ys(meta.target_peak_ctl)} y2={ys(meta.target_peak_ctl)}
        stroke="#e84444" strokeDasharray="4 3" />
      <text x={W - pad.r} y={ys(meta.target_peak_ctl) - 3} fontSize="9" fill="#e84444" textAnchor="end">
        target {meta.target_peak_ctl}
      </text>
      <polyline points={line} fill="none" stroke="#4ac94a" strokeWidth="2.5" strokeLinejoin="round"
        strokeDasharray="5 3" />
      {actual && (
        <polyline points={actual} fill="none" stroke="#e84444" strokeWidth="2.5" strokeLinejoin="round" />
      )}
      {weeks.map((w, i) => (
        <circle key={i} cx={xs(i)} cy={ys(w.ctl_target)} r={w.is_recovery ? 3 : 2.5}
          fill={w.is_recovery ? "#fff" : "#4ac94a"} stroke="#4ac94a" />
      ))}
      {weeks.map((w, i) => (w.actual_ctl != null ? (
        <circle key={"a" + i} cx={xs(i)} cy={ys(w.actual_ctl)} r={2.5} fill="#e84444" stroke="#e84444" />
      ) : null))}
      <text x={pad.l} y={pad.t + 8} fontSize="9" fill="#4ac94a">— — planned</text>
      {actual && <text x={pad.l + 70} y={pad.t + 8} fontSize="9" fill="#e84444">—— actual</text>}
      {[ymin, Math.round((ymin + ymax) / 2), ymax].map((v, n) => (
        <text key={n} x="2" y={ys(v) + 3} fontSize="9" fill="var(--muted)">{Math.round(v)}</text>
      ))}
    </svg>
  );
}

function SeasonForm({ season, eventTypes, onSaved }) {
  const [name, setName] = useState(season?.name || "2026 Season");
  const [start, setStart] = useState(season?.start_date || "");
  const [hours, setHours] = useState(season?.weekly_hours_budget || 7);
  async function save() {
    await fetch("/api/season", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, start_date: start, weekly_hours_budget: Number(hours) }),
    });
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
    const r = await fetch("/api/season/event", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(f),
    });
    if (r.ok) { setF({ ...f, name: "", event_date: "" }); onAdded(); }
  }
  return (
    <div className="cal-form wrap">
      <input placeholder="event name" value={f.name} onChange={(e) => set("name", e.target.value)} />
      <input type="date" value={f.event_date} onChange={(e) => set("event_date", e.target.value)} />
      <select value={f.priority} onChange={(e) => set("priority", e.target.value)}>
        {["A", "B", "C"].map((p) => <option key={p}>{p}</option>)}
      </select>
      <select value={f.event_type} onChange={(e) => set("event_type", e.target.value)}>
        {eventTypes.map((t) => <option key={t} value={t}>{t.replace(/_/g, " ")}</option>)}
      </select>
      <button onClick={add} disabled={!f.name || !f.event_date}>+ event</button>
    </div>
  );
}

export default function Calendar() {
  const [data, setData] = useState(null);   // /api/season
  const [plan, setPlan] = useState(null);
  const [adjustments, setAdjustments] = useState([]);
  const [loading, setLoading] = useState(true);

  async function load() {
    const [s, p, a] = await Promise.all([
      fetch("/api/season").then((r) => r.json()),
      fetch("/api/plan").then((r) => r.json()),
      fetch("/api/plan/adjustments").then((r) => r.json()).catch(() => ({ adjustments: [] })),
    ]);
    setData(s); setPlan(p.error ? null : p); setAdjustments(a.adjustments || []); setLoading(false);
  }
  async function undoAdjustment(id) {
    await fetch(`/api/plan/adjustment/${id}/undo`, { method: "POST" }).catch(() => {});
    load();
  }
  useEffect(() => { load(); }, []);

  if (loading) return <div className="panel">Loading calendar…</div>;
  const eventTypes = data.event_types;

  return (
    <div>
      <div className="panel">
        <h2>Season setup</h2>
        <SeasonForm season={data.season} eventTypes={eventTypes} onSaved={load} />
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
      {data.season && !plan && (
        <div className="panel">Add at least one goal event to generate the plan.</div>
      )}

      {plan && (
        <div className="panel">
          <h2>Plan — backward from your A-race</h2>
          <div className="plan-meta">
            <b>{plan.meta.a_race.name}</b> · {plan.meta.a_race.date} ·{" "}
            <span className="muted">{plan.meta.a_race.emphasis} · {plan.meta.distribution_rx}</span>
            <div className="muted">
              {plan.meta.weeks} wks · base {plan.meta.family_weeks.base} / build {plan.meta.family_weeks.build} /
              peak {plan.meta.family_weeks.peak} / taper {plan.meta.family_weeks.taper} ·
              {plan.meta.masters ? " masters · " : " "}{plan.meta.weekly_hours_budget} h/wk · ramp cap {plan.meta.ramp_cap}/wk ·
              weeks start {plan.meta.week_starts_on === "sunday" ? "Sun" : "Mon"}
            </div>
          </div>
          {!plan.meta.target_reached && (
            <div className="honest">
              ⚠ Honest miss: in {plan.meta.weeks} weeks at {plan.meta.weekly_hours_budget} h/wk you reach
              CTL ~{plan.meta.peak_ctl_achieved}, short of the {plan.meta.target_peak_ctl} target. More time
              or hours would close it — the plan won't pretend otherwise.
            </div>
          )}
          <CtlChart weeks={plan.weeks} meta={plan.meta} />
          <table className="plan-table">
            <thead><tr>
              <th>wk</th><th>week of</th><th>block</th><th>CTL</th><th>ramp</th>
              <th>TSS (plan / actual)</th><th>ride cap</th><th>hrs</th><th>long</th><th>rule / caps</th>
            </tr></thead>
            <tbody>
              {plan.weeks.map((w) => (
                <tr key={w.week} className={[w.is_recovery ? "rec" : "", w.status === "current" ? "now" : "", w.status === "elapsed" ? "past" : ""].join(" ").trim()}>
                  <td>{w.week}{w.field_test ? <span className="ft" title="field-test week (last of block)">⚑</span> : null}</td>
                  <td className="num">{w.week_start}</td>
                  <td><span className="dot" style={{ background: PHASE_COLOR[w.family] }} />{w.block}
                    <div className="muted small">{w.focus}</div></td>
                  <td className="num">{w.ctl_start}→{w.ctl_target}</td>
                  <td className="num">{w.planned_ramp > 0 ? "+" : ""}{w.planned_ramp}</td>
                  <td className="num">{w.weekly_tss_target}
                    {w.actual_tss != null && <> / <span className={"act " + (w.actual_tss >= w.weekly_tss_target ? "hi" : "lo")}>{w.actual_tss}</span></>}
                  </td>
                  <td className="num" title="50% rule: no single ride above this">≤{w.single_ride_tss_cap}</td>
                  <td className="num">{w.est_hours}</td>
                  <td className="num">{w.long_ride_hours ? w.long_ride_hours + "h" : "—"}</td>
                  <td className="rule">{w.rationale}{w.constraints_fired.map((c, i) => <span className="cap" key={i}>{c}</span>)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted small">Every number is computed in code from your history + profile + season.
            Ask the coach to explain any week, or say e.g. "my race moved two weeks" to recompute.</p>
        </div>
      )}

      {adjustments.length > 0 && (
        <div className="panel">
          <h2>Plan adjustments</h2>
          <p className="muted small">Diary-driven changes you confirmed. Undo restores the plan; the
            entry stays here as history.</p>
          {adjustments.map((a) => (
            <div className={"adj-row" + (a.active ? "" : " inactive")} key={a.id}>
              <span className={"adj-dot " + (a.active ? "on" : "off")} />
              <span className="adj-sum">{a.summary}</span>
              <span className="muted small">{a.created_at.slice(0, 10)}</span>
              {a.active
                ? <button className="del" onClick={() => undoAdjustment(a.id)}>undo</button>
                : <span className="muted small adj-tag">reverted</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
