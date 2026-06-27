"""Derived-metrics library (Slice 1, Part A).

Two layers:
  1. Pure functions (Series/DataFrame in -> Series/DataFrame out). No DB, no config
     globals, no hidden state. These are what the tests hand-verify.
  2. A `Metrics` facade that loads the daily/workout tables once and calls the pure
     functions with values from a single MetricsConfig. Detectors (Part B) consume the
     facade only, never raw tables, so each metric is defined exactly once.

Series are indexed by a daily DatetimeIndex over ACTUAL days only (is_projected=0);
projected future rows (tss_sum NULL) are excluded from windowed computation.
"""
import numpy as np
import pandas as pd

from .config import DEFAULT, MetricsConfig


# ----------------------------------------------------------------------------- #
# Pure functions
# ----------------------------------------------------------------------------- #
def ramp_rate(ctl, window_days):
    """CTL change per week over `window_days`. Returns TSS/day per week (CTL pts/week)."""
    delta = ctl - ctl.shift(window_days)
    return delta * (7.0 / window_days)


def foster_monotony(daily_load, window_days, ddof=0, min_days=None):
    """Foster monotony = rolling mean / rolling SD of daily load. Rest days (0) count.
    SD==0 (a flat window) -> NaN (undefined), not infinity."""
    min_p = window_days if min_days is None else min_days
    roll = daily_load.rolling(window_days, min_periods=min_p)
    mean = roll.mean()
    sd = roll.std(ddof=ddof)
    mono = mean / sd.replace(0.0, np.nan)
    return mono


def foster_strain(daily_load, window_days, ddof=0, min_days=None):
    """Foster strain = (sum of load over window) * monotony."""
    min_p = window_days if min_days is None else min_days
    total = daily_load.rolling(window_days, min_periods=min_p).sum()
    return total * foster_monotony(daily_load, window_days, ddof=ddof, min_days=min_days)


def acwr_ewma(daily_load, acute_span, chronic_span, min_days=None):
    """EWMA ACWR. alpha = 2/(span+1), recursive (adjust=False). Returns DataFrame
    with acute, chronic, acwr. acwr gated to NaN until `min_days` of history.

    CAVEAT (see config): acute load is mathematically coupled into chronic load."""
    acute = daily_load.ewm(alpha=2.0 / (acute_span + 1), adjust=False).mean()
    chronic = daily_load.ewm(alpha=2.0 / (chronic_span + 1), adjust=False).mean()
    acwr = acute / chronic.replace(0.0, np.nan)
    out = pd.DataFrame({"acute": acute, "chronic": chronic, "acwr": acwr})
    if min_days:
        out.iloc[:min_days, out.columns.get_loc("acwr")] = np.nan
    return out


def _ols_slope(y):
    x = np.arange(len(y), dtype=float)
    # slope of best-fit line; len>=2 guaranteed by min_periods
    return np.polyfit(x, y, 1)[0]


def tsb_trajectory(tsb, window_days, flat_eps):
    """Direction & slope of TSB over a rolling window (OLS slope, TSB pts/day)."""
    slope = tsb.rolling(window_days, min_periods=window_days).apply(_ols_slope, raw=True)

    def label(s):
        if pd.isna(s):
            return None
        if s > flat_eps:
            return "rising"
        if s < -flat_eps:
            return "falling"
        return "flat"

    direction = slope.map(label)
    return pd.DataFrame({"tsb_slope": slope, "tsb_direction": direction})


def aerobic_decoupling(workouts, long_ride_min_sec, high_pct):
    """Per long ride: Pw:Hr decoupling % (from WKO5 workout.pwhr_pct, since intra-ride
    streams aren't exported). Rides shorter than the threshold are excluded; long rides
    missing power/HR/pwHr are returned with sufficient=False (gated)."""
    w = workouts[(workouts["is_cycling"] == 1)
                 & (workouts["duration_sec"].fillna(0) >= long_ride_min_sec)].copy()
    sufficient = w["pwhr_pct"].notna() & w["avg_hr_bpm"].notna() & w["np_w"].notna()
    w["decoupling_pct"] = w["pwhr_pct"].where(sufficient)
    w["sufficient"] = sufficient
    w["decoupled"] = np.where(sufficient, w["pwhr_pct"] > high_pct, None)
    return w[["date", "started_at", "duration_sec", "decoupling_pct",
              "sufficient", "decoupled"]].reset_index(drop=True)


