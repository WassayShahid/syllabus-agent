from datetime import date

from validate import validate, week_monday


def entry(**overrides):
    base = {"title": "Assignment 1", "type": "assignment", "dueDate": None, "dueTime": None, "week": None,
            "weekday": None, "weightPercent": None, "sourceText": "A1", "page": 1}
    return {**base, **overrides}


def test_week_one_contains_term_start():
    # 2026-09-08 is a Tuesday -> week 1 starts Monday 2026-09-07
    assert week_monday(date(2026, 9, 8), 1) == date(2026, 9, 7)
    assert week_monday(date(2026, 9, 8), 7) == date(2026, 10, 19)


def test_week_and_weekday_resolve_exactly():
    out = validate({"deadlines": [entry(week=3, weekday="Thu")]}, "2026-09-08")
    d = out["deadlines"][0]
    assert d["dueDate"] == "2026-09-24"
    assert d["dateApproximate"] is False


def test_week_without_weekday_is_approximate_monday():
    out = validate({"deadlines": [entry(title="Midterm", type="midterm", week=7)]}, "2026-09-08")
    d = out["deadlines"][0]
    assert d["dueDate"] == "2026-10-19"
    assert d["dateApproximate"] is True


def test_code_overrides_model_date_math_and_warns():
    out = validate({"deadlines": [entry(week=3, weekday="Thu", dueDate="2026-09-25")]}, "2026-09-08")
    assert out["deadlines"][0]["dueDate"] == "2026-09-24"
    assert any("using 2026-09-24" in w for w in out["warnings"])


def test_week_without_term_start_stays_undated_with_warning():
    out = validate({"deadlines": [entry(week=5)]}, None)
    assert out["deadlines"][0]["dueDate"] is None
    assert any("no term start" in w for w in out["warnings"])


def test_explicit_date_kept_when_no_week():
    out = validate({"deadlines": [entry(dueDate="2026-10-04", dueTime="23:59")]}, "2026-09-08")
    d = out["deadlines"][0]
    assert (d["dueDate"], d["dueTime"]) == ("2026-10-04", "23:59")


def test_bad_values_are_cleaned():
    out = validate({"deadlines": [
        entry(title="  ", dueDate="2026-10-01"),
        entry(title="Quiz", type="pop-quiz", dueDate="not a date", dueTime="25:00", weightPercent="7.5%", page=0),
        entry(title="Lab", weightPercent=140),
    ]}, "2026-09-08")
    quiz, lab = sorted(out["deadlines"], key=lambda d: d["title"])[::-1]
    assert quiz["type"] == "other" and quiz["dueDate"] is None and quiz["dueTime"] is None
    assert quiz["weightPercent"] == 7.5 and quiz["page"] is None
    assert lab["weightPercent"] is None
    assert len(out["deadlines"]) == 2


def test_out_of_term_date_flagged():
    out = validate({"deadlines": [entry(dueDate="2027-08-01")]}, "2026-09-08")
    assert any("far outside the term" in w for w in out["warnings"])


def test_duplicates_removed():
    out = validate({"deadlines": [entry(dueDate="2026-10-04"), entry(title="assignment 1", dueDate="2026-10-04")]})
    assert len(out["deadlines"]) == 1


def test_weight_total_warning_only_when_all_weighted():
    off = validate({"deadlines": [entry(weightPercent=30), entry(title="Final", weightPercent=30)]})
    assert any("add up to 60" in w for w in off["warnings"])
    partial = validate({"deadlines": [entry(weightPercent=30), entry(title="Final")]})
    assert not any("add up" in w for w in partial["warnings"])


def test_empty_extraction_warns():
    out = validate({"deadlines": []}, "2026-09-08")
    assert out["deadlines"] == [] and out["warnings"]


def test_sorted_dated_first():
    out = validate({"deadlines": [entry(title="Final"), entry(title="A2", dueDate="2026-11-01"),
                                  entry(title="A1", dueDate="2026-10-01")]})
    assert [d["title"] for d in out["deadlines"]] == ["A1", "A2", "Final"]
