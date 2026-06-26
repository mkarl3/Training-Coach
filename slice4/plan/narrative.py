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

# Bump when _SYSTEM changes so existing cache rows (keyed partly on this) are bypassed.
_PROMPT_VERSION = "2"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS narrative_cache (
    cache_key  TEXT PRIMARY KEY,
    prose      TEXT NOT NULL,
    model      TEXT,
    created_at TEXT
);
"""

_SYSTEM = (
    "You are Wattson, a cycling coach. You'll get an athlete's dashboard read as a JSON list of "
    "note groups. Rewrite it into exactly that many short paragraphs — one paragraph per group, in "
    "order — separated by a single blank line. Keep each paragraph to two or three short, plain "
    "sentences; break up any run-on. Lead the first paragraph with any flag or concern. Direct, "
    "concrete, encouraging voice. HARD RULES: do not add, drop, or change any number, date, "
    "percentage, or fact; only reword and connect what you're given. No greeting, no sign-off, no "
    "headers — output only the paragraphs separated by blank lines."
)


def _key(paragraphs, model):
    raw = "\n␟\n".join(paragraphs) + f"|{model}|v{_PROMPT_VERSION}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def polish(paragraphs, conn, client, cfg):
    """Return a coherent multi-paragraph read for `paragraphs` (list[str], one per group), with
    paragraphs separated by blank lines. Cached in `conn` (coach.db); falls back to the joined
    groups on any miss/error so the caller always gets a valid read."""
    paragraphs = [p for p in (paragraphs or []) if p]
    joined = "\n\n".join(paragraphs)
    if not paragraphs:
        return joined

    model = getattr(cfg, "narrative_model", None) or cfg.model
    key = _key(paragraphs, model)
    if conn is not None:                                  # cache read (best-effort)
        try:
            conn.execute(_SCHEMA)
            row = conn.execute("SELECT prose FROM narrative_cache WHERE cache_key=?", (key,)).fetchone()
            if row:
                return row[0]
        except Exception:
            pass

    if client is None:
        return joined
    try:
        r = client.messages.create(
            model=model, max_tokens=500, system=_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(paragraphs)}],
        )
        prose = next((b.text for b in r.content if b.type == "text"), "").strip()
    except Exception:
        return joined                                     # model unreachable / no key
    if not prose:
        return joined

    if conn is not None:                                  # cache write (best-effort)
        try:
            conn.execute("INSERT OR REPLACE INTO narrative_cache (cache_key, prose, model, created_at) "
                         "VALUES (?,?,?,?)",
                         (key, prose, model, dt.datetime.now().isoformat(timespec="seconds")))
            conn.commit()
        except Exception:
            pass
    return prose
