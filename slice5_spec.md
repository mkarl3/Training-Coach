# Slice 5 — Phase-Progression Autoregulation (SPEC, for sign-off)

Wattson advises when to move between training blocks (Base 1→Base 2, Base 3→Build 1, …) from
**phase-specific metrics**, not the calendar alone. He *advises*; the athlete confirms; code
recomputes. Validated against the primary WKO5/CTS knowledgebase (not the AI-derived matrix).

THE ONE RULE holds: deterministic gate checks in code → Wattson narrates → propose-confirm →
recompute. Nothing advances silently.

---

## 1. Locked principles

- **Asymmetry.** Tightening is fast/cheap (already built — readiness dampener). Advancing must be
  *earned*, gradual, propose-confirm.
- **Never advance early** when a peak exists (A *or* B race). No-goal / C-race-only plans may
  advance on readiness. The gate is **HOLD-or-PROCEED at the planned boundary**, not early promotion.
- **Advance when the target metric PLATEAUS**, with 3 mandatory qualifiers: (a) flat **2–3 weeks**;
  (b) only **after the response window** — never inside the first ~3–4 weeks (acute fatigue 5–10 d
  masks fitness); (c) **hard + soft data agree** on **validated, smoothed** inputs.
- **Race clock governs.** Each block has a `min_weeks` (adaptation floor) AND a race-derived
  `latest_exit` (so downstream blocks still get their floor before race day).
- **Confidence/staleness is first-class.** A stale model → *"go do the benchmark"*, never a guessed
  verdict.
- **Honesty.** Thin/stale/uncertain → say so (honest-miss ethos). Every non-sourced threshold is
  flagged `TUNABLE` in code.

---

## 2. The per-phase gates

`have` = in our data; `proxy` = computed substitute (de-proxy when the data add lands);
`SOURCED` = explicit in KB; `TUNABLE` = our default, not sourced.

