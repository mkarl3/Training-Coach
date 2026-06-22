import React, { useEffect, useState } from "react";

// Slice 5 — dashboard phase-progress card. Reads /api/progression (advises, never recomputes),
// renders the gate + confidence + verdict + Wattson's beat-2 read. On a HOLD it offers the
// confirm-then-apply action (POST /api/progression/hold → recompute, undoable); on ADVANCE it
// routes to the check-in for beats 3-4. NES chrome via the pixel font; numbers stay mono (ONE RULE).

const VERDICT = {
  ADVANCE: { label: "READY TO ADVANCE", cls: "adv" },
  HOLD: { label: "HOLD", cls: "hold" },
  NEEDS_BENCHMARK: { label: "NEEDS A BENCHMARK", cls: "bench" },
  PROCEED_WITH_DEBT: { label: "PROCEED · RACE CLOCK", cls: "bench" },
  BACK_OFF: { label: "BACK OFF", cls: "back" },
  NOT_STARTED: { label: "NOT STARTED", cls: "idle" },
  ON_TRACK: { label: "ON TRACK", cls: "idle" },
  IN_PROGRESS: { label: "IN PROGRESS", cls: "idle" },
  CALENDAR: { label: "TIMED TO YOUR RACE", cls: "cal" },
};
const CONF = { fresh: "fresh", aging: "aging", stale: "stale", none: "no data" };

function FuBar({ value }) {
  const pos = Math.max(0, Math.min(100, ((value - 70) / 20) * 100));
  const band0 = ((81 - 70) / 20) * 100, band1 = ((85 - 70) / 20) * 100;
  return (
    <div className="pm-bar">
      <div className="pm-track" />
      <div className="pm-zone" style={{ left: band0 + "%", width: band1 - band0 + "%" }} />
      <div className="pm-mark" style={{ left: pos + "%" }} />
    </div>
  );
}

export default function PhaseProgress({ meta, onCheckIn, onPlanChange }) {
  const [p, setP] = useState(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [held, setHeld] = useState(null);   // { applied, adjustment_id } after a hold

  const load = () => fetch("/api/progression").then((r) => r.json()).then(setP).catch(() => {});
  useEffect(() => { load(); }, [meta]);
  if (!p || p.state !== "ok") return null;

  const v = VERDICT[p.verdict] || { label: p.verdict, cls: "idle" };
  const g = p.gate || {};
  const hasFu = typeof g.value === "number";
  const isHold = p.verdict === "HOLD" || p.verdict === "PROCEED_WITH_DEBT";
  const showAdvance = p.verdict === "ADVANCE";

  async function doHold() {
    setBusy(true);
    try {
      const r = await fetch("/api/progression/hold", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ block: p.block, weeks: 1 }),
      });
      const j = await r.json();
      if (r.ok) { setHeld(j); setConfirming(false); onPlanChange && onPlanChange(); load(); }
    } finally { setBusy(false); }
  }
  async function undoHold() {
    if (!held) return;
    await fetch(`/api/plan/adjustment/${held.adjustment_id}/undo`, { method: "POST" }).catch(() => {});
    setHeld(null); onPlanChange && onPlanChange(); load();
  }

  return (
    <div className="panel phase-card">
      <div className="phase-head">
        <span className="pix phase-tag">PHASE PROGRESS</span>
        <span className="phase-transition">{p.block}{p.next_block ? ` → ${p.next_block}` : ""}</span>
        <span className={"phase-verdict " + v.cls}>{v.label}</span>
      </div>

      <div className="phase-read"><span className="phase-coach">COACH WATTSON</span> {p.headline}</div>

      <div className="phase-metrics">
        {hasFu ? (
          <div className="pmetric wide">
            <div className="pm-top">
              <span className="pm-lab">{g.name}</span>
              {g.confidence && <span className={"conf " + g.confidence}>{CONF[g.confidence]}</span>}
            </div>
            <div className="pm-val">{g.value}%<span className="pm-target"> · target {g.target}</span></div>
            <FuBar value={g.value} />
            {g.detail && <div className="pm-sub">mFTP {g.detail.mftp} / VO2 power {g.detail.vo2_power} (5-min, {g.detail.vo2_date})</div>}
          </div>
        ) : (
          <>
            <div className="pmetric">
              <div className="pm-lab">Fitness trend</div>
              <div className="pm-val">{p.ctl_change_28d == null ? "—" : (p.ctl_change_28d >= 0 ? "+" : "") + p.ctl_change_28d}</div>
              <div className="pm-sub">/ 28 days</div>
            </div>
            <div className="pmetric">
              <div className="pm-lab">Consistency</div>
              <div className="pm-val">{p.compliance == null ? "—" : Math.round(p.compliance * 100) + "%"}</div>
              <div className="pm-sub">vs planned</div>
            </div>
            <div className="pmetric">
              <div className="pm-lab">Block week</div>
              <div className="pm-val">{p.weeks_elapsed}/{p.weeks_in_block}</div>
              <div className="pm-sub">{p.min_weeks_met ? "min met" : "min " + p.min_weeks}</div>
            </div>
          </>
        )}
      </div>

      <div className="phase-action">
        {p.this_week_test && <span className="phase-test"><i className="ti ti-arrow-right" aria-hidden="true" /> {p.this_week_test}</span>}
        {held ? (
          <span className="phase-held">✓ {held.applied} — plan recomputed
            <button className="phase-link" onClick={undoHold}>undo</button></span>
        ) : isHold ? (
          confirming ? (
            <span className="phase-confirm">Hold {p.block} a week? <span className="muted">(shortens a later block)</span>
              <button className="phase-btn primary" disabled={busy} onClick={doHold}>{busy ? "…" : "Hold"}</button>
              <button className="phase-btn ghost" onClick={() => setConfirming(false)}>cancel</button></span>
          ) : (
            <button className="phase-btn primary" onClick={() => setConfirming(true)}>Hold {p.block} a week</button>
          )
        ) : showAdvance ? (
          <button className="phase-btn primary" onClick={onCheckIn}>Advance to {p.next_block} →</button>
        ) : (
          <button className="phase-btn ghost" onClick={onCheckIn}>Discuss in check-in</button>
        )}
      </div>
    </div>
  );
}