def power_duration_ratio(workouts):
    """Per cycling ride: 1hr/2hr peak-power ratio and gap, gated where 2hr is absent."""
    w = workouts[workouts["is_cycling"] == 1].copy()
    has_both = w["p1hr_w"].notna() & w["p2hr_w"].notna() & (w["p2hr_w"] > 0)
    w["pd_ratio_1h_2h"] = (w["p1hr_w"] / w["p2hr_w"]).where(has_both)
    w["pd_gap_1h_2h_w"] = (w["p1hr_w"] - w["p2hr_w"]).where(has_both)
    w["sufficient"] = has_both
    return w[["date", "started_at", "p1hr_w", "p2hr_w",
              "pd_ratio_1h_2h", "pd_gap_1h_2h_w", "sufficient"]].reset_index(drop=True)


def demonstrated_sustainable_floor(ctl_daily, hold_weeks, window_weeks, as_of=True):
    """Dynamic personal CTL floor (def. A): the highest weekly-mean CTL the athlete
    HELD for >= hold_weeks consecutive weeks within the trailing window_weeks.

    Mechanism: weekly-mean CTL -> rolling `hold_weeks` MIN = the floor each 8-week run
    actually held -> trailing MAX of that over the window = best demonstrated base.

    as_of=True (early-warning): trailing max uses only weeks <= the evaluation week —
    NO lookahead; the floor on day t reflects only what was knowable by t.
    as_of=False (retrospective): a single demonstrated-best scalar over all history,
    broadcast across the series (the best base ever held).

    Returns a daily Series aligned to ctl_daily.index (forward-filled from weekly).
    """
    weekly = ctl_daily.resample("W").mean()
    held = weekly.rolling(hold_weeks, min_periods=hold_weeks).min()
    if as_of:
        floor_weekly = held.rolling(window_weeks, min_periods=1).max()
    else:
        floor_weekly = pd.Series(held.max(), index=weekly.index)
    return floor_weekly.reindex(ctl_daily.index, method="ffill")


def demonstrated_sustainable_ramp(weekly_ctl, floor_weekly, ramp_cap,
                                  percentile=75.0, hold_weeks=3, giveback_frac=0.5):
    """The DEMONSTRATED-SAFE weekly CTL ramp — what the athlete has absorbed AND KEPT, not
    their historical max (which would encode the spike-then-crash pattern we're guarding).

    Take positive week-over-week CTL gains during genuine building (CTL above half the best
    demonstrated floor — skips near-zero detrained noise), KEEP only those that were sustained
    (the gain wasn't given back beyond `giveback_frac` of it within the next `hold_weeks`), and
    report the `percentile`th of those, capped at `ramp_cap`. None when history can't show one.
    Pure: weekly CTL + weekly floor in, scalar (or None) out — hand-verifiable.
    """
    wk = weekly_ctl.dropna()
    if wk.size < hold_weeks + 4:
        return None
    ctl, ramp, flo = wk.values, wk.diff().values, floor_weekly.reindex(wk.index).ffill().values
    fmax = np.nanmax(flo) if flo.size else np.nan
    gate = fmax * 0.5 if np.isfinite(fmax) else 0.0
    safe = []
    for i in range(1, len(wk)):
        r = ramp[i]
        if not np.isfinite(r) or r <= 0 or ctl[i] < gate:
            continue
        future = ctl[i + 1:i + 1 + hold_weeks]
        if future.size and np.nanmin(future) < ctl[i] - giveback_frac * r:
            continue                                       # gain given back -> not sustained
        safe.append(r)
    if not safe:
        return None
    return round(min(float(np.percentile(safe, percentile)), ramp_cap), 1)


