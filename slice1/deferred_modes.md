# Deferred failure modes — captured, NOT built

Modes observed in the data that have no worked spec/discriminator yet. Recorded so they
aren't lost. **Out of scope** until each gets its own definition (and validation on ≥2 athletes).

## Mode 7 — Stagnation despite process (process-green, outcome-flat)
Discussed in Slice 1; fires only when none of modes 1–6 fire and outcome metrics
(mFTP / MMP) are flat over N weeks. No worked discriminator yet. Do not build.

## Mode 8 (candidate) — Multi-year detraining drift / slow decline
**Observed in this athlete.** Per-year **best CTL drifts down across seasons**:

| year | best CTL (per-year p75 / peak) |
|---|---|
| 2023 | p75 **38**, peak 50 |
| 2024 | p75 **36**, peak 42 |
| 2025 | p75 **30**, peak 41 |
| 2026 | p75 **33**, peak 37 |

The ceiling is eroding year over year. **No single-block detector catches this** — every
Slice-1 detector reasons within a season/block (gap_unravel, under_load, monotony, etc.),
and each individual year can look locally acceptable while the multi-year trajectory sinks.
This is a *slow-decline / multi-season-stagnation* signal operating on a horizon longer than
any current detector's window.

Note: the **dynamic personal CTL floor** already encodes part of this implicitly — the
demonstrated-sustainable-base floor falls as old high blocks age out of the trailing window
(retrospective best-held ≈ 41 vs as-of-today ≈ 31). A future mode-8 could surface that drift
explicitly (e.g. trend of per-season peak/sustained CTL, or of the as-of floor itself) rather
than leaving it implicit.

**Deferred.** Needs its own spec: horizon, the outcome metric it tracks, the discriminator
that separates "deliberate detraining / life phase" from "unintended slow decline," and a
reset condition. Not in Slice 2.
