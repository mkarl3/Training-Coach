import React, { useEffect, useState } from "react";

const LABELS = {
  name: "Name",
  birth_year: "Birth year",
  units: "Units",
  week_starts_on: "Week starts on",
};

function FtpHistory({ onChanged, prefill }) {
  const [entries, setEntries] = useState(null);
  const [date, setDate] = useState("");
  const [ftp, setFtp] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    fetch("/api/ftp-history").then((r) => r.json())
      .then((d) => setEntries(d.entries || [])).catch((e) => setErr(String(e)));
  }, []);

  useEffect(() => {                                  // arrived via "Edit date…" — seed the add-form
    if (prefill?.ftp) {
      setFtp(String(Math.round(prefill.ftp)));
      if (prefill.seen_date) setDate(prefill.seen_date);
    }
  }, [prefill]);

  async function add() {
    if (!date || !ftp) return;
    setBusy(true); setErr(null);
    try {
      const r = await fetch("/api/ftp-history", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ effective_date: date, ftp: Number(ftp) }),
      });
      const out = await r.json();
      if (!r.ok) throw new Error(out.detail || "couldn't add");
      setEntries(out.entries); setDate(""); setFtp("");
      if (out.applied) onChanged?.();
    } catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  }

  async function del(id) {
    setBusy(true); setErr(null);
    try {
      const r = await fetch(`/api/ftp-history/${id}`, { method: "DELETE" });
      const out = await r.json();
      if (!r.ok) throw new Error(out.detail || "couldn't delete");
      setEntries(out.entries);
      if (out.applied) onChanged?.();
    } catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  }

  return (
    <>
      <h3>FTP history <span>· the threshold FTP used for TSS</span></h3>
      <p className="hint">
        Each ride's training load is scored against the FTP that was true on its date. Values you
        set in Strava sync in automatically on a pull; add past changes by hand. Editing recomputes
        TSS across your whole history.
      </p>
      <div className="ftp-list">
        {entries && entries.length > 0 ? entries.map((e) => (
          <div className="ftp-row" key={e.id}>
            <span className="ftp-date">{e.effective_date}</span>
            <span className="ftp-val">{Math.round(e.ftp)} W</span>
            <span className={"ftp-src " + e.source}>{e.source}</span>
            <button className="del" onClick={() => del(e.id)} disabled={busy} aria-label="Delete entry">×</button>
          </div>
        )) : <p className="hint">{entries ? "No entries yet." : "Loading…"}</p>}
      </div>
      <div className="ftp-add">
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} aria-label="Effective date" />
        <input type="number" placeholder="watts" value={ftp} min="1" max="600"
          onChange={(e) => setFtp(e.target.value)} aria-label="FTP watts" />
        <button onClick={add} disabled={busy || !date || !ftp}>{busy ? "Recomputing…" : "Add"}</button>
      </div>
      {err && <p className="hint err">{err}</p>}
    </>
  );
}

export default function Profile({ onClose, onSaved, onChanged, prefillFtp }) {
  const [data, setData] = useState(null);
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    fetch("/api/profile")
      .then((r) => r.json())
      .then((d) => {
        setData(d);
        setForm(d.profile);
      })
      .catch((e) => setErr(String(e)));
  }, []);

  function set(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  async function save() {
    setSaving(true);
    setErr(null);
    try {
      const res = await fetch("/api/profile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ updates: form }),
      });
      const out = await res.json();
      if (!res.ok) throw new Error(out.detail || "save failed");
      onSaved();
    } catch (e) {
      setErr(String(e.message || e));
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <b>Athlete profile</b>
          <button className="x" onClick={onClose}>×</button>
        </div>

        {!data && !err && <div className="modal-body">Loading…</div>}
        {err && <div className="modal-body err">{err}</div>}

        {data && (
          <div className="modal-body">
            <p className="hint">
              Athlete #{data.profile.athlete_id}. Everything below is this athlete's own —
              detectors, the dashboard, and the coach all read from here.
            </p>

            <h3>About you</h3>
            <div className="grid">
              {data.fixed_fact_fields.map((f) => (
                <label key={f}>
                  <span>{LABELS[f] || f}</span>
                  {f === "units" ? (
                    <select value={form[f] ?? "imperial"} onChange={(e) => set(f, e.target.value)}>
                      <option value="imperial">imperial (mi / lb)</option>
                      <option value="metric">metric (km / kg)</option>
                    </select>
                  ) : f === "week_starts_on" ? (
                    <select value={form[f] ?? "monday"} onChange={(e) => set(f, e.target.value)}>
                      <option value="monday">Monday</option>
                      <option value="sunday">Sunday</option>
                    </select>
                  ) : (
                    <input
                      type={f === "name" ? "text" : "number"}
                      value={form[f] ?? ""}
                      placeholder={f === "name" ? "" : "unknown"}
                      onChange={(e) => set(f, e.target.value)}
                    />
                  )}
                </label>
              ))}
            </div>
            {data.derived.age != null && (
              <p className="hint">
                Age {data.derived.age}
                {data.derived.is_masters
                  ? " — masters: the coach lengthens recovery and uses shallower troughs."
                  : "."}
              </p>
            )}

            <FtpHistory onChanged={onChanged} />

            <h3 className="advanced">
              Tuned values <span>⚠ advanced — change with care</span>
            </h3>
            <p className="hint">
              These were tuned to this athlete's history and are still provisional. The defaults
              work; only change them if you know what you're doing.
            </p>
            <div className="grid">
              {data.tuned_fields.map((f) => (
                <label key={f} className="tuned">
                  <span>{f}</span>
                  <input type="number" step="any" value={form[f] ?? ""}
                    onChange={(e) => set(f, e.target.value)} />
                </label>
              ))}
            </div>
          </div>
        )}

        <div className="modal-foot">
          <button className="ghost" onClick={onClose} disabled={saving}>Cancel</button>
          <button className="primary" onClick={save} disabled={saving || !data}>
            {saving ? "Saving & recomputing…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
