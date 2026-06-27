"""Optional LLM polish for the deterministic dashboard narrative (Slice 4.5).

`review.coach_card` composes grounded, correct fragments grouped into paragraphs — but un-joined
they read like a list of separate sentences. This rewrites each paragraph group into ONE coherent
paragraph in Wattson's voice WITHOUT adding, removing, or changing any number, date, or fact: THE
ONE RULE still holds — code owns the facts, the model only rewords and connects them.

It runs on the cheaper/faster Sonnet tier (cfg.narrative_model), not the coach's Opus — this is a
pure reword-with-fixed-facts job, no reasoning. Three guarantees keep it safe on an always-on tile:
  • CACHED per state in coach.db (key = hash of the paragraphs + model + prompt version), so the
    model is called once per data change, not on every page load. The prompt version invalidates
    the cache automatically whenever the wording rules below change.
  • DETERMINISTIC FALLBACK — on a cache miss with no client, any model/network error, or an empty
    reply, it returns the paragraphs joined with blank lines. The dashboard never depends on the
    model being reachable (e.g. cold start with no ANTHROPIC_API_KEY still renders the grounded read).
  • The reword is constrained to the facts handed in; it cannot introduce a number that isn't there.
"""
import datetime as dt
import hashlib
import json
import random
import re

# Bump when _SYSTEM changes so existing cache rows (keyed partly on this) are bypassed.
_PROMPT_VERSION = "3"

# Up to this many distinct takes are cached per data state; each render serves a random one, so the
# read doesn't come back word-for-word identical every time (a fixed string reads as a formula, not a
# coach). Bounded cost: at most this many Sonnet calls per state, then it's free and varied.
_VARIANTS = 3
_TEMPERATURE = 1.0           # latitude for genuine voice variation; the fact-guard protects the facts

_SCHEMA = """
CREATE TABLE IF NOT EXISTS narrative_cache (
    cache_key  TEXT PRIMARY KEY,
    prose      TEXT NOT NULL,
    model      TEXT,
    created_at TEXT
);
"""

_SYSTEM = (
    "You are Wattson — a sharp, encouraging cycling coach talking to your athlete. You'll get the "
    "athlete's dashboard read as a JSON list of note groups. Rewrite it into exactly that many "
    "paragraphs — one per group, in order, separated by a single blank line — in your own natural "
    "coaching voice. Make it sound like a real person who knows this rider, not a template: vary your "
    "sentence openings and rhythm, connect the ideas the way you'd actually say them out loud, and "
    "don't just echo the wording you were handed — rephrase it as your own. Lead the first paragraph "
    "with any flag or concern. Keep each paragraph to two or three sentences: tight, direct, concrete, "
    "never padded. The ONE hard constraint: every number, date, percentage, and fact must stay exactly "
    "as given — reword freely, but never invent, drop, or change a number. No greeting, no sign-off, "
    "no headers, no emoji — output only the paragraphs separated by blank lines."
)

# A "fact" worth guarding: any decimal, any 2+ digit integer, or any integer carrying a unit. Small
# bare ordinals (week 1 of 3) are left out — the looser prompt may spell those, and they're low-risk.
_FACT_RE = re.compile(r"\d+\.\d+|\d{2,}|\d+(?=\s?(?:W\b|min\b|%|×|x\b|TSS|kg|lb|bpm|days?\b))", re.I)


def _facts_preserved(src, out):
    """True iff the polished text carries exactly the significant numbers of the source — none dropped,
    none invented, none changed. The guardrail that lets us hand the model real voice freedom without
    risking THE ONE RULE."""
    return set(_FACT_RE.findall(src)) == set(_FACT_RE.findall(out))


def _key(paragraphs, model):
    raw = "\n␟\n".join(paragraphs) + f"|{model}|v{_PROMPT_VERSION}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _generate(client, model, paragraphs):
    """One fresh, voice-varied take. Empty string on any error (caller falls back)."""
    try:
        r = client.messages.create(
            model=model, max_tokens=500, temperature=_TEMPERATURE, system=_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(paragraphs)}],
        )
        return next((b.text for b in r.content if b.type == "text"), "").strip()
    except Exception:
        return ""                                         # model unreachable / no key


def polish(paragraphs, conn, client, cfg):
    """Return a coherent multi-paragraph read for `paragraphs` (list[str], one per group), paragraphs
    separated by blank lines. Caches up to `_VARIANTS` distinct takes per data state in `conn`
    (coach.db) and serves a random one, so the read isn't word-for-word identical on every render.
    Each fresh take is fact-checked (THE ONE RULE) before it's cached. Falls back to the joined groups
    on any miss/error so the caller always gets a valid, correct read."""
    paragraphs = [p for p in (paragraphs or []) if p]
    joined = "\n\n".join(paragraphs)
    if not paragraphs:
        return joined

    model = getattr(cfg, "narrative_model", None) or cfg.model
    base = _key(paragraphs, model)                         # one base key per (state, model, prompt ver)
    src = "\n".join(paragraphs)

    variants = []
    if conn is not None:                                  # read the existing pool (best-effort)
        try:
            conn.execute(_SCHEMA)
            variants = [r[0] for r in conn.execute(
                "SELECT prose FROM narrative_cache WHERE cache_key LIKE ?", (base + ":%",)).fetchall()]
        except Exception:
            pass

    # Top up the pool by one fresh take per render until it's full — bounds cost to _VARIANTS calls
    # per state, after which rendering is free and still varied.
    if client is not None and len(variants) < _VARIANTS:
        prose = _generate(client, model, paragraphs)
        if prose and _facts_preserved(src, prose):
            if conn is not None:                          # cache write (best-effort)
                try:
                    conn.execute(
                        "INSERT OR REPLACE INTO narrative_cache (cache_key, prose, model, created_at) "
                        "VALUES (?,?,?,?)",
                        (f"{base}:{len(variants)}", prose, model,
                         dt.datetime.now().isoformat(timespec="seconds")))
                    conn.commit()
                except Exception:
                    pass
            variants.append(prose)

    if not variants:
        return joined
    return random.choice(variants)
