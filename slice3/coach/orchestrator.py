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

SYSTEM = """You are Coach Wattson — the voice of Watt Smith, an old pro who reads an athlete's
numbers and tells them straight. You work from three sources, given below:
1. FINDINGS — deterministic detections from the athlete's own training data.
2. METHODOLOGY — passages retrieved from the athlete's own coaching knowledge base.
3. NOTES — dated subjective reports the athlete made in past check-ins.

Hard rules (these never bend):
- You NEVER calculate. Every claim about what is happening in their training must trace to
  a FINDING given below — quote its numbers as given; do not derive new ones, do not
  estimate trends the findings don't state. The HUD displays the numbers; you interpret them.
- Advice should trace to the METHODOLOGY passages. When you go beyond what the findings and
  retrieved methodology support, you MUST flag it explicitly, e.g. "This isn't from your
  methodology, but generally...". Grounded answers need no flag.
- Subjective NOTES are what the athlete said, dated. Use them to corroborate and personalize
  ("you mentioned work stress that week") — never convert them into metrics.
- NO internal jargon. CTL / ATL / TSB / TSS are fine (athletes know them). But NEVER say
  "ACWR" or "acute:chronic ratio" — describe it in plain words instead: "this week is a big
  jump over what you've recently been doing," or "you piled on ~70% more than your usual week."
  Same for any other internal term: translate it to what it means for their training.

Voice (Coach Wattson):
- State the number first, then what to do about it. Lead with the read, not the pep talk.
- Encouraging when it's earned, blunt when the numbers demand it — never hype, never insulting.
  "That's how you do it" when they've built clean; "I've seen this movie, back it off" when
  they're redlining. You've watched a lot of seasons; it shows.
- Plain language, tight — a few short lines, not an essay. Connect the data to how they said
  they feel. Reference prior check-ins when relevant. You can be a little arcade about it, but
  the moment you touch a number, it's exactly the number the findings gave you."""


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

    def __init__(self, conn, watch_state, ranked_confirmed, index, client=None, cfg=DEFAULT,
                 profile=None, plan_summary=None, soft_advisories=None, weekly_briefing=None,
                 phase_progression=None):
        import anthropic
        from wko_metrics import DEFAULT_PROFILE
        self.conn = conn                      # coach.db (notes + conversations)
        self.watch_state = watch_state        # slice2 select() output for "now"
        self.ranked_confirmed = ranked_confirmed
        self.index = index                    # MethodologyIndex
        self.client = client or anthropic.Anthropic()
        self.cfg = cfg
        self.profile = profile or DEFAULT_PROFILE
        self.athlete_id = self.profile.athlete_id
        # The deterministic calendar (slice4), as a plain text summary the coach EXPLAINS.
        # The coach never computes these numbers — code does; this is read-only context.
        self.plan_summary = plan_summary
        # Recurring subjective themes (slice4.5 step 3), as soft context. STRICTLY non-binding:
        # the coach may acknowledge these; it must NEVER change a plan number because of them.
        self.soft_advisories = soft_advisories
        # This week's deterministic briefing (slice4.5 weekly check-in) — set when a check-in is
        # opened; the coach narrates it, never recomputes it.
        self.weekly_briefing = weekly_briefing
        self.phase_progression = phase_progression

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
        rows = capture.notes_for_window(self.conn, start, as_of, self.athlete_id)
        return "\n".join(f"  {d} [{cat}] {note} (said: \"{q}\")" for d, cat, note, q in rows) \
            or "  (none yet)"

    def _profile_context(self, as_of):
        """KNOWN fixed facts only — never invented. Empty until the athlete fills them in,
        so behavior is unchanged for an unconfigured profile. Carries the doc's masters rule."""
        p = self.profile
        year = int(as_of[:4])
        facts = [f"name: {p.name}"]
        age = p.age(year)
        if age is not None:
            facts.append(f"age: {age} ({'masters (>=40): lengthen recovery, shallower troughs' if p.is_masters(year) else 'open category'})")
        # weekly availability is a season input (slice4), not a profile fact — added to the
        # coach's context by the calendar layer when a season is active.
        return "  " + "\n  ".join(facts)

    def _build_turn_context(self, question, as_of, conv_id):
        chunks = self._retrieve(question)
        meth = "\n\n".join(f"[{c['doc']} — relevance {c['score']:.2f}]\n{c['text']}"
                           for c in chunks) or "(nothing relevant retrieved — flag any general answer)"
        prior = store.prior_checkin_dates(self.conn, conv_id)
        calendar = (f"CALENDAR (deterministic plan skeleton — explain it, do NOT recompute "
                    f"these numbers yourself):\n{self.plan_summary}\n\n" if self.plan_summary else "")
        themes = (f"RECURRING CHECK-IN THEMES (soft signals — acknowledge them, but they must "
                  f"NEVER change a plan number; only hard facts feed a recompute):\n"
                  f"{self.soft_advisories}\n\n" if self.soft_advisories else "")
        briefing = (f"THIS WEEK'S BRIEFING (deterministic — narrate it, do NOT recompute these "
                    f"numbers):\n{self.weekly_briefing}\n\n" if self.weekly_briefing else "")
        progression = (f"PHASE PROGRESSION (deterministic gate — advise on whether this block has "
                       f"done its job. Narrate the contingency (what this week tests) and the "
                       f"calendar cost of holding. You may PROPOSE a hold, but the athlete confirms "
                       f"— do NOT recompute numbers yourself):\n{self.phase_progression}\n\n"
                       if self.phase_progression else "")
        return (f"ATHLETE PROFILE (fixed facts):\n{self._profile_context(as_of)}\n\n"
                f"{briefing}{progression}{calendar}{themes}"
                f"FINDINGS (deterministic, as of {as_of}):\n"
                f"{_findings_context(self.watch_state, self.ranked_confirmed)}\n\n"
                f"METHODOLOGY (retrieved for this question, corpus v{self.index.version}):\n{meth}\n\n"
                f"NOTES (athlete's dated subjective reports, last 60 days):\n"
                f"{self._notes_context(as_of)}\n\n"
                f"Prior check-ins on: {', '.join(prior) or 'none'}"), chunks

    # ---- the turn ----
    def respond(self, user_text, conv_id, as_of, now_iso):
        # 1. CAPTURE: store what the athlete said as dated notes (validated; no metrics).
        accepted, rejected = capture.extract_notes(user_text, as_of, self.client, self.cfg)
        capture.store_checkin(self.conn, as_of, accepted, now_iso, self.athlete_id)

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

    # ---- intake first-read (grounded; writes nothing, computes nothing) ----
    def first_read(self, as_of, season_goal=None):
        """Coach Wattson's first read on a new athlete. Reuses the SAME grounded context the
        check-in turn builds (findings + profile + season + retrieved methodology); seeds it with
        a fixed first-read instruction. Read-only — no capture, no plan write, no metric. If the
        FINDINGS are thin it soft-fallbacks instead of asserting a pattern that isn't there."""
        context, chunks = self._build_turn_context(
            "season readiness overview: fitness CTL, fatigue ATL, form TSB, and this athlete's "
            "characteristic failure pattern (spike-then-crash, gaps, durability)", as_of, conv_id=None)
        if season_goal:
            context += (f"\n\nSEASON DIRECTION (general goal — no dated A-race yet, so there is no "
                        f"plan to explain): {season_goal}")
        instruction = (
            "This is your FIRST read on a new athlete — you've just seen their history for the "
            "first time. Introduce yourself in one line as Coach Wattson, then give them the read: "
            "how much history you can see, the characteristic pattern the FINDINGS show, and any "
            "active flags — number-first, in your voice. If the FINDINGS are thin or absent, say "
            "plainly there isn't enough history to call a pattern yet — do NOT invent one. A few "
            "tight lines, not an essay.")
        response = self.client.messages.create(
            model=self.cfg.model, max_tokens=self.cfg.max_tokens, system=SYSTEM,
            messages=[{"role": "user", "content": f"<context>\n{context}\n</context>\n\n{instruction}"}])
        reply = next((b.text for b in response.content if b.type == "text"), "")
        return {"reply": reply,
                "methodology_used": [{"doc": c["doc"], "score": c["score"]} for c in chunks]}
