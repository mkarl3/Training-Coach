"""Diary classifier tests (Slice 4.5, step 1). The LLM classification itself is exercised by
the demo; here we hand-verify the STRUCTURAL GATE — the part that must hold even if the model
misbehaves: fabricated quotes, malformed/illogical dates, ambiguity without a question, and
hard kinds missing the input they map to all get rejected. Proposals only; nothing is applied."""
from plan import diary
from plan.diary import AdjustmentKind as K, DiaryItem


MSG = ("I caught the flu and was off the bike Monday through Wednesday. "
       "Family's away this weekend so I've got about 12 hours free. Legs feel great.")


def item(**kw):
    base = dict(kind=K.soft, summary="x", quote="Legs feel great", confidence=0.9)
    base.update(kw)
    return DiaryItem(**base)


def test_verbatim_quote_gate_rejects_fabrication():
    good = item(quote="Legs feel great")
    bad = item(quote="I am completely exhausted and need two weeks off")   # not in the message
    acc, rej = diary.validate_items([good, bad], MSG)
    assert good in acc and bad not in acc
    assert any(n is bad and reason == "quote_not_verbatim" for n, reason in rej)


def test_none_is_dropped_silently():
    acc, rej = diary.validate_items([item(kind=K.none, quote="x")], MSG)
    assert acc == [] and rej == []                         # not plan-relevant -> ignored


def test_hard_time_loss_needs_dates():
    no_dates = item(kind=K.hard_time_loss, quote="off the bike Monday through Wednesday",
                    summary="flu, out 3 days")
    with_dates = item(kind=K.hard_time_loss, quote="off the bike Monday through Wednesday",
                      summary="flu, out 3 days", start_date="2026-06-08", end_date="2026-06-10",
                      reason="flu", severity="mild")
    acc, rej = diary.validate_items([no_dates, with_dates], MSG)
    assert with_dates in acc
    assert no_dates not in acc and any(r[1] == "time_loss_without_dates" for r in rej)


def test_capacity_up_needs_a_window():
    bare = item(kind=K.hard_capacity_up, quote="I've got about 12 hours free")
    good = item(kind=K.hard_capacity_up, quote="I've got about 12 hours free",
                available_hours=12.0, start_date="2026-06-13")
    acc, rej = diary.validate_items([bare, good], MSG)
    assert good in acc
    assert bare not in acc and any(r[1] == "capacity_up_without_window" for r in rej)


def test_future_dates_allowed_for_opportunity():
    # capacity-up is inherently forward-looking; the gate must NOT clamp to a past window.
    fut = item(kind=K.hard_capacity_up, quote="Family's away this weekend",
               available_hours=12.0, start_date="2026-12-25")
    acc, _ = diary.validate_items([fut], MSG)
    assert fut in acc


def test_ambiguous_must_carry_a_question():
    no_q = item(kind=K.ambiguous, quote="I caught the flu", confidence=0.4)
    with_q = item(kind=K.ambiguous, quote="I caught the flu", confidence=0.4,
                  clarifying_question="How many days do you expect to be off the bike?")
    acc, rej = diary.validate_items([no_q, with_q], MSG)
    assert with_q in acc
    assert no_q not in acc and any(r[1] == "ambiguous_without_question" for r in rej)


def test_dates_must_be_wellformed_and_ordered():
    bad = item(kind=K.hard_time_loss, quote="off the bike Monday through Wednesday",
               start_date="2026-13-99", end_date="2026-06-10")
    backwards = item(kind=K.hard_time_loss, quote="off the bike Monday through Wednesday",
                     start_date="2026-06-10", end_date="2026-06-08")
    acc, rej = diary.validate_items([bad, backwards], MSG)
    assert acc == []
    reasons = {r[1] for r in rej}
    assert "bad_start_date" in reasons and "end_before_start" in reasons


def test_confidence_must_be_in_range():
    acc, rej = diary.validate_items([item(confidence=1.7, quote="Legs feel great")], MSG)
    assert acc == [] and any(r[1] == "bad_confidence" for r in rej)


def test_soft_needs_no_inputs():
    acc, _ = diary.validate_items([item(kind=K.soft, quote="Legs feel great")], MSG)
    assert len(acc) == 1 and acc[0].kind == K.soft


def test_soft_item_carries_optional_readiness():
    # a soft 'fried' read can grade readiness; it still passes the gate (no special input required).
    it = item(kind=K.soft, quote="Legs feel great", readiness="low")
    acc, _ = diary.validate_items([it], MSG)
    assert it in acc and it.readiness == "low"


# --- step 3: recurring-theme advisory (non-binding) ---
def test_recurring_theme_needs_multiple_checkins():
    rows = [
        (1, "sleep", "slept badly"), (1, "fatigue", "wiped"),     # checkin 1
        (2, "sleep", "rough night again"),                        # checkin 2
        (3, "sleep", "still not sleeping"), (3, "stress", "work"),  # checkin 3
    ]
    themes = diary.recurring_themes(rows, min_checkins=3)
    assert [t["category"] for t in themes] == ["sleep"]           # sleep in 3 check-ins; others <3
    sleep = themes[0]
    assert sleep["checkins"] == 3 and sleep["label"] == "sleep"
    assert "slept badly" in sleep["quotes"]


def test_recurring_theme_counts_distinct_checkins_not_mentions():
    rows = [(1, "fatigue", "a"), (1, "fatigue", "b"), (1, "fatigue", "c")]   # 3 mentions, 1 checkin
    assert diary.recurring_themes(rows, min_checkins=3) == []     # one check-in is not a pattern


def test_recurring_theme_ignores_logistics_categories():
    rows = [(i, "time_constraint", "busy") for i in range(1, 5)]  # 4 check-ins, but logistics
    assert diary.recurring_themes(rows, min_checkins=3) == []


def test_advisory_text_is_neutral_and_quotes():
    themes = diary.recurring_themes(
        [(1, "soreness_pain", "knee sore"), (2, "soreness_pain", "knee again"),
         (3, "soreness_pain", "still sore")], min_checkins=3)
    txt = diary.advisory_text(themes)
    assert "soreness/pain" in txt and "3 recent check-ins" in txt and "knee sore" in txt
    assert diary.advisory_text([]) is None
