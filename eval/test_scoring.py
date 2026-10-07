from scoring import match, score, summarize


def d(title, due=None, weight=None):
    return {"title": title, "dueDate": due, "weightPercent": weight}


def test_perfect_extraction():
    labels = [d("Assignment 1", "2026-10-09", 10), d("Final exam", None, 40)]
    s = score(labels, [d("Assignment 1", "2026-10-09", 10.0), d("Final Exam", None, 40)])
    assert (s["matched"], s["correct"], s["missed"], s["extra"]) == (2, 2, [], [])


def test_wrong_date_is_matched_but_not_correct():
    s = score([d("Midterm", "2026-10-22", 25)], [d("Midterm", "2026-10-21", 25)])
    assert s["matched"] == 1 and s["correct"] == 0 and s["dateCorrect"] == 0 and s["weightCorrect"] == 1


def test_same_date_allows_looser_title():
    pairs = match([d("Assignment 2", "2026-11-01")], [d("A2: ray tracer", "2026-11-01")])
    assert pairs[0][1] is None            # too different even on the same date
    pairs = match([d("Term project proposal", "2026-10-10")], [d("Project proposal", "2026-10-10")])
    assert pairs[0][1] is not None


def test_each_prediction_used_once():
    labels = [d("Lab 1", "2026-09-24"), d("Lab 2", "2026-10-08")]
    s = score(labels, [d("Lab 1", "2026-09-24")])
    assert s["matched"] == 1 and s["missed"] == ["Lab 2"]


def test_extra_predictions_lower_precision():
    per_file = {"a": score([d("Quiz", "2026-10-01", 5)], [d("Quiz", "2026-10-01", 5), d("Reading week")])}
    summary = summarize(per_file)
    assert summary["accuracy"] == 100.0 and summary["precision"] == 50.0
