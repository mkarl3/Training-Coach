import React, { useEffect, useRef, useState } from "react";

const API = "http://127.0.0.1:8001";

// Minimal markdown: **bold** and *italic* only — everything else stays plain text.
function md(text) {
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*\n]+\*)/g);
  return parts.map((p, i) => {
    if (p.startsWith("**") && p.endsWith("**")) return <b key={i}>{p.slice(2, -2)}</b>;
    if (p.startsWith("*") && p.endsWith("*")) return <i key={i}>{p.slice(1, -1)}</i>;
    return p;
  });
}

export default function App() {
  const [meta, setMeta] = useState(null);
  const [convId, setConvId] = useState(null);
  const [msgs, setMsgs] = useState([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const endRef = useRef(null);

  useEffect(() => {
    fetch(`${API}/api/coach/meta`)
      .then((r) => r.json())
      .then(async (mt) => {
        setMeta(mt);
        if (mt.latest_conversation_id) {
          setConvId(mt.latest_conversation_id);
          const h = await fetch(
            `${API}/api/coach/history?conversation_id=${mt.latest_conversation_id}`
          ).then((r) => r.json());
          setMsgs(h.messages.map((m) => ({ role: m.role, content: m.content })));
        }
      })
      .catch((e) => setErr(String(e)));
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs, busy]);

  async function send() {
    const text = draft.trim();
    if (!text || busy) return;
    setDraft("");
    setMsgs((m) => [...m, { role: "user", content: text }]);
    setBusy(true);
    try {
      const out = await fetch(`${API}/api/coach/message`, {
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
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (err)
    return (
      <div className="wrap">
        <header><h1>Coach</h1></header>
        <p style={{ color: "var(--red)" }}>API error: {err}. Is the coach backend on :8001?</p>
      </div>
    );

  return (
    <div className="wrap">
      <header>
        <h1>
          Coach <small>weekly check-in · data through {meta?.as_of ?? "…"}</small>
        </h1>
        {meta && <span className={"pill " + meta.board_status}>{meta.board_status}</span>}
      </header>

      <div className="chat">
        {msgs.length === 0 && (
          <div className="empty">
            <b>How was your week?</b>
            <br />
            Tell me how training felt — sleep, stress, the rides. I'll connect it to what
            your data shows. What you report is saved as dated notes.
          </div>
        )}
        {msgs.map((m, i) => (
          <React.Fragment key={i}>
            <div className={"msg " + m.role}>{md(m.content)}</div>
            {m.role === "assistant" && (m.captured?.length || m.sources?.length) ? (
              <div className="meta-row">
                {m.captured?.map((n, j) => (
                  <span className="chip" key={"n" + j}>
                    ✎ {n.date} {n.category}
                  </span>
                ))}
                {m.sources?.slice(0, 3).map((s, j) => (
                  <span className="chip" key={"s" + j}>
                    📄 {s.doc.replace(/\.(docx|pdf)$/i, "").slice(0, 38)}
                  </span>
                ))}
              </div>
            ) : null}
          </React.Fragment>
        ))}
        {busy && <div className="thinking">coach is reading your data…</div>}
        <div ref={endRef} />
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
        <button onClick={send} disabled={busy || !draft.trim()}>
          Send
        </button>
      </div>
    </div>
  );
}
