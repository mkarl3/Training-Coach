import React, { useEffect, useRef, useState } from "react";
import Wattson, { VB_HEAD, moodFromStatus } from "./Wattson.jsx";

// The merged dashboard card — hero + phase fused into ONE Wattson read. The narrative carries the
// coaching (composed server-side at /api/coach/dashboard — THE ONE RULE: the UI never synthesizes
// it); the metric row stays glanceable with the vitals + a gate-aware progress visual that stands
// on its own; a reply box hands off to the full chat. Replaces HeroBar + PhaseProgress.

const FDIR = { rising: "↑", sliding: "↓", holding: "→" };
const FCOL = { rising: "var(--green)", sliding: "var(--ramp-lose)", holding: "var(--ramp-hold)" };

function Vital({ k, v, sub, col }) {
  return (
    <div className="mc-tile" style={{ borderTopColor: col || "var(--jacket)" }}>
      <div className="mc-k">{k}</div>
      <div className="mc-v" style={{ color: col || "var(--cream)" }}>{v}</div>
      {sub && <div className="mc-k" style={{ color: col }}>{sub}</div>}
    </div>
  );
}

// --- gate-aware progress visual (self-contained: shows what's measured, where you are, the goal) ---
function GateVisual({ g }) {
  if (!g || g.kind === "none") return null;

  if (g.kind === "weeks") {
    const wks = g.weeks && g.weeks.length ? g.weeks : null;
    const slots = g.min_ride_days || 4;
    const cellState = (w) => (w.complete ? "complete" : w.status === "now" ? "current"
      : w.status === "done" ? "missed" : "future");
    return (
      <div className="mc-tile gate" style={{ borderTopColor: "var(--gold)" }}>
        <div className="gate-top">
          <span className="mc-k" style={{ color: "var(--gold)" }}>Progress → {g.next_block}</span>
          <span className="mc-cap">ride {slots}+ days/wk = steady</span>
        </div>
        {wks ? (
          <div className="gw-weeks">
            {wks.map((w) => (
              <div key={w.week} className={"gw-wk " + cellState(w)}>
                <div className="gw-wk-lab">WK {w.week}{w.status === "now" && <em>now</em>}</div>
                <div className="gw-slots">
                  {Array.from({ length: slots }).map((_, s) => (
                    <i key={s} className={"gw-slot" + (s < w.ride_days ? " on" : "")} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="gw-fallback mc-cap">{g.elapsed} of {g.total} weeks</div>
        )}
        <div className="gate-foot">
          <span style={{ color: g.ramp_ok ? "var(--green)" : "var(--ramp-lose)" }}>
            <i className={"ti " + (g.ramp_ok ? "ti-trending-up" : "ti-trending-down")} aria-hidden="true" />{" "}
            fitness {g.ramp >= 0 ? "+" : ""}{g.ramp}/28d</span>
          <span className="mc-cap">→ {g.next_block}</span>
        </div>
      </div>
    );
  }

  if (g.kind === "gauge") {
    const span = (g.axis_max - g.axis_min) || 1;
    const pos = Math.max(0, Math.min(100, ((g.value - g.axis_min) / span) * 100));
    const zL = ((g.lo - g.axis_min) / span) * 100, zW = ((g.hi - g.lo) / span) * 100;
    return (
      <div className="mc-tile gate" style={{ borderTopColor: "var(--jacket)" }}>
        <div className="gate-top"><span className="mc-k" style={{ color: "var(--jacket)" }}>Progress → {g.next_block}</span>
          <span className="mc-cap">{g.metric}</span></div>
        <div className="gauge-track">
          <div className="gauge-zone" style={{ left: zL + "%", width: zW + "%" }} />
          <div className="gauge-mark" style={{ left: pos + "%" }} />
          <span className="gauge-val" style={{ left: pos + "%" }}>{g.value}%</span>
        </div>
        <div className="gate-foot">
          <span className="mc-cap">{g.axis_min}</span>
          <span className="mc-cap" style={{ color: "var(--green)" }}>{g.lo}–{g.hi} ready</span>
          <span className="mc-cap">{g.axis_max}</span>
        </div>
        {g.confidence && <div className={"gauge-conf " + g.confidence}>{g.confidence} data</div>}
      </div>
    );
  }

  if (g.kind === "benchmark") {
    return (
      <div className="mc-tile gate" style={{ borderTopColor: "var(--gold)" }}>
        <div className="gate-top"><span className="mc-k" style={{ color: "var(--gold)" }}>Progress → {g.next_block}</span>
          <span className="mc-cap">needs a fresh effort</span></div>
        <div className="gate-bench"><i className="ti ti-target" aria-hidden="true" /><span>{g.need}</span></div>
      </div>
    );
  }

  if (g.kind === "calendar") {
    return (
      <div className="mc-tile gate" style={{ borderTopColor: "var(--gold)" }}>
        <div className="gate-top"><span className="mc-k" style={{ color: "var(--gold)" }}>Progress → {g.next_block}</span>
          <span className="mc-cap">timed to your race</span></div>
        <div className="gate-bench"><i className="ti ti-flag-3" aria-hidden="true" /><span>Peak &amp; taper are counted back from race day.</span></div>
      </div>
    );
  }
  return null;
}

export default function MergedCard({ meta, onSeeWeek, onReply }) {
  const [c, setC] = useState(null);
  const [draft, setDraft] = useState("");
  const inited = useRef(false);

  useEffect(() => {
    fetch("/api/coach/dashboard").then((r) => r.json()).then(setC).catch(() => {});
  }, [meta]);

  if (!c) return <div className="panel">Loading…</div>;
  const mood = c.mood || moodFromStatus(c.status);
  const fit = c.vitals?.fitness, form = c.vitals?.form;

  function submitReply() {
    const t = draft.trim();
    if (!t) return;
    setDraft("");
    onReply?.(t);
  }

  return (
    <div className="panel merged-card">
      <div className="mc-grid">
        <div className="mc-portrait"><Wattson mood={mood} viewBox={VB_HEAD} /></div>

        <div className="mc-main">
          <div className="mc-head">
            <span className="mc-coach">COACH WATTSON</span>
            {c.block && <span className="mc-phase">{c.block}{c.next_block ? ` › ${c.next_block}` : ""}
              {c.week_in_block ? ` · WK ${c.week_in_block}/${c.weeks_in_block}` : ""}</span>}
            {c.verdict_label && <span className={"mc-verdict " + (c.verdict || "").toLowerCase()}>{c.verdict_label}</span>}
          </div>

          <p className="mc-narrative">{(c.narrative || []).join(" ")}</p>

          {fit && (
            <div className="mc-row">
              <Vital k="Fitness" v={<>{fit.value} <span className="mc-arrow">{FDIR[fit.dir]}</span></>}
                sub={fit.dir} col={FCOL[fit.dir]} />
              <Vital k="Form" v={`${form.value >= 0 ? "+" : ""}${form.value}`} sub={form.label}
                col={form.label === "run down" ? "var(--red)" : form.label === "fresh" ? "var(--tsb)" : "var(--cream)"} />
              {c.this_week_tss != null && <Vital k="This week" v={c.this_week_tss} sub="TSS" col="var(--cream)" />}
              <GateVisual g={c.gate_visual} />
            </div>
          )}

          <div className="mc-actions">
            <div className="mc-reply">
              <input value={draft} placeholder="Reply to Coach Wattson…"
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); submitReply(); } }} />
              <button onClick={submitReply} aria-label="Send reply">→</button>
            </div>
            <button className="mc-see" onClick={onSeeWeek}><i className="ti ti-calendar" aria-hidden="true" /> See this week →</button>
          </div>
        </div>
      </div>
    </div>
  );
}