def demonstrated_safe_acute_ratio(weekly_tss, min_chronic, percentile=75.0,
                                  hold_weeks=3, giveback_frac=0.5):
    """The DEMONSTRATED-SAFE acute jump — how big a single week's load this athlete can pile on
    over their recent baseline WITHOUT it leading to a crash. Same discipline as the sustainable
    ramp: it's NOT their historical max (that includes the spikes that broke them).

    For each week, ratio = that week's TSS / the prior 4-week average ('how much harder than
    you'd recently been training'). Keep only step-UP weeks whose load was then SUSTAINED (not
    given back beyond `giveback_frac` within `hold_weeks` — i.e. it didn't precede a collapse),
    over a meaningful chronic base (>= min_chronic). Report the `percentile`th of those safe
    ratios. None when history can't demonstrate one. Pure: weekly TSS in, scalar (or None) out.
    """
    wk = weekly_tss.dropna()
    if wk.size < hold_weeks + 5:
        return None
    v = wk.values
    safe = []
    for i in range(4, len(wk)):
        chronic = float(v[i - 4:i].mean())
        if chronic < min_chronic or v[i] <= chronic:          # only genuine step-ups over a real base
            continue
        future = v[i + 1:i + 1 + hold_weeks]
        if future.size and float(np.nanmin(future)) < giveback_frac * v[i]:
            continue                                          # load collapsed after -> spike-then-crash
        safe.append(v[i] / chronic)
    if not safe:
        return None
    return round(float(np.percentile(safe, percentile)), 2)


def trailing_zero_ride_streak(has_ride):
    """Per-day count of consecutive trailing has_ride==0 days (0 on a ride day).
    A gap is has_ride==0, NOT tss_sum==0 (a logged ride with missing TSS is not a gap)."""
    out, c = [], 0
    for v in has_ride:
        c = 0 if v == 1 else c + 1
        out.append(c)
    return pd.Series(out, index=has_ride.index, name="zero_ride_streak")


def expanding_peak(series):
    """Prior peak with NO lookahead: expanding max up to and including each day."""
    return series.cummax()


def consecutive_runs_above(weekly, floor):
    """Per-week running count of consecutive weeks with value >= floor (resets on break)."""
    out, c = [], 0
    for v in weekly:
        c = c + 1 if (pd.notna(v) and v >= floor) else 0
        out.append(c)
    return pd.Series(out, index=weekly.index)


def gray_zone_fraction(workouts, daily_index, low, high, window_days):
    """Rolling fraction of CYCLING workouts whose workout-grain IF is in [low,high].
    Reads workout.if_ (NEVER daily.if_daily, which is display-only)."""
    w = workouts[(workouts["is_cycling"] == 1) & workouts["if_"].notna()].copy()
    w["d"] = pd.to_datetime(w["date"])
    inband = ((w["if_"] >= low) & (w["if_"] <= high)).astype(int)
    by = pd.DataFrame({"d": w["d"], "inband": inband, "n": 1}).groupby("d").sum()
    by = by.reindex(daily_index, fill_value=0)
    roll_in = by["inband"].rolling(window_days, min_periods=1).sum()
    roll_n = by["n"].rolling(window_days, min_periods=1).sum()
    return roll_in / roll_n.replace(0, np.nan)


def distribution_concentration(shares_df):
    """Herfindahl index of zone shares (Σ share²). Uniform -> 1/n; single zone -> 1.
    Rising = distribution NARROWING (monotony's distribution leg)."""
    return (shares_df ** 2).sum(axis=1, min_count=1)


def rolling_best(workouts, col, daily_index, window_days):
    """Per-day rolling max of a per-workout power column over cycling workouts."""
    w = workouts[(workouts["is_cycling"] == 1) & workouts[col].notna()].copy()
    s = w.groupby(pd.to_datetime(w["date"]))[col].max().reindex(daily_index)
    return s.rolling(window_days, min_periods=1).max()


def rolling_slope(series, window_days):
    """OLS slope (units/day) over a rolling window; NaN until the window fills."""
    return series.rolling(window_days, min_periods=window_days).apply(_ols_slope, raw=True)


