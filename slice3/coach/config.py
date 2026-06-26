"""Coach config — all knobs named here, not inline."""
from dataclasses import dataclass


@dataclass(frozen=True)
class CoachConfig:
    # --- Retrieval ---
    # Top-K methodology chunks handed to the model per question. Too few misses guidance;
    # too many drowns the model and slows/costs more. Tunable.
    methodology_chunks_per_query: int = 5
    # Chunking: passages of roughly this many words, built from whole paragraphs,
    # with one-paragraph overlap so a thought split across a boundary isn't lost.
    chunk_target_words: int = 350
    chunk_min_words: int = 60          # merge tiny trailing chunks into the previous one
    # Minimum cosine similarity for a chunk to count as "supporting methodology".
    # Below this, retrieval returns nothing rather than junk -> coach must soft-flag.
    min_similarity: float = 0.08

    # --- Corpus (frozen, versioned; re-index only on deliberate updates) ---
    corpus_version: str = "2026-06-12.v1"

    # --- LLM (used by capture + coach, not retrieval) ---
    # Current Anthropic model id (verified 2026-06); defined ONCE here, never inline.
    model: str = "claude-opus-4-8"
    max_tokens: int = 1200
    # Dashboard narrative polish is a pure reword-with-fixed-facts job — no reasoning — so it runs
    # on the cheaper/faster Sonnet tier ($3/$15 vs Opus $5/$25 per MTok), not the coach's Opus.
    narrative_model: str = "claude-sonnet-4-6"
    # Capture: how far back a note may be dated relative to the check-in date.
    capture_lookback_days: int = 14


DEFAULT = CoachConfig()
