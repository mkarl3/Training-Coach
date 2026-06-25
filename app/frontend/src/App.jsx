import React, { useEffect, useRef, useState } from "react";
import Watchman from "./Watchman.jsx";
import Coach from "./Coach.jsx";
import Profile from "./Profile.jsx";
import Calendar from "./Calendar.jsx";
import Onboarding from "./Onboarding.jsx";
import CheckIn from "./CheckIn.jsx";
import Wattson, { VB_HEAD, moodFromStatus } from "./Wattson.jsx";

const RESTING_LINE = {
  approving: "Numbers are where they should be. I'll yell if that changes.",
  calm: "Let's see where you stand. Open me up when you're ready.",
  alarmed: "Something's moving in your numbers. Let's talk.",
};

// Coach Wattson, always close at hand: a bottom dialogue bar (his portrait + mood + a line)
// that opens the coach chat in a drawer over the full-screen dashboard.
function CoachBar({ status, onOpen }) {
  const mood = moodFromStatus(status);
  return (
    <button className="coachbar" onClick={onOpen} aria-label="Talk to Coach Wattson">
      <div className="coachbar-port"><Wattson mood={mood} viewBox={VB_HEAD} /></div>
      <div className="coachbar-txt">
        <span className="who">Coach Wattson</span>
        <p>{RESTING_LINE[mood]}</p>
      </div>
      <span className="coachbar-cue">▲ PRESS TO TALK</span>
    </button>
  );
}