def tiz_distribution(daily_tiz, zone_cols, window_days):
    """Rolling per-zone share. zone_cols: ordered list of TiZ second-columns. Returns a
    DataFrame of shares (0..1) per zone; rows with zero total time over the window -> NaN."""
    z = daily_tiz[zone_cols].fillna(0.0)
    roll = z.rolling(window_days, min_periods=1).sum()
    total = roll.sum(axis=1)
    shares = roll.div(total.replace(0.0, np.nan), axis=0)
    shares.columns = [c.replace("_sec", "_share") for c in zone_cols]
    return shares


# ----------------------------------------------------------------------------- #
# Data loading
# ----------------------------------------------------------------------------- #
POWER_ZONE_COLS = [f"tiz_pwr_z{i}_sec" for i in range(1, 7)]
HR_ZONE_COLS = [f"tiz_hr_z{i}_sec" for i in range(1, 6)]


def load_daily(conn, actual_only=True):
    """Load `daily` as a DatetimeIndex-frame. actual_only drops is_projected rows."""
    df = pd.read_sql_query("SELECT * FROM daily ORDER BY date", conn)
    if actual_only:
        df = df[df["is_projected"] == 0].copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    return df


def load_workouts(conn):
    df = pd.read_sql_query("SELECT * FROM workout ORDER BY started_at", conn)
    return df


