# Slice 3 — The Coach (LLM interface)

A conversational weekly check-in that **explains** the Slice-1 findings in plain language,
**captures** the athlete's subjective reports as dated structured notes, **advises** from
the methodology knowledge base, and **remembers** across sessions.

## The rule everything hangs on

**The LLM interprets and advises. It never calculates and never manufactures data.**
Enforced structurally, not just by prompt:
- Per turn the model is handed only (a) deterministic findings (Slice-1 detectors +
  Slice-2 selection), (b) retrieved methodology passages, (c) dated subjective notes +
  conversation history. It never sees raw `daily`/`workout` tables (tested).
- **Capture boundary:** notes have NO numeric fields; every note's `quote` must be a
  verbatim substring of the athlete's message; dates must fall inside the check-in window.
  Violations are rejected before storage (tested with planted fabrications).
- **Soft grounding:** answers beyond findings+methodology are allowed but must be flagged
  ("This isn't from your methodology, but generally…"). Empty retrieval forces the flag.

## Layout
- `coach/indexer.py` / `retrieval.py` — frozen, versioned methodology index
  (63 docs → 1,617 chunks, TF-IDF + cosine in SQLite; `corpus_version` tagged; re-run
  `build` only on deliberate corpus updates). Per-question top-K retrieval
  (`methodology_chunks_per_query`, similarity floor) + LLM query expansion.
- `coach/capture.py` — subjective-note schema + extraction (`messages.parse`, Pydantic)
  + the validation gate.
- `coach/store.py` — conversations persist in `coach.db`, stitched to dates.
- `coach/orchestrator.py` — context assembly + the per-turn LLM call.
- `api/main.py` — FastAPI on **:8001** (`/api/coach/meta|history|message`).
- `frontend/` — React chat UI on **:5181**.

## Run
```bash
# backend (needs ANTHROPIC_API_KEY; model: claude-opus-4-8 in coach/config.py)
python -m uvicorn api.main:app --port 8001        # from slice3/
cd frontend && npm install && npm run dev          # -> http://127.0.0.1:5181
python -m pytest tests/ -q                         # 11 tests, no API needed
```

## Honest framing
The grounding rule cannot be perfectly guaranteed by prompts — LLMs drift. The structural
constraint (what the model is handed) is the real guardrail; the prompt is the second line.
Retrieval quality was eyeballed on 4 questions, not measured; the corpus is thin on
re-entry/return-from-layoff content (query expansion mitigates; adding a transcript on
re-entry would help more).

## Not in this slice
Weekly-export import UI (separate small slice over the Slice-0 parser) and the annual
calendar (Feature 3, last slice).