export default function App() {
  const [intake, setIntake] = useState(null);     // /api/intake/status; null = loading
  const [meta, setMeta] = useState(null);
  const [err, setErr] = useState(null);
  const [upload, setUpload] = useState({ state: "idle", msg: "" });
  const [dataKey, setDataKey] = useState(0); // bump to remount dashboard after a data refresh
  const [planKey, setPlanKey] = useState(0); // bump to remount the calendar after a plan change
  const [showProfile, setShowProfile] = useState(false);
  const [coachOpen, setCoachOpen] = useState(false);
  const [coachSeed, setCoachSeed] = useState(null);   // a reply typed on the dashboard, auto-sent on open
  const [checkinOpen, setCheckinOpen] = useState(false);
  const [view, setView] = useState("dashboard");  // "dashboard" | "calendar"
  const [ftpPending, setFtpPending] = useState(null);   // Strava-proposed FTP awaiting accept/edit/dismiss
  const [ftpPrefill, setFtpPrefill] = useState(null);   // value handed to the Profile editor on "Edit"
  const fileRef = useRef(null);

  useEffect(() => {
    (async () => {
      try {
        const st = await fetch(`/api/intake/status`).then((r) => r.json());
        setIntake(st);
        if (st.complete) {
          setMeta(await fetch(`/api/meta`).then((r) => r.json()));
          refreshFtpPending();
        }
      } catch (e) { setErr(String(e)); }
    })();
  }, []);

  async function finishOnboarding() {
    const [st, mt] = await Promise.all([
      fetch(`/api/intake/status`).then((r) => r.json()),
      fetch(`/api/meta`).then((r) => r.json()),
    ]);
    setIntake(st); setMeta(mt);
  }

  async function closeCheckin() {
    // the check-in can load data and/or apply a hold — refresh meta and remount dashboard + calendar
    setCheckinOpen(false);
    try { setMeta(await fetch(`/api/meta`).then((r) => r.json())); } catch {}
    setDataKey((k) => k + 1);
    setPlanKey((k) => k + 1);
  }

  async function refreshAfterProfile() {
    await refreshDataOnly();
    setShowProfile(false);
  }

  async function refreshDataOnly() {
    const mt = await fetch(`/api/meta`).then((r) => r.json());
    setMeta(mt);
    setDataKey((k) => k + 1);   // remount data views (FTP edit recomputes TSS without closing)
  }

  async function refreshFtpPending() {
    try {
      const d = await fetch(`/api/ftp-history`).then((r) => r.json());
      setFtpPending(d.pending ? { ...d.pending, prev: d.current } : null);
    } catch { /* ignore */ }
  }

  async function acceptFtp() {
    await fetch(`/api/ftp-history/accept-pending`, { method: "POST" }).catch(() => {});
    setFtpPending(null);
    refreshDataOnly();
  }

  function editFtp() {
    setFtpPrefill(ftpPending);          // pre-fill the Profile editor; pending stays until they add
    setShowProfile(true);
    setFtpPending(null);                // hide the banner while editing
  }

  async function dismissFtp() {
    await fetch(`/api/ftp-history/dismiss-pending`, { method: "POST" }).catch(() => {});
    setFtpPending(null);
  }

  async function onFile(e) {
    const arr = [...(e.target.files || [])];
    e.target.value = "";
    if (!arr.length) return;
    setUpload({ state: "busy", msg: `Ingesting ${arr.length > 1 ? arr.length + " files" : arr[0].name}…` });
    try {
      const body = new FormData();
      arr.forEach((f) => body.append("files", f));
      const res = await fetch(`/api/upload`, { method: "POST", body });   // incremental: no 12mo minimum
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

  async function onStravaPull() {
    setUpload({ state: "busy", msg: "Pulling from Strava…" });
    try {
      const res = await fetch(`/api/strava/pull`, { method: "POST" });
      const out = await res.json();
      if (!res.ok) throw new Error(out.detail || "pull failed");
      const mt = await fetch(`/api/meta`).then((r) => r.json());
      setMeta(mt);
      setDataKey((k) => k + 1);
      refreshFtpPending();          // surface any new Strava FTP for accept/edit/dismiss
      const note = out.rate_limited ? " (rate-limited — click again in ~15 min for the rest)" : "";
      setUpload({ state: "ok", msg: `Synced — ${out.rides_with_power} rides, data through ${out.data_through}.${note}` });
      setTimeout(() => setUpload({ state: "idle", msg: "" }), 8000);
    } catch (e2) {
      setUpload({ state: "err", msg: String(e2.message || e2) });
    }
  }

  if (err)
    return (
      <div className="shell">
        <div className="appbar"><h1 className="wordmark">WATT SMITH</h1></div>
        <p className="err">API error: {err}. Is the backend running on :8000?</p>
      </div>
    );
  if (intake === null)
    return (
      <div className="shell">
        <div className="appbar"><h1 className="wordmark">WATT SMITH</h1></div>
        <p style={{ color: "var(--ink-2)", padding: 14 }}>Loading…</p>
      </div>
    );

  if (!intake.complete)
    return <Onboarding initialStatus={intake} onComplete={finishOnboarding} />;

  if (!meta)
    return (
      <div className="shell">
        <div className="appbar"><h1 className="wordmark">WATT SMITH</h1></div>
        <p style={{ color: "var(--ink-2)", padding: 14 }}>Loading…</p>
      </div>
    );

  return (
    <div className="shell">
      <div className="appbar">
        <h1 className="wordmark">WATT SMITH <small>data through {meta.date_max}</small></h1>
        <div className="tabs">
          <button className={view === "dashboard" ? "tab on" : "tab"} onClick={() => setView("dashboard")}>Dashboard</button>
          <button className={view === "calendar" ? "tab on" : "tab"} onClick={() => setView("calendar")}>Calendar</button>
        </div>
        <div className="appbar-actions">
          {upload.msg && <span className={"upload-msg " + upload.state}>{upload.msg}</span>}
          <input type="file" accept=".xlsx" multiple ref={fileRef} onChange={onFile} style={{ display: "none" }} />
          <button className="update-btn" disabled={upload.state === "busy"} onClick={onStravaPull}>
            {upload.state === "busy" ? "Syncing…" : "⟲ Pull from Strava"}
          </button>
          <button className="update-btn" onClick={() => setCheckinOpen(true)}>✓ Check-In</button>
          <button className="update-btn" onClick={() => setShowProfile(true)}>⚙ Profile</button>
          <button className="update-btn" disabled={upload.state === "busy"} onClick={() => fileRef.current?.click()}>
            {upload.state === "busy" ? "Updating…" : "↑ Load data"}
          </button>
          <span className={"pill " + meta.board_status}>{meta.board_status}</span>
        </div>
      </div>

      {ftpPending && (
        <div className="ftp-notice">
          <span className="ftp-notice-txt">
            <b>Strava FTP changed</b> — your set FTP is now <b>{Math.round(ftpPending.ftp)} W</b>
            {ftpPending.prev != null && <> (was {Math.round(ftpPending.prev)} W)</>}. Use it for
            training load going forward?
          </span>
          <div className="ftp-notice-actions">
            <button className="confirm" onClick={acceptFtp}>Accept</button>
            <button className="ghost" onClick={editFtp}>Edit date…</button>
            <button className="notice-x" onClick={dismissFtp} aria-label="Dismiss">×</button>
          </div>
        </div>
      )}

      {showProfile && (
        <Profile
          onClose={() => { setShowProfile(false); setFtpPrefill(null); refreshFtpPending(); }}
          onSaved={refreshAfterProfile} onChanged={refreshDataOnly} prefillFtp={ftpPrefill} />
      )}

      <div className="main">
        {view === "dashboard"
          ? <Watchman key={"w" + dataKey} meta={meta} onSeeWeek={() => setView("calendar")} onCheckIn={() => setCheckinOpen(true)} onPlanChange={() => setPlanKey((k) => k + 1)} onReply={(t) => { setCoachSeed(t); setCoachOpen(true); }} />
          : <Calendar key={"cal" + dataKey + "-" + planKey} />}
      </div>

      <CoachBar status={meta.board_status} onOpen={() => setCoachOpen(true)} />

      {coachOpen && (
        <>
          <div className="coach-scrim" onClick={() => { setCoachOpen(false); setCoachSeed(null); }} />
          <div className="coach-drawer">
            <Coach key={"c" + dataKey} meta={meta} seedMessage={coachSeed}
              onPlanChanged={() => setPlanKey((k) => k + 1)}
              onClose={() => { setCoachOpen(false); setCoachSeed(null); }} />
          </div>
        </>
      )}

      {checkinOpen && (
        <CheckIn meta={meta} onClose={closeCheckin}
          onPlanChanged={() => { setPlanKey((k) => k + 1); setDataKey((k) => k + 1); }} />
      )}
    </div>
  );
}
