import React, { useEffect, useRef, useState } from "react";

// Minimal markdown: **bold** and *italic* only.
function md(text) {
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*\n]+\*)/g);
  return parts.map((p, i) => {
    if (p.startsWith("**") && p.endsWith("**")) return <b key={i}>{p.slice(2, -2)}</b>;
    if (p.startsWith("*") && p.endsWith("*")) return <i key={i}>{p.slice(1, -1)}</i>;
    return p;
  });
}

function DiffLine({ diff }) {
  if (!diff || diff.error_new) return <span className="muted">can't preview this change</span>;
  const s = diff.summary;
  const peak = s.peak_ctl_achieved;
  const reach = s.target_reached;
  return (
    <div className="diff">
      <b>{diff.n_changed}</b> week{diff.n_changed === 1 ? "" : "s"} change · peak CTL{" "}
      {peak[0]} → <b>{peak[1]}</b>
      {reach[0] !== reach[1] && (
        <span className={reach[1] ? "ok" : "miss"}>
          {" "}· target {reach[1] ? "now reachable" : "no longer reachable"}
        </span>
      )}
      {s.weeks[0] !== s.weeks[1] && <span> · {s.weeks[0]} → {s.weeks[1]} wks</span>}
    </div>
  );
}

const KIND_LABEL = {
  hard_time_loss: "Time off",
  hard_capacity_up: "Extra availability",
  hard_capacity_change: "Keep it easy",
};

export default function Coach({ meta, onPlanChanged }) {
  const [convId, setConvId] = useState(meta.latest_conversation_id);
  const [msgs, setMsgs] = useState([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [cards, setCards] = useState({});   // proposalId -> {status, adjustmentId}
  const [themes, setThemes] = useState([]); // recurring soft-signal themes (non-binding)
  const chatRef = useRef(null);

  useEffect(() => {
    fetch(`/api/coach/advisories`).then((r) => r.json())
      .then((a) => setThemes(a.recurring_themes || [])).catch(() => {});
  }, []);

  async function confirm(p) {
    setCards((c) => ({ ...c, [p.id]: { status: "applying" } }));
    try {
      const out = await fetch(`/api/plan/adjustment/confirm`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ proposal_id: p.id }),
      }).then((r) => r.json());
      setCards((c) => ({ ...c, [p.id]: { status: "applied", adjustmentId: out.adjustment_id } }));
      onPlanChanged?.();
    } catch {
      setCards((c) => ({ ...c, [p.id]: { status: "error" } }));
    }
  }
  async function undo(p) {
    const aid = cards[p.id]?.adjustmentId;
    if (aid == null) return;
    await fetch(`/api/plan/adjustment/${aid}/undo`, { method: "POST" }).catch(() => {});
    setCards((c) => ({ ...c, [p.id]: { status: "undone" } }));
    onPlanChanged?.();
  }
  const dismiss = (p) => setCards((c) => ({ ...c, [p.id]: { status: "dismissed" } }));

  useEffect(() => {
    if (!meta.latest_conversation_id) return;
    fetch(`/api/coach/history?conversation_id=${meta.latest_conversation_id}`)
      .then((r) => r.json())
      .then((h) => setMsgs(h.messages.map((m) => ({ role: m.role, content: m.content }))))
      .catch(() => {});
  }, [meta]);

  useEffect(() => {
    // scroll ONLY the chat pane — scrollIntoView would scroll ancestor containers
    // and drag the dashboard out of view in the stacked layout
    const el = chatRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [msgs, busy]);

  async function send() {
    const text = draft.trim();
    if (!text || busy) return;
    setDraft("");
    setMsgs((m) => [...m, { role: "user", content: text }]);
    setBusy(true);
    try {
      const out = await fetch(`/api/coach/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, conversation_id: convId }),
      }).then((r) => r.json());
      setConvId(out.conversation_id);
      if (out.recurring_themes) setThemes(out.recurring_themes);
      setMsgs((m) => [
        ...m,
        { role: "assistant", content: out.reply, captured: out.notes_captured,
          sources: out.methodology_used, proposals: out.plan_proposals,
          questions: out.clarifying_questions },
      ]);
    } catch {
      setMsgs((m) => [...m, { role: "assistant", content: "(connection error — try again)" }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="chat-head">
        <b>Coach</b>
        <span>weekly check-in · what you report is saved as dated notes</span>
      </div>
      {themes.length > 0 && (
        <div className="themes" title="Recurring in your check-ins — context for the coach, not a plan change">
          <span className="themes-label">Recurring:</span>
          {themes.map((t) => (
            <span className="theme-chip" key={t.category}>{t.label} ×{t.checkins}</span>
          ))}
        </div>
      )}
      <div className="chat" ref={chatRef}>
        {msgs.length === 0 && (
          <div className="empty">
            <b>How was your week?</b>
            <br />
            Tell me how training felt — sleep, stress, the rides. I'll connect it to what
            the dashboard shows.
          </div>
        )}
        {msgs.map((m, i) => (
          <React.Fragment key={i}>
            <div className={"msg " + m.role}>{md(m.content)}</div>
            {m.role === "assistant" && (m.captured?.length || m.sources?.length) ? (
              <div className="meta-row">
                {m.captured?.map((n, j) => (
                  <span className="chip" key={"n" + j}>✎ {n.date} {n.category}</span>
                ))}
                {m.sources?.slice(0, 2).map((s, j) => (
                  <span className="chip" key={"s" + j}>
                    📄 {s.doc.replace(/\.(docx|pdf)$/i, "").slice(0, 34)}
                  </span>
                ))}
              </div>
            ) : null}
            {m.questions?.map((q, j) => (
              <div className="ask-card" key={"q" + j}>I need one thing to act on this: {q}</div>
            ))}
            {m.proposals?.map((p) => {
              const st = cards[p.id]?.status;
              if (st === "dismissed") return null;
              return (
                <div className="proposal" key={p.id}>
                  <div className="proposal-head">
                    <span className="tag">{KIND_LABEL[p.kind] || "Plan change"}</span>
                    <span className="proposal-sum">{p.summary}</span>
                  </div>
                  <DiffLine diff={p.diff} />
                  {(!st || st === "applying" || st === "error") && (
                    <div className="proposal-actions">
                      <button className="confirm" onClick={() => confirm(p)} disabled={st === "applying"}>
                        {st === "applying" ? "Applying…" : "Confirm & recompute"}
                      </button>
                      <button className="ghost" onClick={() => dismiss(p)}>Dismiss</button>
                      {st === "error" && <span className="miss">couldn't apply — try again</span>}
                    </div>
                  )}
                  {st === "applied" && (
                    <div className="proposal-actions">
                      <span className="ok">✓ Applied to your plan.</span>
                      <button className="ghost" onClick={() => undo(p)}>Undo</button>
                    </div>
                  )}
                  {st === "undone" && <div className="muted">↩ Reverted — plan restored.</div>}
                </div>
              );
            })}
          </React.Fragment>
        ))}
        {busy && <div className="thinking">coach is reading your data…</div>}
      </div>
      <div className="composer">
        <textarea
          value={draft}
          placeholder="How did the week go?"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
        />
        <button onClick={send} disabled={busy || !draft.trim()}>Send</button>
      </div>
    </>
  );
}