| Transition | Gate signal | Advance when | Data | Source |
|---|---|---|---|---|
| **Prep → Base 1** | CTL ramp on track + consistency | ramp inside safe band AND compliance ≥ thresh, no detraining | CTL/ramp `have`, compliance `have` | ramp SOURCED; compliance thresh TUNABLE |
| **Base 1 → Base 2** | volume absorbed | min_weeks met AND CTL ramp held AND not over-fatigued (TSB/ATL sane) AND able to add TiZ | `have` | absorption/TiZ progression SOURCED; "absorbed" thresh TUNABLE |
| **Base 2 → Base 3** | intensive-aerobic TiZ progressed + FTP starting to respond | min_weeks met AND tempo/SS TiZ sustained AND mFTP not falling | TiZ `have`, mFTP `have` | TiZ-progression SOURCED; cutoffs TUNABLE |
| **Base 3 → Build 1** ⭐ | **fractional utilization** = mFTP / power-at-VO2max | % in **81–85% band** (vs athlete's own history) AND flat 2–3 wk; if < ~80–81% → stay in base | mFTP `have`, pVO2max **proxy = p5min_w** | **SOURCED** (Cusick, Building FTP/TTE/Stamina); 81–85% band SOURCED, individualized off own history |
| **Build 1 → Build 2** | VO2max power rising→flat (time-boxed) | 2–5 wk gain window done AND 5-min power stops climbing AND aerobic TIS impulse falling | p5min_w `have`, aerobic_tis `have` | time-box + frontloaded gains SOURCED; "stops climbing" TUNABLE |
| **Build 2 → Peak** | anaerobic impulse spent + cooked | anaerobic TIS impulse falling AND fatigue high (TSB low) AND block ≥ ceiling 4–7 wk | anaerobic_tis `have`, TSB `have` | falling-impulse + ceiling SOURCED; FRC read AVOIDED (artifact) |
| **Peak → Race** | **calendar** (taper backward from race) | date-driven, NOT a metric gate | — | per user; metrics only *monitor/confirm* |

Notes:
- ⭐ **Base 3 → Build 1 is the keystone gate** — best-sourced, power-only. v1 uses the 5-min-power
  proxy for pVO2max (so the band may read high while the proxy is stale — that triggers "needs
  benchmark", see §3, rather than a false "ready").
- **FRC is deliberately NOT a gate** (the FTP↔FRC model artifact: FRC shrinks as FTP rises). We read
  fatigue + falling anaerobic TIS impulse instead.
- The within-base/within-build sub-steps are intentionally *softer* (absorption + min_weeks + "able
  to progress"), because the sources gate the **major** transitions (Prep→Base, Base→Build,
  Build→Peak), not each sub-block. We surface progress for all, but only the major gates carry a
  strong metric verdict.

---

## 3. Staleness / confidence model

Every modeled metric only means something with a recent **max effort** in its duration band:

| Band | Effort | Feeds |
|---|---|---|
| short | 1–10 s | Pmax / neuromuscular |
| medium | ~1 min | FRC / anaerobic |
| 5-min | ~5 min | VO2max power (our base→build proxy) |
| long | 20–60 min | mFTP / TTE / aerobic |

**v1 confidence (no residuals exported):** `days_since_fresh_max_in_band` →
`fresh < 14 d · aging 14–42 d · stale > 42 d` (re-feed cadence ~8 wk = 56 d cap). All `TUNABLE`.
(If WKO export later exposes **normalized residuals / per-metric C.V.**, fold them in — SOURCED 5–10
rule.)

- **Smoothing (kills single-session wiggle):** TTE on **28-day EWMA** (SOURCED); others on a short
  rolling median. **Plateau = |slope| ≈ 0 over 2–3 wk on the smoothed series.**
- A gate whose metric is **stale → verdict `NEEDS_BENCHMARK`** → Wattson asks for the *specific*
  effort. The **field-test week** (already at every block end in `canonical_blocks`) is when it's
  scheduled — that's the keystone that re-seeds confidence before a verdict is trusted.

---

## 4. Decision logic (at the boundary, `min_weeks` met)

```
if metric stale            -> NEEDS_BENCHMARK   (hold pending field test)
elif red flags             -> BACK_OFF          (PD trending down / compliance off / overreached → recovery, not advance)
elif gate READY            -> ADVANCE           (propose; recompute)
elif race-time has buffer  -> HOLD              (extend 1 wk; surface cost: steals buffer / lowers peak — honest-miss)
elif at latest_exit        -> PROCEED_WITH_DEBT (advance but shape next block conservative / carry unfinished work; narrate the tradeoff)
```
- **Before `min_weeks`:** not evaluated for advance — show progress only; ignore any plateau inside
  the fatigue-mask window.
- **Never advance early** even if READY early (peak-anchored): hold the schedule, keep it fresh /
  seed a touch of the next stimulus.

---

## 5. The contingency (Wattson's 4th beat — an engine requirement)

The assessment emits not just a verdict but the **branch**, stated *before* the week happens:
> *"This week's test of the gate is `<X>`. Clear it → we advance (peak unaffected). Miss it → we
> hold one week (peak ~−1 fitness), or if the clock's tight, we move on and keep Build 1 conservative."*

So `assess_progression` returns `{ verdict, this_week_test, branches:[{outcome, action, calendar_cost}] }`.

---

## 6. Where Wattson narrates

- **Dashboard hero (beats 1–2):** *this week + why* · *phase position + what's gating*. The
  phase-specific metric cards (replacing the generic Fitness/Form vitals) show the gate metrics with
  progress + a **confidence chip** (fresh/aging/stale). The **Advance / Hold** proposal + buttons live
  here (decision co-located with the metrics).
- **Weekly check-in (beats 3–4):** the *contingency* + *calendar impact*; the full propose-confirm.
- **Calendar:** reflects the structural outcome after confirm (block extended / advanced, trajectory
  shifted, honest-miss updated).

---

## 7. Engine shape / where it lives

- **New pure module `slice4/plan/progression.py`:** `assess_progression(m, plan, as_of, profile) ->
  PhaseProgress` = `{ current_block, gate{metric,target,value,trend,plateau,confidence},
  verdict, this_week_test, branches[], min_weeks_met, latest_exit, cost_if_hold }`.
- **New metric helpers** (slice1 `metrics.py`): `fractional_utilization()` (mFTP / 5-min power),
  `plateau(series, weeks=3)`, `band_staleness(as_of)` (days since fresh max per band).
- **Reuses:** `canonical_blocks` (operationalizes the `advance_when` text + `field_test` markers);
  plan-vs-actual compliance; the diff/confirm/recompute path; honest-miss; generator block min_weeks.
- **API:** `GET /api/progression` (assessment). Advance/Hold = propose→confirm reusing the existing
  `/api/plan/adjustment/confirm` semantics (recompute advances or extends the block).
- **Frontend:** dashboard hero phase-cards + advise; calendar reflects.

---

## 8. v1 scope vs deferred

**v1 (build now, current data + proxies):** Prep + Base gates (CTL ramp, consistency,
fractional-utilization via 5-min proxy, absorption sub-steps) + Build gates present;
staleness/confidence (days-since-max-effort); min/max-weeks + conflict logic; the five verdicts;
contingency branch; Wattson beats 1–2 + 4; dashboard phase-cards + advise; calendar reflects.
*Honest reality:* for a detrained athlete most Build gates will read `NEEDS_BENCHMARK` — correct, not
a bug.

**Deferred:** the WKO data adds (pVO2max/Stamina/freshness-diagnostics/LT1 → de-proxy); phenotype/
event-specific gate selection (v1 uses the generic per-phase metric); general-goal/no-event path;
B/C race micro-structure; multi-A-race; residual-based confidence.

---

## 9. Open decisions for sign-off

1. **Build order:** assessment engine + API first (verify on your data as plain JSON), CHECKPOINT,
   then the dashboard phase-cards + advise UI? (matches our slice cadence)
2. **`min_weeks` source:** use `canonical_blocks` nominal weeks as the floor, or a separate
   adaptation-rate-derived floor (base ≥4, build ≥3)?
3. **Confidence thresholds** (14 d / 42 d / 56 d) and the **compliance threshold** for "consistent" —
   accept as tunable v1 defaults, or set differently?
4. **Within-base sub-steps:** advise on each (Base 1→2→3) as soft "you're absorbing it, step up", or
   only fire a strong verdict at the major gates (Prep→Base, Base→Build, Build→Peak)?
