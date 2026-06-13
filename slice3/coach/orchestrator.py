"""Coach orchestration — explain, capture, advise, remember.

THE STRUCTURAL GROUNDING GUARANTEE: per turn, the model is handed exactly three kinds of
material — (a) deterministic Slice-1/2 findings, (b) retrieved methodology passages,
(c) dated subjective notes + conversation history. It is NEVER given raw daily/workout
tables, so it cannot compute or "notice" trends the engine didn't produce. The system
prompt restates the rule; the context assembly is what enforces it.

Soft grounding policy: answers beyond findings+methodology are allowed but must be flagged
("This isn't from your methodology, but generally...").
"""
import datetime
import json

from . import capture, store
from .config import DEFAULT

SYSTEM = """You are this athlete's cycling coach. You work from three sources, given below:
1. FINDINGS — deterministic detections from the athlete's own training data.
2. METHODOLOGY — passages retrieved from the athlete's own coaching knowledge base.
3. NOTES — dated subjective reports the athlete made in past check-ins.

Hard rules:
- You NEVER calculate. Every claim about what is happening in their training must trace to
  a FINDING given below — quote its numbers as given; do not derive new ones, do not
  estimate trends the findings don't state.
- Advice should trace to the METHODOLOGY passages. When you go beyond what the findings and
  retrieved methodology support, you MUST flag it explicitly, e.g. "This isn't from your
  methodology, but generally...". Grounded answers need no flag.
- Subjective NOTES are what the athlete said, dated. Use them to corroborate and personalize
  ("you mentioned work stress that week") — never convert them into metrics.
- Be a coach: plain language, direct, warm. Explain what the data shows, connect it to how
  they said they feel, and give concrete grounded next steps. Reference prior check-ins
  when relevant. Keep responses tight — a few short paragraphs, not an essay."""


def _expand_query(question, client, cfg):
    """One small LLM call: rephrase the athlete's question into training-methodology
    vocabulary so lexical retrieval finds the right passages. Rewords a QUESTION only —
    no data involved, nothing computed."""
    try:
        r = client.messages.create(
            model=cfg.model, max_tokens=100,
            system="Rewrite the cycling-training question as 5-10 search keywords a "
                   "coaching-methodology corpus would use (e.g. 'gap' -> 'time off the "
                   "bike detraining restart'). Output only the keywords.",
            messages=[{"role": "user", "content": question}],
        )
        return next((b.text for b in r.content if b.type == "text"), "").strip()
    except Exception:
        return ""                                   # retrieval still runs on the raw question


def _findings_context(watch_state, ranked_confirmed):
    """Compact JSON the model can cite — selection output + recent confirmed findings."""
    recent = [{
        "mode": f["mode_id"], "variant": f["variant"], "family": f["detector_family"],
        "window": f"{f['window_start']}..{f['window_end']}",
        "evidence": f["evidence"], "data_flags": f["data_flags"],
    } for f in ranked_confirmed]
    return json.dumps({"current_dashboard_state": watch_state,
                       "confirmed_findings_last_12mo": recent}, indent=1, default=str)


class Coach:
    """Wires retrieval + findings + notes + memory into per-turn LLM calls."""

    def __init__(self, conn, watch_state, ranked_confirmed, index, client=None, cfg=DEFAULT):
        import anthropic
        self.conn = conn                      # coach.db (notes + conversations)
        self.watch_state = watch_state        # slice2 select() output for "now"
        self.ranked_confirmed = ranked_confirmed
        self.index = index                    # MethodologyIndex
        self.client = client or anthropic.Anthropic()
        self.cfg = cfg

    # ---- context assembly (the structural guarantee lives here) ----
    def _retrieve(self, question):
        chunks = {(c["doc"], c["seq"]): c for c in self.index.retrieve(question)}
        expansion = _expand_query(question, self.client, self.cfg)
        if expansion:
            for c in self.index.retrieve(expansion):
                chunks.setdefault((c["doc"], c["seq"]), c)
        ranked = sorted(chunks.values(), key=lambda c: -c["score"])
        return ranked[: self.cfg.methodology_chunks_per_query]

    def _notes_context(self, as_of):
        start = (datetime.date.fromisoformat(as_of) - datetime.timedelta(days=60)).isoformat()
        rows = capture.notes_for_window(self.conn, start, as_of)
        return "\n".join(f"  {d} [{cat}] {note} (said: \"{q}\")" for d, cat, note, q in rows) \
            or "  (none yet)"

    def _build_turn_context(self, question, as_of, conv_id):
        chunks = self._retrieve(question)
        meth = "\n\n".join(f"[{c['doc']} — relevance {c['score']:.2f}]\n{c['text']}"
                           for c in chunks) or "(nothing relevant retrieved — flag any general answer)"
        prior = store.prior_checkin_dates(self.conn, conv_id)
        return (f"FINDINGS (deterministic, as of {as_of}):\n"
                f"{_findings_context(self.watch_state, self.ranked_confirmed)}\n\n"
                f"METHODOLOGY (retrieved for this question, corpus v{self.index.version}):\n{meth}\n\n"
                f"NOTES (athlete's dated subjective reports, last 60 days):\n"
                f"{self._notes_context(as_of)}\n\n"
                f"Prior check-ins on: {', '.join(prior) or 'none'}"), chunks

    # ---- the turn ----
    def respond(self, user_text, conv_id, as_of, now_iso):
        # 1. CAPTURE: store what the athlete said as dated notes (validated; no metrics).
        accepted, rejected = capture.extract_notes(user_text, as_of, self.client, self.cfg)
        capture.store_checkin(self.conn, as_of, accepted, now_iso)

        # 2. Persist the user message; build history AFTER so the model sees it last.
        store.add_message(self.conn, conv_id, "user", user_text, now_iso)
        hist = store.history(self.conn, conv_id, limit=12)

        # 3. Assemble grounded context (findings + retrieved methodology + notes ONLY).
        context, chunks = self._build_turn_context(user_text, as_of, conv_id)
        messages = [{"role": r, "content": c} for r, c, _ in hist]
        messages[-1] = {"role": "user",
                        "content": f"<context>\n{context}\n</context>\n\n{user_text}"}

        response = self.client.messages.create(
            model=self.cfg.model, max_tokens=self.cfg.max_tokens,
            system=SYSTEM, messages=messages)
        reply = next((b.text for b in response.content if b.type == "text"), "")

        store.add_message(self.conn, conv_id, "assistant", reply, now_iso)
        return {
            "reply": reply,
            "notes_captured": [{"date": n.date, "category": n.category.value, "note": n.note}
                               for n in accepted],
            "notes_rejected": len(rejected),
            "methodology_used": [{"doc": c["doc"], "score": c["score"]} for c in chunks],
        }
