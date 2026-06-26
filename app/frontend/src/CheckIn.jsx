import React, { useCallback, useEffect, useRef, useState } from "react";
import Wattson, { VB_FULL } from "./Wattson.jsx";
import Celebration from "./Celebration.jsx";

// The Weekly Check-In — a full-screen NES "cartridge" Coach Wattson LEADS. Six rounds, each a
// screen; advancing SCROLLS DOWN to the next (Punch-Out style, slow ease). Wattson is a big sprite
// co-located with his dialogue box and the response options. THE ONE RULE holds: nostalgia in the
// chrome, the data stays clean. The UI never synthesizes coaching copy — every Wattson line and
// every number comes from the backend (upload / weekly-briefing / progression / trend / hold).

const FAM = { base: "var(--jacket)", build: "var(--green)", peak: "var(--gold)", taper: "var(--ink-3)" };
const FU_LO = 81, FU_HI = 85;   // the sourced fractional-utilization "base is maxed" band

const LEGS = [
  { key: "fresh", label: "FRESH", note: "My legs feel fresh and ready this week." },
  { key: "ok", label: "OK", note: "My legs feel okay — normal this week." },
  { key: "heavy", label: "HEAVY", note: "My legs have felt heavy this week." },
  { key: "wrecked", label: "WRECKED", note: "My legs are wrecked — I've been really fatigued this week." },
];
const flagged = (k) => k === "heavy" || k === "wrecked";

const ROUNDS = ["LOAD YOUR WEEK", "YOUR WEEK", "READY TO STEP UP?", "ADJUST", "THIS WEEK", "LOCKED IN"];

// minimal markdown for coach replies: **bold** only (kept out of the chrome — body text only)
function say(text) {
  if (!text) return null;
  return text.split(/(\*\*[^*]+\*\*)/g).map((p, i) =>
    p.startsWith("**") && p.endsWith("**") ? <b key={i}>{p.slice(2, -2)}</b> : p);
}

const moodForVerdict = (v) =>
  ["ADVANCE", "ON_TRACK", "CALENDAR", "IN_PROGRESS"].includes(v) ? "approving"
    : ["HOLD", "BACK_OFF", "NEEDS_BENCHMARK", "PROCEED_WITH_DEBT"].includes(v) ? "alarmed" : "calm";

// ---- Wattson speaking, with his options/readout beside him (no top/bottom split) ----
function Beat({ mood = "calm", birthday = false, children }) {
  return (
    <div className="ci-beat">
      <div className="ci-sprite"><Wattson mood={mood} viewBox={VB_FULL} birthday={birthday} /><div className="ci-platform" /></div>
      <div className="ci-say pbox">
        <div className="ci-who">COACH WATTSON</div>
        <div className="ci-body">{children}</div>
      </div>
    </div>
  );
}

// ---- forward fitness projection: white history + green planned (+ amber "if eased") ----
// chart-scale fix: SVG fills its flex box (preserveAspectRatio=none, 100%×100%), strokes use
// vector-effect=non-scaling-stroke, labels are crisp HTML overlays.
function ProjChart({ history, planned, eased }) {
  const t = (d) => new Date(d).getTime();
  const hist = (history || []).filter((p) => p.ctl != null);
  if (hist.length < 2) return <div className="ci-chart-empty">not enough history to chart</div>;
  const lastDate = hist[hist.length - 1].date;
  const last = hist[hist.length - 1];
  const plan = [last, ...(planned?.points || []).filter((p) => p.date > lastDate)];
  const ease = eased ? [last, ...(eased.points || []).filter((p) => p.date > lastDate)] : null;
  const all = [...hist, ...plan, ...(ease || [])];
  const xs = all.map((p) => t(p.date)), cs = all.map((p) => p.ctl);
  const xmin = Math.min(...xs), xmax = Math.max(...xs);
  const ymin = Math.max(0, Math.min(...cs) - 6), ymax = Math.max(...cs) + 6;
  const X = (d) => ((t(d) - xmin) / (xmax - xmin || 1)) * 100;
  const Y = (c) => 100 - ((c - ymin) / (ymax - ymin || 1)) * 100;
  const path = (pts) => pts.map((p) => `${X(p.date).toFixed(2)},${Y(p.ctl).toFixed(2)}`).join(" ");
  const nowX = X(lastDate);
  return (
    <div className="ci-chart">
      <span className="ci-yax ci-ymax">{Math.round(ymax)}</span>
      <span className="ci-yax ci-ymin">{Math.round(ymin)}</span>
      <span className="ci-nowlab" style={{ left: `calc(${nowX}% )` }}>now</span>
      <svg viewBox="0 0 100 100" preserveAspectRatio="none">
        <line x1={nowX} y1="0" x2={nowX} y2="100" stroke="var(--line)" strokeWidth="1"
          vectorEffect="non-scaling-stroke" strokeDasharray="3 3" />
        <polyline points={path(hist)} fill="none" stroke="var(--cream)" strokeWidth="2.5"
          vectorEffect="non-scaling-stroke" />
        <polyline points={path(plan)} fill="none" stroke="var(--green)" strokeWidth="2.5"
          strokeDasharray="5 4" vectorEffect="non-scaling-stroke" />
        {ease && <polyline points={path(ease)} fill="none" stroke="var(--gold)" strokeWidth="2.5"
          strokeDasharray="5 4" vectorEffect="non-scaling-stroke" />}
      </svg>
      <div className="ci-chart-key">
        <span><i className="k-hist" />your fitness</span>
        <span><i className="k-plan" />on plan</span>
        {ease && <span><i className="k-ease" />if eased</span>}
      </div>
    </div>
  );
}

