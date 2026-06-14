import React, { useEffect, useRef, useState } from "react";
import Watchman from "./Watchman.jsx";
import Coach from "./Coach.jsx";
import Profile from "./Profile.jsx";
import Calendar from "./Calendar.jsx";
import CoachWattson, { moodFor } from "./CoachWattson.jsx";

const RESTING_LINE = {
  calm: "Numbers are where they should be. I'll yell if that changes.",
  approving: "That's how you do it. Keep it rolling — don't get greedy.",
  alarmed: "Something's moving in your numbers. Let's talk.",
};

// The always-present bottom bar: Wattson's portrait (mood = board state), his latest line,
// and a press-start cue. Click anywhere to open the dialogue drawer.
function CoachBar({ status, onOpen }) {
  const [brief, setBrief] = useState(null);
  useEffect(() => {
    fetch("/api/coach/weekly-briefing").then((r) => r.json()).then(setBrief).catch(() => {});
  }, []);
  const rising = brief?.pmc?.ctl?.dir_7d === "up";
  const mood = moodFor(brief?.status || status, rising);
  return (
    <button className="coachbar" onClick={onOpen} aria-label="Talk to Coach Wattson">
      <div className="coachbar-port"><CoachWattson mood={mood} variant="head" /></div>
      <div className="coachbar-txt">
        <span className="who">Coach Wattson</span>
        <p>{RESTING_LINE[mood]}</p>
      </div>
      <span className="coachbar-cue">▲ PRESS TO TALK</span>
    </button>
  );
}

export default function App() {
  const [meta, setMeta] = useState(null);
  const [err, setErr] = useState(null);
  const [upload, setUpload] = useState({ state: "idle", msg: "" });
  const [dataKey, setDataKey] = useState(0); // bump to remount dashboard after a data refresh
  const [planKey, setPlanKey] = useState(0); // bump to remount the calendar after a plan change
  const [showProfile, setShowProfile] = useState(false);
  const [coachOpen, setCoachOpen] = useState(false);
  const [view, setView] = useState("dashboard");  // "dashboard" | "calendar"
  const fileRef = useRef(null);

  async function refreshAfterProfile() {
    const mt = await fetch(`/api/meta`).then((r) => r.json());
    setMeta(mt);
    setDataKey((k) => k + 1);
    setShowProfile(false);
  }

  useEffect(() => {
    fetch(`/api/meta`).then((r) => r.json()).then(setMeta).catch((e) => setErr(String(e)));
  }, []);

  async function onFile(e) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    setUpload({ state: "busy", msg: `Ingesting ${f.name}…` });
    try {
      const body = new FormData();
      body.append("file", f);
      const res = await fetch(`/api/upload`, { method: "POST", body });
      const out = await res.json();
      if (!res.ok) throw new Error(out.detail || "upload failed");
      const mt = await fetch(`/api/meta`).then((r) => r.json());
      setMeta(mt);
      setDataKey((k) => k + 1);
      setUpload({ state: "ok", msg: `Updated — data now through ${out.data_through}.` });
      setTimeout(() => setUpload({ state: "idle", msg: "" }), 6000);
    } catch (e2) {
      setUpload({ state: "err", msg: String(e2.message || e2) });
    }
  }

  if (err)
    return (
      <div className="shell">
        <div className="appbar"><h1>WATT SMITH</h1></div>
        <p className="err">API error: {err}. Is the backend running on :8000?</p>
      </div>
    );
  if (!meta)
    return (
      <div className="shell">
        <div className="appbar"><h1>WATT SMITH</h1></div>
        <p style={{ color: "var(--ink-2)", padding: 14 }}>Loading…</p>
      </div>
    );

  return (
    <div className="shell">
      <div className="appbar">
        <h1>WATT SMITH <small>data through {meta.date_max}</small></h1>
        <div className="tabs">
          <button className={view === "dashboard" ? "tab on" : "tab"} onClick={() => setView("dashboard")}>Dashboard</button>
          <button className={view === "calendar" ? "tab on" : "tab"} onClick={() => setView("calendar")}>Calendar</button>
        </div>
        <div className="appbar-actions">
          {upload.msg && <span className={"upload-msg " + upload.state}>{upload.msg}</span>}
          <input type="file" accept=".xlsx" ref={fileRef} onChange={onFile} style={{ display: "none" }} />
          <button className="update-btn" onClick={() => setShowProfile(true)}>⚙ Profile</button>
          <button className="update-btn" disabled={upload.state === "busy"} onClick={() => fileRef.current?.click()}>
            {upload.state === "busy" ? "Updating…" : "↑ Load data"}
          </button>
          <span className={"pill " + meta.board_status}>{meta.board_status}</span>
        </div>
      </div>

      {showProfile && <Profile onClose={() => setShowProfile(false)} onSaved={refreshAfterProfile} />}

      <div className="main">
        {view === "dashboard"
          ? <Watchman key={"w" + dataKey} meta={meta} />
          : <Calendar key={"cal" + dataKey + "-" + planKey} />}
      </div>

      <CoachBar key={"bar" + dataKey + "-" + planKey} status={meta.board_status} onOpen={() => setCoachOpen(true)} />

      {coachOpen && (
        <>
          <div className="coach-scrim" onClick={() => setCoachOpen(false)} />
          <div className="coach-drawer">
            <Coach key={"c" + dataKey} meta={meta}
              onPlanChanged={() => setPlanKey((k) => k + 1)}
              onClose={() => setCoachOpen(false)} />
          </div>
        </>
      )}
    </div>
  );
}