# ----------------------------------------------------------------------------- #
# Facade — the single point where config meets the pure functions
# ----------------------------------------------------------------------------- #
class Metrics:
    def __init__(self, conn, config: MetricsConfig = DEFAULT, profile=None):
        from .profile import DEFAULT_PROFILE
        self.cfg = config
        self.profile = profile or DEFAULT_PROFILE   # athlete-relative constants live here
        self.daily = load_daily(conn, actual_only=True)
        self.workouts = load_workouts(conn)

    # daily load series with rest days = 0 (real inputs), contiguous over actual days.
    @property
    def daily_load(self):
        return self.daily["tss_sum"].astype(float)

    def ramp_rate(self):
        return ramp_rate(self.daily["ctl"].astype(float), self.cfg.ramp_window_days)

    def monotony(self):
        return foster_monotony(self.daily_load, self.cfg.monotony_window_days,
                               self.cfg.monotony_sd_ddof, self.cfg.monotony_min_days)

    def strain(self):
        return foster_strain(self.daily_load, self.cfg.monotony_window_days,
                             self.cfg.monotony_sd_ddof, self.cfg.monotony_min_days)

    def acwr(self):
        return acwr_ewma(self.daily_load, self.cfg.acwr_acute_span_days,
                         self.cfg.acwr_chronic_span_days, self.cfg.acwr_min_days)

    def tsb_trajectory(self):
        return tsb_trajectory(self.daily["tsb"].astype(float),
                              self.cfg.tsb_window_days, self.cfg.tsb_flat_eps)

    def decoupling(self):
        return aerobic_decoupling(self.workouts, self.cfg.long_ride_min_sec,
                                  self.cfg.decoupling_high_pct)

    def power_duration(self):
        return power_duration_ratio(self.workouts)

    def _floor_window_weeks(self):
        return int(round(self.profile.floor_window_months * 52 / 12))

    def personal_ctl_floor_asof(self):
        """No-lookahead dynamic floor for the early-warning variant."""
        return demonstrated_sustainable_floor(
            self.daily["ctl"].astype(float), self.profile.floor_hold_weeks,
            self._floor_window_weeks(), as_of=True)

    def personal_ctl_floor(self):
        """Retrospective demonstrated-best floor (constant scalar broadcast daily)."""
        return demonstrated_sustainable_floor(
            self.daily["ctl"].astype(float), self.profile.floor_hold_weeks,
            self._floor_window_weeks(), as_of=False)

    def personal_sustainable_ramp(self, percentile=75.0, hold_weeks=3, giveback_frac=0.5):
        """The athlete's DEMONSTRATED-SAFE weekly CTL ramp — what they've actually absorbed
        and kept, not their historical max (which would bake in their spike-then-crash pattern).
        Like the CTL floor, a retrospective trait read off full history. Capped by the profile's
        ramp_rate_cap; None when history is too thin (caller falls back to a method default)."""
        wk = self.weekly_ctl().dropna()
        floor_wk = self.personal_ctl_floor().resample("W").last().reindex(wk.index).ffill()
        return demonstrated_sustainable_ramp(
            wk, floor_wk, self.profile.ramp_rate_cap, percentile, hold_weeks, giveback_frac)

    def weekly_tss(self):
        """Actual weekly TSS (summed from per-workout/daily TSS — no CTL math involved)."""
        return self.daily["tss_sum"].astype(float).resample("W").sum()

    def personal_safe_acute_ratio(self, percentile=75.0):
        """The athlete's DEMONSTRATED-SAFE acute jump (this-week-TSS / recent-baseline) that didn't
        precede a crash — derived from summed actual TSS, not a literature constant."""
        return demonstrated_safe_acute_ratio(self.weekly_tss(), self.profile.acwr_min_chronic_load,
                                             percentile)

    # --- Slice 5 phase-progression helpers ---
    def fractional_utilization(self, as_of=None, window_days=42):
        """mFTP as a % of modeled power-at-VO2max (curve-modeled 5-min power, daily `pvo2max_w` from
        the Om3CP fit — validated to match WKO's mFTP%VO2max, ~84%). The sourced Base->Build gate.
        None when the metrics aren't available (e.g. a DB built before pvo2max_w existed). The
        "is there a fresh max effort" check lives separately in band_staleness('vo2', observed)."""
        ao = pd.Timestamp(as_of) if as_of else self.daily.index.max()
        ftp = float(self.mftp.asof(ao))
        pv = self.daily["pvo2max_w"].asof(ao) if "pvo2max_w" in self.daily.columns else None
        vo2 = float(pv) if pv is not None and pd.notna(pv) else None
        if vo2 is None or vo2 <= 0 or not np.isfinite(ftp):
            return None
        return {"pct": round(100.0 * ftp / vo2, 1), "mftp": round(ftp), "vo2_power": round(vo2),
                "vo2_date": ao.strftime("%Y-%m-%d")}

    # which per-ride power column anchors each duration band (for staleness)
    _BAND_COL = {"short": "p5s_w", "medium": "p1min_w", "vo2": "p5min_w", "long": "p20min_w"}

    def band_staleness(self, as_of=None, fresh_frac=0.93, window_days=90):
        """Days since the last GENUINE max effort in each duration band (a ride whose band power is
        within fresh_frac of the trailing-window best). None = no effort in that band. The modeled
        metrics (Pmax/FRC/VO2/mFTP) are only trustworthy when their band is fresh."""
        ao = pd.Timestamp(as_of) if as_of else self.daily.index.max()
        w = self.workouts.copy()
        w["_d"] = pd.to_datetime(w["date"])
        w = w[w["_d"] <= ao]
        out = {}
        for band, col in self._BAND_COL.items():
            ww = w.assign(_v=pd.to_numeric(w[col], errors="coerce")).dropna(subset=["_v"])
            recent = ww[ww["_d"] > ao - pd.Timedelta(days=window_days)]
            if recent.empty:
                out[band] = None
                continue
            peak = float(recent["_v"].max())
            fresh = recent[recent["_v"] >= fresh_frac * peak]
            out[band] = int((ao - fresh["_d"].max()).days)
        return out

    def ctl_change(self, as_of=None, days=28):
        """CTL delta over the trailing `days` (absorption / building check)."""
        ao = pd.Timestamp(as_of) if as_of else self.daily.index.max()
        c = self.ctl.dropna()
        a, b = c.asof(ao - pd.Timedelta(days=days)), c.asof(ao)
        if not (np.isfinite(a) and np.isfinite(b)):
            return None
        return round(float(b - a), 1)

    def readiness_from_form(self, as_of=None, floor=0.7, low_pct=0.30):
        """Objective readiness BACKSTOP from current form (TSB), athlete-relative. ~1.0 normally;
        eases only when TSB sits low in the athlete's OWN range — genuine fatigue they might not
        report. No-lookahead (TSB up to as_of). Returns a 0..1 factor (it can only tighten)."""
        tsb = self.tsb.dropna()
        if tsb.size < 30:
            return 1.0
        cur = float(tsb.asof(pd.Timestamp(as_of))) if as_of else float(tsb.iloc[-1])
        if not np.isfinite(cur):
            return 1.0
        pct = float((tsb.values <= cur).mean())          # where today's form sits, 0..1
        if pct >= low_pct:
            return 1.0
        return round(floor + (1.0 - floor) * (pct / low_pct), 2)

    def tiz_power_distribution(self):
        return tiz_distribution(self.daily, POWER_ZONE_COLS, self.cfg.tiz_window_days)

    def tiz_hr_distribution(self):
        return tiz_distribution(self.daily, HR_ZONE_COLS, self.cfg.tiz_window_days)

    # --- thin primitive accessors (detectors read these, never the raw tables) ---
    @property
    def ctl(self):
        return self.daily["ctl"].astype(float)

    @property
    def atl(self):
        return self.daily["atl"].astype(float)

    @property
    def tsb(self):
        return self.daily["tsb"].astype(float)

    @property
    def mftp(self):
        return self.daily["mftp_w"].astype(float)

    @property
    def has_ride(self):
        return self.daily["has_ride"].astype(int)

    def zero_ride_streak(self):
        return trailing_zero_ride_streak(self.has_ride)

    def prior_peak_ctl(self):
        return expanding_peak(self.ctl)

    def recent_peak_ctl(self, window_days):
        """Trailing-window CTL peak — 'did a real build happen recently'."""
        return self.ctl.rolling(f"{window_days}D", min_periods=1).max()

    def ctl_percentile_threshold(self, pct, as_of=True):
        """Dynamic per-athlete fitness line = the Pxx percentile of the athlete's own CTL.
        Scales to whoever the athlete is. as_of=True uses an EXPANDING (history-to-date,
        no-lookahead) percentile — valid for early-warning; as_of=False uses the all-history
        percentile (retrospective). Returns a daily Series."""
        ctl = self.ctl.dropna()
        if as_of:
            thr = ctl.expanding(min_periods=self.cfg.ctl_percentile_min_days).quantile(pct / 100.0)
            return thr.reindex(self.daily.index).ffill()
        return pd.Series(float(np.nanpercentile(ctl.values, pct)), index=self.daily.index)

    def weekly_ctl(self):
        return self.ctl.resample("W").mean()

    def consecutive_weeks_above_floor(self, as_of=True):
        floor = (self.personal_ctl_floor_asof() if as_of else self.personal_ctl_floor())
        floor_weekly = floor.resample("W").last()
        wk = self.weekly_ctl()
        out, c = [], 0
        for dt, v in wk.items():
            f = floor_weekly.get(dt, np.nan)
            c = c + 1 if (pd.notna(v) and pd.notna(f) and v >= f) else 0
            out.append(c)
        return pd.Series(out, index=wk.index)

    def active_ride_days(self, window_days):
        """Rolling count of ride days in the trailing window (the 'thread alive' gate)."""
        return self.has_ride.rolling(window_days, min_periods=1).sum()

    def gray_zone_if_fraction(self):
        return gray_zone_fraction(self.workouts, self.daily.index, self.cfg.if_band_low,
                                  self.cfg.if_band_high, self.cfg.monotony_window_days)

    def tiz_power_concentration(self):
        return distribution_concentration(self.tiz_power_distribution())

    def mmp_best(self, col, window_days):
        return rolling_best(self.workouts, col, self.daily.index, window_days)

    def tsb_percentile(self, pct):
        return float(np.nanpercentile(self.tsb.values, pct))

    def flags_in_window(self, start, end):
        """Union of advisory data_flags tokens on days inside [start, end] (inclusive)."""
        seg = self.daily.loc[str(start):str(end), "data_flags"].dropna()
        toks = set()
        for v in seg:
            for t in str(v).split(";"):
                if t:
                    toks.add(t)
        return sorted(toks)
