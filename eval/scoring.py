"""Match predicted deadlines to hand labels and compute accuracy.

A prediction *matches* a label when the titles are similar (one title's words all appear in the
other, e.g. "A1" vs "Assignment 1 (A1)", counts as similar), or when both have the same due date
and the same non-zero weight. A matched deadline is *correct* when its date and weight are both
right; that's the headline number.
"""
import re
from difflib import SequenceMatcher

SAME_DATE_TITLE_THRESHOLD = 0.5
ANY_DATE_TITLE_THRESHOLD = 0.75


def _norm(title):
    return re.sub(r"[^a-z0-9 ]", "", (title or "").lower()).strip()


def similarity(a, b):
    na, nb = _norm(a), _norm(b)
    da, db = set(re.findall(r"\d+", na)), set(re.findall(r"\d+", nb))
    if da and db and da != db:                     # "Assignment 2" is never "Assignment 1"
        return 0.0
    ta, tb = set(na.split()), set(nb.split())
    if ta and tb and (ta <= tb or tb <= ta):       # one title's words all appear in the other
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def _weight_ok(label, pred):
    lw, pw = label.get("weightPercent"), pred.get("weightPercent")
    if lw is None or pw is None:
        return lw is None and pw is None
    return abs(float(lw) - float(pw)) < 0.01


def match(labels, preds):
    """Greedy best-first matching. Returns [(label, pred_or_None)]."""
    candidates = []
    for li, label in enumerate(labels):
        for pi, pred in enumerate(preds):
            sim = similarity(label["title"], pred["title"])
            same_date = label.get("dueDate") == pred.get("dueDate")
            # same date + same non-zero weight is the same deliverable, however it's titled
            same_slot = same_date and label.get("dueDate") and _weight_ok(label, pred) and label.get("weightPercent")
            if same_slot or sim >= (SAME_DATE_TITLE_THRESHOLD if same_date else ANY_DATE_TITLE_THRESHOLD):
                candidates.append((same_date, sim, li, pi))
    candidates.sort(reverse=True)            # same-date pairs first, then by title similarity
    used_l, used_p, pairs = set(), set(), {}
    for _, _, li, pi in candidates:
        if li not in used_l and pi not in used_p:
            used_l.add(li)
            used_p.add(pi)
            pairs[li] = pi
    return [(label, preds[pairs[li]] if li in pairs else None) for li, label in enumerate(labels)]


def score(labels, preds):
    pairs = match(labels, preds)
    matched = [(l, p) for l, p in pairs if p is not None]
    date_ok = [(l, p) for l, p in matched if l.get("dueDate") == p.get("dueDate")]
    weight_ok = [(l, p) for l, p in matched if _weight_ok(l, p)]
    correct = [(l, p) for l, p in matched if l.get("dueDate") == p.get("dueDate") and _weight_ok(l, p)]
    matched_preds = {id(p) for _, p in matched}
    return {
        "labeled": len(labels),
        "predicted": len(preds),
        "matched": len(matched),
        "correct": len(correct),
        "dateCorrect": len(date_ok),
        "weightCorrect": len(weight_ok),
        "missed": [l["title"] for l, p in pairs if p is None],
        "extra": [p["title"] for p in preds if id(p) not in matched_preds],
        "wrong": [{"label": l, "predicted": {k: p.get(k) for k in ("title", "dueDate", "weightPercent")}}
                  for l, p in matched if (l, p) not in correct],
    }


def summarize(per_file):
    totals = {k: sum(s[k] for s in per_file.values()) for k in
              ("labeled", "predicted", "matched", "correct", "dateCorrect", "weightCorrect")}

    def pct(n, d):
        return round(100 * n / d, 1) if d else None

    return {
        **totals,
        "accuracy": pct(totals["correct"], totals["labeled"]),       # headline: % of real deadlines fully right
        "recall": pct(totals["matched"], totals["labeled"]),
        "precision": pct(totals["matched"], totals["predicted"]),
        "dateAccuracy": pct(totals["dateCorrect"], totals["matched"]),
        "weightAccuracy": pct(totals["weightCorrect"], totals["matched"]),
    }
