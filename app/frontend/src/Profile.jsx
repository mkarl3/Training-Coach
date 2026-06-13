import React, { useEffect, useState } from "react";

const LABELS = {
  name: "Name",
  birth_year: "Birth year",
  units: "Units",
  week_starts_on: "Week starts on",
};

export default function Profile({ onClose, onSaved }) {
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
