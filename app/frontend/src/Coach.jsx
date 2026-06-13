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

export default function Coach({ meta }) {
  const [convId, setConvId] = useState(meta.latest_conversation_id);
  const [msgs, setMsgs] = useState([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const chatRef = useRef(null);

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
      setMsgs((m) => [
        ...m,
        { role: "assistant", content: out.reply, captured: out.notes_captured,
          sources: out.methodology_used },
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
