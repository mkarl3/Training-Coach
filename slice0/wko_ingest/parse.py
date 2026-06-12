"""Cell-level parsers: normalize WKO5 export cells to canonical types.

Rules:
- The export sentinel '--' and blank/empty cells -> None (NULL), never 0.
- All durations -> integer seconds.
- US units (mi, lb, W, kJ, bpm, rpm, %) are preserved as numbers as-is.
"""
import datetime
import re

MISSING = {"--", "", "n/a", "na", "none"}

_HMS_TOKEN_RE = re.compile(
    r"^\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+)\s*s)?\s*$", re.IGNORECASE
)


def is_missing(v):
    if v is None:
        return True
    if isinstance(v, str) and v.strip().lower() in MISSING:
        return True
    return False


def parse_float(v):
    """Numbers and numeric strings -> float; sentinel/blank -> None."""
    if is_missing(v):
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace(",", "")
        try:
            return float(s)
        except ValueError:
            return None
    return None


def parse_str(v):
    if is_missing(v):
        return None
    return str(v).strip()


def parse_duration_sec(v, two_part="ms"):
    """Normalize a duration cell to integer seconds.

    Handles: datetime.time, datetime.timedelta, 'h:m:s' / 'm:s' strings, and the
    WKO token form like '12m31s', '1m52s', '33m27s'. two_part controls how a
    single-colon string ('A:B') is read: 'ms' -> minutes:seconds (durations),
    'hm' -> hours:minutes (sleep columns whose unit is 'h:m').
    """
    if is_missing(v):
        return None
    if isinstance(v, datetime.timedelta):
        return int(round(v.total_seconds()))
    if isinstance(v, datetime.time):
        return v.hour * 3600 + v.minute * 60 + v.second
    if isinstance(v, datetime.datetime):
        # Unexpected for a duration column; treat the time-of-day as the duration.
        return v.hour * 3600 + v.minute * 60 + v.second
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        # A bare number in a duration column is ambiguous; reject rather than guess.
        return None
    if isinstance(v, str):
        s = v.strip()
        if s.lower() in MISSING:
            return None
        if ":" in s:
            parts = s.split(":")
            try:
                nums = [int(p) for p in parts]
            except ValueError:
                return None
            if len(parts) == 3:
                h, m, sec = nums
            elif len(parts) == 2:
                if two_part == "hm":
                    h, m, sec = nums[0], nums[1], 0
                else:
                    h, m, sec = 0, nums[0], nums[1]
            else:
                return None
            return h * 3600 + m * 60 + sec
        m = _HMS_TOKEN_RE.match(s)
        if m and any(m.groups()):
            h = int(m.group(1) or 0)
            mins = int(m.group(2) or 0)
            sec = int(m.group(3) or 0)
            return h * 3600 + mins * 60 + sec
        return None
    return None


def parse_date(v):
    """Return ISO 'YYYY-MM-DD' from a datetime/date/string, else None."""
    if is_missing(v):
        return None
    if isinstance(v, datetime.datetime):
        return v.date().isoformat()
    if isinstance(v, datetime.date):
        return v.isoformat()
    if isinstance(v, str):
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
            try:
                return datetime.datetime.strptime(v.strip(), fmt).date().isoformat()
            except ValueError:
                continue
    return None


def parse_datetime(v):
    """Return full ISO timestamp 'YYYY-MM-DDTHH:MM:SS' from a datetime, else date-only."""
    if is_missing(v):
        return None
    if isinstance(v, datetime.datetime):
        return v.replace(microsecond=0).isoformat()
    d = parse_date(v)
    return d
