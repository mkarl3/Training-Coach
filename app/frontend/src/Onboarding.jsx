import React, { useEffect, useRef, useState } from "react";
import Dialogue from "./Dialogue.jsx";
import { moodFromStatus } from "./Wattson.jsx";

// Linear intake flow. Wattson (via <Dialogue>) frames each step; the forms stay clinical
// (Outfit labels, Plex Mono numbers). Each step persists to its existing endpoint as we go —
// no backend changes. The first-read text is backend-generated and grounded; we render it as-is.

const STEP = { INTRO: 0, PROFILE: 1, UPLOAD: 2, GOALS: 3, LIFE: 4, READ: 5 };
const CATEGORIES = ["injury", "illness", "life", "travel", "equipment", "other"];
const GENERAL_GOALS = ["durability", "sustained_threshold", "anaerobic", "balanced"];

// Resume: derive the starting step from the status flags so a mid-flow reload lands correctly.
function stepFromStatus(s) {
  if (!s) return STEP.INTRO;
  if (!s.has_profile) return STEP.INTRO;
  if (!(s.has_data && s.months_of_history >= 12)) return STEP.UPLOAD;
  if (!s.has_season_or_goal) return STEP.GOALS;
  return STEP.LIFE;                       // everything required is done -> optional life events, then read
}

async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const out = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(out.detail || "request failed");
  return out;
}

export default function Onboarding({ initialStatus, onComplete }) {
  const [step, setStep] = useState(() => stepFromStatus(initialStatus));
  const total = 6;

  return (
    <div className="onboarding">
      <div className="ob-shell">
        <div className="ob-bar">
          <span className="wordmark">WATT SMITH</span>
          <span className="ob-progress">STEP {Math.min(step + 1, total)} / {total}</span>
        </div>
        {step === STEP.INTRO && <Intro onNext={() => setStep(STEP.PROFILE)} />}
        {step === STEP.PROFILE && <ProfileStep onNext={() => setStep(STEP.UPLOAD)} />}
        {step === STEP.UPLOAD && <UploadStep onNext={() => setStep(STEP.GOALS)} />}
        {step === STEP.GOALS && <GoalsStep onNext={() => setStep(STEP.LIFE)} />}
        {step === STEP.LIFE && <LifeStep onNext={() => setStep(STEP.READ)} />}
        {step === STEP.READ && <FirstReadStep onComplete={onComplete} />}
      </div>
    </div>
  );
}

function Card({ children }) {
  return <div className="ob-card pbox-light">{children}</div>;
}

// ---- 1. intro ----
function Intro({ onNext }) {
  return (
    <>
      <Dialogue mood="calm"
        text="I'm Coach Wattson. I read your numbers and tell you straight — no hype, no fluff. Give me a few minutes to learn your history and we'll get to work."
        cta={<button className="btn btn-primary" onClick={onNext}>Start</button>} />
    </>
  );
}

// ---- 2. profile ----
function ProfileStep({ onNext }) {
  const [f, setF] = useState({ name: "", birth_year: "", units: "imperial",
    week_starts_on: "monday", weight_kg: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));
  async function save() {
    setBusy(true); setErr(null);
    try {
      await postJSON("/api/profile", { updates: f });
      onNext();
    } catch (e) { setErr(String(e.message || e)); setBusy(false); }
  }
  return (
    <>
      <Dialogue mood="calm" text="First, the basics. Your age sets the masters rules I use; the rest is housekeeping." />
      <Card>
        <h3>About you</h3>
        <div className="ob-grid">
          <label><span>Name</span><input value={f.name} onChange={(e) => set("name", e.target.value)} /></label>
          <label><span>Birth year</span><input className="num" type="number" value={f.birth_year}
            placeholder="e.g. 1986" onChange={(e) => set("birth_year", e.target.value)} /></label>
          <label><span>Units</span>
            <select value={f.units} onChange={(e) => set("units", e.target.value)}>
              <option value="imperial">imperial (mi / lb)</option>
              <option value="metric">metric (km / kg)</option>
            </select></label>
          <label><span>Week starts on</span>
            <select value={f.week_starts_on} onChange={(e) => set("week_starts_on", e.target.value)}>
              <option value="monday">Monday</option>
              <option value="sunday">Sunday</option>
            </select></label>
          <label><span>Weight (kg)</span><input className="num" type="number" step="0.1" value={f.weight_kg}
            placeholder="optional" onChange={(e) => set("weight_kg", e.target.value)} /></label>
        </div>
        {err && <div className="ob-err">{err}</div>}
        <div className="ob-actions">
          <button className="btn btn-primary" onClick={save} disabled={busy}>{busy ? "Saving…" : "Continue"}</button>
        </div>
      </Card>
    </>
  );
}

