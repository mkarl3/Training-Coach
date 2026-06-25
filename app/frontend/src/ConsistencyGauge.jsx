import React, { useEffect, useState } from "react";
import Wattson, { VB_HEAD } from "./Wattson.jsx";

// Consistency Gauge (handoff brief) — four-heart vitality readout. RENDERS ONLY: every value
// (hearts, color, mood, flag, streak, the alert numbers) comes from /api/consistency. No thresholds,
// counters, or logic here. Hearts are pixel/SVG; metric text is IBM Plex Mono (the brand split).

const HEART = ["0110110", "1111111", "1111111", "0111110", "0011100", "0001000"];  // 7×6 pixel heart

function Heart({ state }) {   // state: "empty" | "red" | "yellow" | "flash"
  const u = 3;
  return (
    <svg className={"cg-heart " + state} viewBox="0 0 21 18" width="26" height="22"
      shapeRendering="crispEdges" fill="currentColor" aria-hidden="true">
      {HEART.flatMap((row, y) => [...row].map((c, x) =>
        c === "1" ? <rect key={x + "-" + y} x={x * u} y={y * u} width={u} height={u} /> : null))}
    </svg>
  );
}

export default function ConsistencyGauge({ meta, onReply }) {
  const [g, setG] = useState(null);
  useEffect(() => { fetch("/api/consistency").then((r) => r.json()).then(setG).catch(() => {}); }, [meta]);
  if (!g) return null;

  const ev = g.source_finding?.evidence || {};
  const drop = g.source_finding?.discriminator_result?.ctl_dropped?.value;   // never recomputed here

  return (
    <div className={"panel cg" + (g.flagged ? " flag" : "")}>
      <div className="cg-row">
        <div className="cg-port"><Wattson mood={g.wattson_mood} viewBox={VB_HEAD} /></div>
        <div className="cg-mid">
          <div className="cg-label">CONSISTENCY</div>
          <div className="cg-hearts">
            {[1, 2, 3, 4].map((i) => <Heart key={i} state={i <= g.hearts ? g.heart_color : "empty"} />)}
          </div>
        </div>
        <div className="cg-streak">
          <div className="cg-streak-n">{g.clean_week_streak}</div>
          <div className="cg-streak-l">clean wk{g.clean_week_streak === 1 ? "" : "s"}</div>
        </div>
      </div>

      {g.flagged && (
        <div className="cg-alert">
          <span className="cg-alert-tag pix">⚠ CONSISTENCY FLAG</span>
          <span className="cg-alert-line">
            Off the bike <b>{ev.zero_ride_streak_days}</b> days{drop != null && <> · fitness dropped <b>{drop}</b></>}.
            That's the build-and-crash pattern — let's pull it back.
          </span>
          {onReply && (
            <button className="cg-alert-cta" onClick={() => onReply("My consistency flag is up — what do we do about the gap?")}>
              Talk to Wattson →
            </button>
          )}
        </div>
      )}
    </div>
  );
}