export default function CheckIn({ meta, onClose, onPlanChanged }) {
  const [step, setStep] = useState(0);              // highest unlocked round
  const [convId, setConvId] = useState(meta?.latest_conversation_id || null);
  const [ach, setAch] = useState(null);             // pending big-ride achievement → Wattson's celebration

  useEffect(() => {                                  // greet you with the celebration if you earned one
    fetch(`/api/achievements/pending`).then((r) => r.json())
      .then((d) => setAch(d.achievement || null)).catch(() => {});
  }, []);

  function dismissAch() {                            // hide it; it'd otherwise stay until your next ride
    const id = ach?.ride_id;
    setAch(null);
    if (id) fetch(`/api/achievements/dismiss`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ride_id: String(id) }),
    }).catch(() => {});
  }

  const [loaded, setLoaded] = useState(null);       // {data_through} | "skipped"
  const [loadErr, setLoadErr] = useState(null);
  const [busy, setBusy] = useState(false);

  const [b, setB] = useState(null);                 // weekly-briefing
  const [prog, setProg] = useState(null);           // /api/progression
  const [plan, setPlan] = useState(null);           // /api/plan
  const [trend, setTrend] = useState(null);         // /api/trend (history + planned projection)

  const [legs, setLegs] = useState(null);
  const [legsReply, setLegsReply] = useState(null);

  const [preview, setPreview] = useState(null);     // hold dry-run
  const [choice, setChoice] = useState(null);       // 'eased' | 'held'
  const [easeAdj, setEaseAdj] = useState(null);     // adjustment id once a hold is applied

  const [ask, setAsk] = useState([]);               // [{role, text}]
  const [draft, setDraft] = useState("");

  const scroller = useRef(null);
  const roundRefs = useRef([]);

  const scrollToRound = useCallback((i) => {
    const cont = scroller.current, el = roundRefs.current[i];
    if (!cont || !el) return;
    const start = cont.scrollTop, end = el.offsetTop, t0 = performance.now(), dur = 1300;
    const ease = (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
    const stepFn = (now) => {
      const p = Math.min(1, (now - t0) / dur);
      cont.scrollTop = start + (end - start) * ease(p);
      if (p < 1) requestAnimationFrame(stepFn);
    };
    requestAnimationFrame(stepFn);
  }, []);

  const go = useCallback((i) => {
    setStep((s) => Math.max(s, i));
    requestAnimationFrame(() => scrollToRound(i));
  }, [scrollToRound]);

  async function loadData() {
    const [bb, pp, pl, tr] = await Promise.all([
      fetch(`/api/coach/weekly-briefing`).then((r) => r.json()).catch(() => null),
      fetch(`/api/progression`).then((r) => r.json()).catch(() => null),
      fetch(`/api/plan`).then((r) => r.json()).catch(() => null),
      fetch(`/api/trend`).then((r) => r.json()).catch(() => null),
    ]);
    setB(bb); setProg(pp); setTrend(tr);
    setPlan(pl && !pl.error ? pl : null);
  }

  async function onUpload(e) {
    const arr = [...(e.target.files || [])];
    e.target.value = "";
    if (!arr.length) return;
    setBusy(true); setLoadErr(null);
    try {
      const body = new FormData();
      arr.forEach((f) => body.append("files", f));
      const res = await fetch(`/api/upload`, { method: "POST", body });
      const out = await res.json();
      if (!res.ok) throw new Error(out.detail || "upload failed");
      await loadData();
      setLoaded({ data_through: out.data_through, files: out.files });
    } catch (e2) {
      setLoadErr(String(e2.message || e2));
    } finally {
      setBusy(false);
    }
  }

  async function skipUpload() {
    setBusy(true);
    await loadData();
    setLoaded("skipped");
    setBusy(false);
    go(1);
  }

  async function sendMessage(text) {
    const out = await fetch(`/api/coach/message`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, conversation_id: convId }),
    }).then((r) => r.json());
    if (out.conversation_id) setConvId(out.conversation_id);
    return out;
  }

  async function pickLegs(opt) {
    if (busy) return;
    setLegs(opt.key); setLegsReply(null); setBusy(true);
    try {
      const out = await sendMessage(opt.note);
      setLegsReply(out.reply || "Logged.");
    } catch {
      setLegsReply("(couldn't reach the coach — your answer was noted)");
    } finally {
      setBusy(false);
    }
  }

  // when ADJUST unlocks and the legs were flagged, dry-run the ease so we can SHOW it before committing
  const canEase = flagged(legs) && prog?.state === "ok" && !!prog?.block && !!plan;
  useEffect(() => {
    if (step < 3 || !canEase || preview) return;
    fetch(`/api/progression/hold/preview?block=${encodeURIComponent(prog.block)}&weeks=1`)
      .then((r) => r.json()).then((d) => !d.detail && setPreview(d)).catch(() => {});
  }, [step, canEase, preview, prog, plan]);

  async function easeIt() {
    if (busy) return;
    setBusy(true);
    try {
      const out = await fetch(`/api/progression/hold`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ block: prog.block, weeks: 1 }),
      }).then((r) => r.json());
      setEaseAdj(out.adjustment_id);
      setChoice("eased");
      onPlanChanged?.();
      await loadData();   // refresh plan/projection to reflect the hold
    } catch {
      setChoice(null);
    } finally {
      setBusy(false);
    }
  }

  async function undoEase() {
    if (easeAdj == null) return;
    await fetch(`/api/plan/adjustment/${easeAdj}/undo`, { method: "POST" }).catch(() => {});
    setEaseAdj(null); onPlanChanged?.();
    await loadData();
  }

  // BACK to round i: reset this screen's answer + everything downstream, then scroll up
  async function back(i) {
    if (i <= 3 && easeAdj != null) await undoEase();
    if (i <= 1) { setLegs(null); setLegsReply(null); }
    if (i <= 3) { setPreview(null); setChoice(null); }
    setStep(i);
    requestAnimationFrame(() => scrollToRound(i));
  }

  async function sendAsk() {
    const text = draft.trim();
    if (!text || busy) return;
    setDraft(""); setAsk((a) => [...a, { role: "user", text }]); setBusy(true);
    try {
      const out = await sendMessage(text);
      setAsk((a) => [...a, { role: "coach", text: out.reply || "…" }]);
    } catch {
      setAsk((a) => [...a, { role: "coach", text: "(connection error — try again)" }]);
    } finally {
      setBusy(false);
    }
  }

  // ---- derived readout values ----
  const bday = !!meta?.birthday;                    // birthday week → party hat on the check-in sprite
  const wr = b?.week_reviewed, pmc = b?.pmc, nw = b?.next_week;
  const ctlNow = pmc?.ctl?.now, ctlD = pmc?.ctl?.delta_7d;
  const streak = b?.streak ?? 0;
  const gate = prog?.gate;
  const fuPct = gate?.value;
  const cur = plan ? (plan.weeks.find((w) => w.status === "current")
    || plan.weeks.find((w) => w.status === "upcoming") || plan.weeks[0]) : null;
  const pm = plan?.meta;
  const blockWk = plan && nw
    ? plan.weeks.filter((w) => w.block === nw.block && w.week <= nw.week).length : null;

  const Nav = ({ i, label = "NEXT", mood }) => (
    <div className="ci-nav">
      {i > 0 && <button className="ci-back" onClick={() => back(i - 1)}>◀ BACK</button>}
      <button className="ci-next" onClick={() => go(i + 1)}>{label} ▼</button>
    </div>
  );

  return (
    <div className="checkin">
      <div className="ci-crt" />
      <div className="ci-bar">
        <span className="ci-title">WEEKLY CHECK-IN</span>
        <span className="ci-dots">{ROUNDS.map((_, i) =>
          <i key={i} className={i <= step ? "on" : ""} />)}</span>
        <button className="ci-close" onClick={onClose} aria-label="Close">✕</button>
      </div>

      <div className="ci-scroll" ref={scroller}>
        {ach && (
          <div style={{ maxWidth: 520, margin: "16px auto 4px", padding: "0 16px" }}>
            <Celebration flair={ach.flair} title={ach.title} subtitle={ach.subtitle} onDismiss={dismissAch} />
          </div>
        )}
        {/* ROUND 1 — LOAD YOUR WEEK */}
        <section className="ci-round" ref={(el) => (roundRefs.current[0] = el)}>
          <div className="ci-label">ROUND 1 · LOAD YOUR WEEK</div>
          <Beat birthday={bday} mood={loaded ? "approving" : "calm"}>
            {!loaded ? (
              <>
                <p>Let's load this week first — drop in your latest WKO5 export and I'll read it.</p>
                <label className="ci-btn ci-file">
                  {busy ? "Loading…" : "↑ LOAD THIS WEEK'S FILE"}
                  <input type="file" accept=".xlsx" multiple disabled={busy} onChange={onUpload} hidden />
                </label>
                <button className="ci-link" disabled={busy} onClick={skipUpload}>already synced — skip</button>
                {loadErr && <p className="ci-err">{loadErr}</p>}
              </>
            ) : (
              <>
                <p>{loaded === "skipped"
                  ? `Using what's on file — data through ${b?.as_of || meta?.date_max}.`
                  : `Loaded. Data's now through ${loaded.data_through}.`}
                  {wr?.actual_tss != null && ` That's ${wr.actual_tss} TSS in the last week.`}</p>
                <p className="muted">Let's look at how the week went.</p>
              </>
            )}
          </Beat>
          {loaded && loaded !== "skipped" && <Nav i={0} />}
        </section>

        {/* ROUND 2 — YOUR WEEK */}
        <section className="ci-round" ref={(el) => (roundRefs.current[1] = el)}>
          <div className="ci-label">ROUND 2 · YOUR WEEK</div>
          {step < 1 ? <Locked /> : (
            <>
              <div className="ci-readout">
                <div className="ci-ro-block">
                  <div className="ci-ro-h">DID YOU DO THE WORK?</div>
                  {wr?.planned_tss != null ? (
                    <div className="ci-ro-grid">
                      <Stat k="PLANNED" v={wr.planned_tss} />
                      <Stat k="YOU DID" v={wr.actual_tss} />
                      <Stat k="OF PLAN" v={`${wr.compliance_pct}%`}
                        tone={wr.compliance_pct >= 90 ? "ok" : "warn"} />
                    </div>
                  ) : (
                    <div className="ci-ro-grid">
                      <Stat k="LAST 7 DAYS" v={`${wr?.actual_tss ?? "—"} TSS`} />
                      <Stat k="PRIOR WEEK" v={`${wr?.prior_week_tss ?? "—"} TSS`} />
                    </div>
                  )}
                </div>
                <div className="ci-ro-block">
                  <div className="ci-ro-h">WHAT IT DID</div>
                  <div className="ci-ro-grid">
                    <Stat k="FITNESS" v={ctlNow != null ? (ctlD != null ? `${Math.round(ctlNow - ctlD)}→${Math.round(ctlNow)}` : Math.round(ctlNow)) : "—"} />
                    <Stat k="FORM" v={pmc?.tsb?.now ?? "—"} />
                    <Stat k="BOARD" v={(b?.status || "—").toUpperCase()}
                      tone={b?.status === "green" ? "ok" : b?.status === "alert" ? "bad" : "warn"} />
                  </div>
                </div>
              </div>
              <Beat birthday={bday} mood={legs && flagged(legs) ? "alarmed" : legs ? "approving" : "calm"}>
                {!legs ? <p>So how did your legs actually feel this week?</p>
                  : legsReply ? <p>{say(legsReply)}</p>
                  : <p className="muted">reading that against your numbers…</p>}
                <div className="ci-opts">
                  {LEGS.map((o) => (
                    <button key={o.key} disabled={busy}
                      className={"ci-opt" + (legs === o.key ? " on" : "")}
                      onClick={() => pickLegs(o)}>{o.label}</button>
                  ))}
                </div>
              </Beat>
              {legs && legsReply && <Nav i={1} />}
            </>
          )}
        </section>

        {/* ROUND 3 — READY TO STEP UP? */}
        <section className="ci-round" ref={(el) => (roundRefs.current[2] = el)}>
          <div className="ci-label">ROUND 3 · READY TO STEP UP?</div>
          {step < 2 ? <Locked /> : (
            <>
              {prog?.state === "ok" && gate ? (
                <Beat birthday={bday} mood={moodForVerdict(prog.verdict)}>
                  <p>{say(prog.headline || "")}</p>
                  {prog.transition_kind === "base_to_build" && fuPct != null ? (
                    <div className="ci-gauge">
                      <div className="ci-gauge-h">HOW BUILT-OUT IS YOUR BASE?</div>
                      <div className="ci-gauge-track">
                        <div className="ci-gauge-zone" style={{ left: `${FU_LO}%`, width: `${FU_HI - FU_LO}%` }} />
                        <div className="ci-gauge-fill" style={{ width: `${Math.min(100, fuPct)}%` }} />
                        <div className="ci-gauge-mark" style={{ left: `${Math.min(100, fuPct)}%` }} />
                      </div>
                      <div className="ci-gauge-foot">
                        <span><b>{fuPct}%</b> now</span>
                        <span className="ok">READY {FU_LO}–{FU_HI}%</span>
                        {gate.confidence && <span className={"ci-conf " + gate.confidence}>{gate.confidence} data</span>}
                      </div>
                      <p className="ci-narr">Your all-day steady power is {fuPct}% of your best 5-minute power.
                        At {FU_LO}–{FU_HI}% your base is maxed out — past that, VO2 work raises the ceiling.</p>
                    </div>
                  ) : (
                    <div className="ci-ro-grid wide">
                      <Stat k={(gate.metric || "gate").toUpperCase()} v={gate.value != null ? gate.value : "—"} />
                      {gate.compliance != null && <Stat k="COMPLIANCE" v={`${gate.compliance}%`} />}
                      {prog.ctl_change_28d != null && <Stat k="FITNESS 28d" v={`${prog.ctl_change_28d > 0 ? "+" : ""}${prog.ctl_change_28d}`} />}
                    </div>
                  )}
                  {prog.this_week_test && <p className="ci-test">This week: {prog.this_week_test}.</p>}
                </Beat>
              ) : (
                <Beat birthday={bday} mood="calm">
                  <p>{prog?.state === "no_plan"
                    ? "No season plan loaded yet — set one up and I'll start gating your phases."
                    : "Your plan hasn't started yet — nothing to step up to this week."}</p>
                </Beat>
              )}
              <Nav i={2} />
            </>
          )}
        </section>

        {/* ROUND 4 — ADJUST */}
        <section className="ci-round" ref={(el) => (roundRefs.current[3] = el)}>
          <div className="ci-label">ROUND 4 · ADJUST</div>
          {step < 3 ? <Locked /> : (
            <>
              <ProjChart history={trend?.series} planned={trend?.projection}
                eased={canEase && choice !== "eased" ? preview?.projection_eased : null} />
              {canEase ? (
                <Beat birthday={bday} mood={choice === "eased" ? "approving" : "alarmed"}>
                  {choice === "eased" ? (
                    <>
                      <p>Eased. {preview?.diff && diffSentence(preview.diff)} Backing off when you're fried is nearly free.</p>
                      <button className="ci-link" onClick={undoEase}>undo</button>
                    </>
                  ) : choice === "held" ? (
                    <p>Plan holds, then. Keep the rides honest and we'll watch the legs next week.</p>
                  ) : (
                    <>
                      <p>Your legs are flagging. I can ease this block a week — {preview?.diff ? diffSentence(preview.diff) : "you rejoin the plan shortly, peak unchanged."}</p>
                      <div className="ci-opts">
                        <button className="ci-opt ease" disabled={busy || !preview} onClick={easeIt}>EASE IT</button>
                        <button className="ci-opt" disabled={busy} onClick={() => setChoice("held")}>HOLD THE PLAN</button>
                      </div>
                    </>
                  )}
                </Beat>
              ) : (
                <Beat birthday={bday} mood="approving">
                  <p>Nothing to change — that green line is you, on plan. Keep it rolling.</p>
                </Beat>
              )}
              {(!canEase || choice) && <Nav i={3} />}
            </>
          )}
        </section>

        {/* ROUND 5 — THIS WEEK */}
        <section className="ci-round" ref={(el) => (roundRefs.current[4] = el)}>
          <div className="ci-label">ROUND 5 · THIS WEEK</div>
          {step < 4 ? <Locked /> : (
            <>
              {plan && pm && cur ? (
                <>
                  <div className="ci-posbar">
                    <div className="ci-posbar-head">
                      <span className="pix">WK {cur.week}/{pm.weeks}</span>
                      <span className="muted">{Math.max(0, pm.weeks - cur.week)} WK → RACE ◆</span>
                    </div>
                    <div className="ci-cells">
                      {plan.weeks.map((w) => (
                        <div key={w.week} className={"ci-cell" + (w.week === cur.week ? " now" : "")}
                          style={{ background: FAM[w.family] || "var(--ink-3)", opacity: w.status === "elapsed" ? 0.4 : 1 }}
                          title={`wk ${w.week} · ${w.block}`}>
                          {w.week === cur.week && <span className="ci-cell-ptr">▼</span>}
                        </div>
                      ))}
                    </div>
                  </div>
                  {nw && (
                    <div className="ci-mission">
                      <Stat k="PHASE" v={(nw.block || "—").toUpperCase()} />
                      <Stat k="BLOCK WK" v={blockWk ?? "—"} />
                      <Stat k="TARGET TSS" v={nw.weekly_tss_target} />
                      <Stat k="RIDE CAP" v={`≤${nw.single_ride_tss_cap}`} />
                      <Stat k="LONG" v={nw.long_ride_hours ? `${nw.long_ride_hours}h` : "—"} />
                    </div>
                  )}
                  {nw?.focus && <div className="ci-focus">FOCUS — {nw.focus}.{nw.field_test ? " ⚑ Field test this week." : ""}</div>}
                </>
              ) : (
                <Beat birthday={bday} mood="calm"><p>No weekly plan to brief — set up a season to get a mission here.</p></Beat>
              )}
              <Beat birthday={bday} mood="calm">
                <p>Anything you want to ask before you lock in?</p>
                {ask.map((m, i) => (
                  <p key={i} className={m.role === "user" ? "ci-ask-u" : ""}>{m.role === "coach" ? say(m.text) : m.text}</p>
                ))}
                <div className="ci-composer">
                  <input value={draft} placeholder="ask Wattson…" disabled={busy}
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); sendAsk(); } }} />
                  <button disabled={busy || !draft.trim()} onClick={sendAsk}>ASK</button>
                </div>
              </Beat>
              <Nav i={4} label="LOCK IN" />
            </>
          )}
        </section>

        {/* ROUND 6 — LOCKED IN */}
        <section className="ci-round" ref={(el) => (roundRefs.current[5] = el)}>
          <div className="ci-label">ROUND 6 · LOCKED IN</div>
          {step < 5 ? <Locked /> : (
            <>
              <Beat birthday={bday} mood="approving">
                <p>Locked in. You showed up, you read the numbers, you made the call. That's the job.</p>
                <div className="ci-streak">
                  <div className="ci-streak-h">ON-PLAN STREAK</div>
                  <div className="ci-streak-n pix">{streak + 1}</div>
                  <div className="ci-streak-s">weeks running — consistency is what builds the engine</div>
                </div>
              </Beat>
              <div className="ci-nav">
                <button className="ci-back" onClick={() => back(4)}>◀ BACK</button>
                <button className="ci-next" onClick={onClose}>DONE ✓</button>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}

function Locked() {
  return <div className="ci-locked"><span>·····</span></div>;
}

function Stat({ k, v, tone }) {
  return (
    <div className="ci-stat">
      <div className="ci-stat-k">{k}</div>
      <div className={"ci-stat-v" + (tone ? " " + tone : "")}>{v}</div>
    </div>
  );
}

// a factual sentence about the diff (data, not coaching copy) — mirrors the chat's DiffLine
function diffSentence(diff) {
  if (!diff || diff.error_new || !diff.summary) return "";
  const peak = diff.summary.peak_ctl_achieved;
  const peakBit = peak && peak[0] !== peak[1]
    ? `peak fitness ${peak[0]}→${peak[1]}` : "peak unchanged";
  return `${diff.n_changed} week${diff.n_changed === 1 ? "" : "s"} shift, ${peakBit}.`;
}