// ---- 3. upload (intake mode: >=12 months enforced server-side; accepts MANY files) ----
function UploadStep({ onNext }) {
  const [state, setState] = useState("idle");   // idle | busy | done
  const [err, setErr] = useState(null);
  const [done, setDone] = useState(null);       // {data_through, months, files}
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef(null);

  async function uploadFiles(fileList) {
    const arr = [...(fileList || [])];
    if (!arr.length) return;
    setState("busy"); setErr(null);
    try {
      const body = new FormData();
      arr.forEach((f) => body.append("files", f));        // all files in one request
      const res = await fetch("/api/upload?intake=true", { method: "POST", body });
      const out = await res.json();
      if (!res.ok) throw new Error(out.detail || "upload failed");   // 422 < 12 months / rebuild fail
      const st = await fetch("/api/intake/status").then((r) => r.json());
      setDone({ data_through: out.data_through, months: st.months_of_history, files: out.files });
      setState("done");
    } catch (e2) { setErr(String(e2.message || e2)); setState("idle"); }   // stay on step; live data untouched
  }

  return (
    <>
      <Dialogue mood="calm" text="Now the tape. Drop in your WKO5 exports — all of them at once is fine (Training History, PMC, Daily TiZ across the years). I need at least 12 months to read your patterns honestly." />
      <Card>
        <h3>Training history</h3>
        <input type="file" accept=".xlsx" multiple ref={fileRef} style={{ display: "none" }}
          onChange={(e) => { uploadFiles(e.target.files); e.target.value = ""; }} />
        <div className={"ob-drop" + (dragging ? " over" : "")}
          onClick={() => state !== "busy" && fileRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => { e.preventDefault(); setDragging(false); uploadFiles(e.dataTransfer.files); }}>
          {state === "busy"
            ? "Ingesting…"
            : "Drop your WKO5 .xlsx files here — or click to choose (select multiple)"}
        </div>
        {err && <div className="ob-err">⚠ {err}</div>}
        {done && (
          <div className="ob-stat">
            <div><span className="k">FILES</span><span className="v">{done.files?.length ?? 0}</span></div>
            <div><span className="k">DATA THROUGH</span><span className="v">{done.data_through}</span></div>
            <div><span className="k">HISTORY</span><span className="v">{done.months} mo</span></div>
          </div>
        )}
        <div className="ob-actions">
          <button className="btn btn-primary" onClick={onNext} disabled={state !== "done"}>Continue</button>
        </div>
      </Card>
    </>
  );
}

// ---- 4. goals: season + events, or a general-goal direction when there's no race ----
function GoalsStep({ onNext }) {
  const [season, setSeason] = useState({ name: "2026 Season", start_date: "", weekly_hours_budget: 7 });
  const [savedSeason, setSavedSeason] = useState(false);
  const [eventTypes, setEventTypes] = useState([]);
  const [events, setEvents] = useState([]);
  const [ev, setEv] = useState({ name: "", event_date: "", priority: "A", event_type: "" });
  const [goal, setGoal] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    fetch("/api/season").then((r) => r.json()).then((d) => {
      setEventTypes(d.event_types || []);
      setEv((s) => ({ ...s, event_type: (d.event_types || [])[0] || "" }));
      if (d.season) { setSeason((s) => ({ ...s, ...d.season })); setSavedSeason(true); setEvents(d.events || []); }
    }).catch(() => {});
  }, []);

  async function saveSeason(extra = {}) {
    setErr(null);
    try {
      await postJSON("/api/season", { ...season, weekly_hours_budget: Number(season.weekly_hours_budget), ...extra });
      setSavedSeason(true);
    } catch (e) { setErr(String(e.message || e)); }
  }
  async function addEvent() {
    try {
      await postJSON("/api/season/event", ev);
      setEvents((es) => [...es, { ...ev }]); setEv({ ...ev, name: "", event_date: "" });
    } catch (e) { setErr(String(e.message || e)); }
  }
  async function pickGoal(g) {
    setGoal(g);
    await saveSeason({ general_goal: g });        // persist direction on the season (no A-race needed)
  }

  return (
    <>
      <Dialogue mood="calm" text="What are we pointing at? Add your races — the A-race is the one we peak for. No date yet? Pick a direction and I'll bias the work that way." />
      <Card>
        <h3>Season</h3>
        <div className="ob-grid">
          <label><span>Start date</span><input type="date" value={season.start_date}
            onChange={(e) => setSeason({ ...season, start_date: e.target.value })} /></label>
          <label><span>Weekly hours available</span><input className="num" type="number" step="0.5"
            value={season.weekly_hours_budget}
            onChange={(e) => setSeason({ ...season, weekly_hours_budget: e.target.value })} /></label>
        </div>
        <div className="ob-actions">
          <button className="btn btn-secondary" onClick={() => saveSeason()} disabled={!season.start_date}>
            {savedSeason ? "Season saved ✓" : "Save season"}
          </button>
        </div>

        {savedSeason && (
          <>
            <h3>Target events</h3>
            {events.map((e, i) => (
              <div className="ob-row" key={i}>
                <span className={"prio prio-" + e.priority}>{e.priority}</span>
                <b>{e.name}</b> <span className="muted">{e.event_date} · {String(e.event_type).replace(/_/g, " ")}</span>
              </div>
            ))}
            <div className="ob-eventform">
              <input placeholder="event name" value={ev.name} onChange={(e) => setEv({ ...ev, name: e.target.value })} />
              <input type="date" value={ev.event_date} onChange={(e) => setEv({ ...ev, event_date: e.target.value })} />
              <select value={ev.priority} onChange={(e) => setEv({ ...ev, priority: e.target.value })}>
                {["A", "B", "C"].map((p) => <option key={p}>{p}</option>)}
              </select>
              <select value={ev.event_type} onChange={(e) => setEv({ ...ev, event_type: e.target.value })}>
                {eventTypes.map((t) => <option key={t} value={t}>{t.replace(/_/g, " ")}</option>)}
              </select>
              <button className="btn btn-ghost" onClick={addEvent} disabled={!ev.name || !ev.event_date}>+ add</button>
            </div>

            {events.length === 0 && (
              <>
                <h3>…or a season direction (no race yet)</h3>
                <p className="ob-hint">No dated A-race means no dated plan — that's fine. Pick the emphasis and I'll shape the base/build around it.</p>
                <div className="ob-chips">
                  {GENERAL_GOALS.map((g) => (
                    <button key={g} className={"chip-btn" + (goal === g ? " on" : "")} onClick={() => pickGoal(g)}>
                      {g.replace(/_/g, " ")}
                    </button>
                  ))}
                </div>
              </>
            )}
          </>
        )}
        {err && <div className="ob-err">{err}</div>}
        <div className="ob-actions">
          <button className="btn btn-primary" onClick={onNext}
            disabled={!savedSeason || (events.length === 0 && !goal)}>Continue</button>
        </div>
      </Card>
    </>
  );
}

