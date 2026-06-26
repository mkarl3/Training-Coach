"""Big-ride achievements — the data behind Wattson's celebration moment.

Pure detection over the Strava ride summaries (distance_mi / elev_ft per ride). Five kinds, ordered
by the headline hierarchy below. Two are PERSONAL BESTS (everyone earns them eventually — your
furthest ride, your biggest climbing day); three are ABSOLUTE milestones that stay genuinely rare:

    everest    elevation ≥ 29,029 ft (the showstopper)
    longest    a new LONGEST-EVER ride (distance PB ≥ 50 mi)
    climb_pb   a new BIGGEST-EVER climbing day (elevation PB ≥ 3,000 ft)
    climb10k   elevation ≥ 10,000 ft in one ride
    century    distance ≥ 100 mi

The object Wattson holds CYCLES cowbell → champagne → trophy across achievements (by cumulative
index). The "pending" achievement is the one on the athlete's MOST RECENT ride — so it shows from
when you ride it until the next ride (plus an explicit dismiss). THE ONE RULE: this is data; the
celebration art stays in the frontend.
"""

OBJECTS = ["cowbell", "champagne", "trophy"]   # cycle order — mirrors CELEBRATIONS in Wattson.jsx
CENTURY_MI = 100.0
BIG_CLIMB_FT = 10000.0
EVEREST_FT = 29029.0
PB_MIN_MI = 50.0                               # don't celebrate a "longest ever" below a real ride
CLIMB_PB_MIN_FT = 3000.0                       # ditto for a "biggest climbing day" PB

PRIORITY = ["everest", "longest", "climb_pb", "climb10k", "century"]   # headline hierarchy
CLIMB_FAMILY = ["everest", "climb_pb", "climb10k"]                     # collapse to one for display


def _rides(summaries):
    rs = [s for s in summaries
          if "ride" in (s.get("sport") or "").lower() or s.get("distance_mi")]
    return sorted(rs, key=lambda s: (s.get("start") or s.get("date") or ""))


def _display(kinds):
    """Priority-ordered kinds for display, with the climb family collapsed to its top member so the
    subtitle never double-counts the same big climb (e.g. an Everesting is not also 'a 10k climb')."""
    climb = next((k for k in CLIMB_FAMILY if k in kinds), None)
    return [k for k in PRIORITY if k in kinds and (k not in CLIMB_FAMILY or k == climb)]


def scan(summaries):
    """Walk rides chronologically; return (events, rides). Each event = a ride that earned an
    achievement, carrying its cumulative `index` (for the object cycle)."""
    rides = _rides(summaries)
    events, max_dist, max_elev, idx = [], 0.0, 0.0, 0
    for r in rides:
        dist = r.get("distance_mi") or 0
        elev = r.get("elev_ft") or 0
        kinds = []
        if elev >= EVEREST_FT:
            kinds.append("everest")
        if dist > max_dist and max_dist > 0 and dist >= PB_MIN_MI:
            kinds.append("longest")
        if elev > max_elev and max_elev > 0 and elev >= CLIMB_PB_MIN_FT:
            kinds.append("climb_pb")
        if elev >= BIG_CLIMB_FT:
            kinds.append("climb10k")
        if dist >= CENTURY_MI:
            kinds.append("century")
        if dist > max_dist:
            max_dist = dist
        if elev > max_elev:
            max_elev = elev
        if not kinds:
            continue
        events.append({"ride_id": str(r.get("id")), "date": r.get("date"),
                       "dist": dist, "elev": elev, "kinds": kinds, "index": idx})
        idx += 1
    return events, rides


_TITLE = {"everest": "Everesting!", "longest": "Longest ride ever",
          "climb_pb": "Biggest climbing day", "climb10k": "Huge climbing day", "century": "Century!"}


def _present(ev):
    """One moment per ride: the highest-priority trigger is the headline; any others are folded
    into the subtitle so the ride still gets full credit. The object cycles once per ride."""
    flair = OBJECTS[ev["index"] % len(OBJECTS)]
    dist, elev = round(ev["dist"]), round(ev["elev"])
    disp = _display(ev["kinds"])
    head = disp[0]
    desc = {
        "everest":  f"{elev:,} ft climbed in a single ride",
        "longest":  f"{dist} mi — a new distance record",
        "climb_pb": f"{elev:,} ft — a new climbing record",
        "climb10k": f"{elev:,} ft of climbing in one ride",
        "century":  f"{dist} miles in a single ride",
    }
    second = {"everest": "Everesting", "longest": "a distance PR", "climb_pb": "a climbing PR",
              "climb10k": f"a {elev:,} ft climb", "century": "a century"}
    subtitle = desc[head]
    if disp[1:]:
        subtitle += " · also " + ", ".join(second[k] for k in disp[1:])
    return {"flair": flair, "title": _TITLE[head], "subtitle": subtitle,
            "ride_id": ev["ride_id"], "kind": head, "kinds": ev["kinds"]}


def pending(summaries, dismissed=()):
    """The achievement to celebrate right now: the one earned on the most recent ride, if that ride
    qualifies and hasn't been dismissed. Returns the present-able dict, or None."""
    events, rides = scan(summaries)
    if not events or not rides:
        return None
    last = events[-1]
    if last["ride_id"] != str(rides[-1].get("id")) or last["ride_id"] in set(dismissed):
        return None
    return _present(last)


# --- dismiss store (one row per dismissed ride) on the shared coach.db conn ---
def _ensure(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS achievement_dismissed (ride_id TEXT PRIMARY KEY)")
    conn.commit()


def dismissed_ids(conn):
    _ensure(conn)
    return {row[0] for row in conn.execute("SELECT ride_id FROM achievement_dismissed")}


def dismiss(conn, ride_id):
    _ensure(conn)
    conn.execute("INSERT OR IGNORE INTO achievement_dismissed (ride_id) VALUES (?)", (str(ride_id),))
    conn.commit()