// ---- 5. life events (skippable) — simple date-range form ----
function LifeStep({ onNext }) {
  const [items, setItems] = useState([]);
  const [f, setF] = useState({ start_date: "", end_date: "", category: "injury", note: "" });
  const [err, setErr] = useState(null);
  async function add() {
    setErr(null);
    try {
      await postJSON("/api/life-event", { ...f, end_date: f.end_date || null });
      setItems((xs) => [...xs, { ...f }]); setF({ start_date: "", end_date: "", category: "injury", note: "" });
    } catch (e) { setErr(String(e.message || e)); }
  }
  return (
    <>
      <Dialogue mood="calm" text="Anything the numbers can't see? Injuries, illness, a newborn, a bad travel stretch — tag the dates so I don't misread a dip as a choice." />
      <Card>
        <h3>Life events <span className="ob-opt">optional</span></h3>
        {items.map((it, i) => (
          <div className="ob-row" key={i}>
            <span className="cat-tag">{it.category}</span>
            <span className="muted">{it.start_date}{it.end_date ? ` → ${it.end_date}` : ""}</span>
            {it.note && <span className="muted"> · {it.note}</span>}
          </div>
        ))}
        <div className="ob-grid">
          <label><span>Start date</span><input type="date" value={f.start_date}
            onChange={(e) => setF({ ...f, start_date: e.target.value })} /></label>
          <label><span>End date (optional)</span><input type="date" value={f.end_date}
            onChange={(e) => setF({ ...f, end_date: e.target.value })} /></label>
          <label><span>Category</span>
            <select value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>
              {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
            </select></label>
          <label><span>Note</span><input value={f.note} placeholder="optional"
            onChange={(e) => setF({ ...f, note: e.target.value })} /></label>
        </div>
        {err && <div className="ob-err">{err}</div>}
        <div className="ob-actions">
          <button className="btn btn-ghost" onClick={add} disabled={!f.start_date}>+ add event</button>
          <button className="btn btn-primary" onClick={onNext}>{items.length ? "Continue" : "Skip"}</button>
        </div>
      </Card>
    </>
  );
}

// ---- 6. first read — the payoff. Backend-generated, grounded; rendered as-is. ----
function FirstReadStep({ onComplete }) {
  const [text, setText] = useState(null);
  const [mood, setMood] = useState("calm");
  const [err, setErr] = useState(null);
  useEffect(() => {
    (async () => {
      try {
        const meta = await fetch("/api/meta").then((r) => r.json());
        setMood(moodFromStatus(meta.board_status));
        const out = await postJSON("/api/coach/first-read", {});
        setText(out.reply);
      } catch (e) { setErr(String(e.message || e)); }
    })();
  }, []);
  return (
    <>
      {text == null && !err && (
        <Dialogue mood="calm" text="Give me a second — reading your numbers…" />
      )}
      {err && <Card><div className="ob-err">⚠ {err}</div>
        <div className="ob-actions"><button className="btn btn-primary" onClick={onComplete}>Enter dashboard</button></div></Card>}
      {text != null && (
        <Dialogue mood={mood} text={text}
          cta={<button className="btn btn-primary" onClick={onComplete}>Enter dashboard</button>} />
      )}
    </>
  );
}
