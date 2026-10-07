"""Measure deadline-extraction accuracy against hand-labelled syllabi.

    # call the model on every labelled syllabus (uses your AWS credentials; costs a few cents each)
    python eval/run_eval.py

    # re-score a previous run without calling the model (free; use after fixing labels or scoring)
    python eval/run_eval.py --rescore eval/results/2026-10-07T12-00-00.json

Runs the exact production code path: extract_text -> extract_deadlines -> validate.
Label format: see eval/labels/example.json.
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend" / "src"))
sys.path.insert(0, str(HERE))

from lib.llm import DEFAULT_MODEL_ID  # noqa: E402
from scoring import score, summarize  # noqa: E402


def load_labels(labels_dir):
    labels = {}
    for path in sorted(Path(labels_dir).glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("example"):
            continue
        labels[path.stem] = data
    return labels


def predict(label):
    from extract_deadlines import extract
    from extract_text import check_size, extract_pages
    from validate import validate

    pdf = (HERE / label["pdf"]).read_bytes()
    pages = extract_pages(pdf)
    check_size(pages)
    validated = validate(extract(pages, label.get("termStart")), label.get("termStart"))
    return validated["deadlines"]


def report(summary, per_file):
    print()
    for name, s in per_file.items():
        print(f"{name:30} {s['correct']:>3}/{s['labeled']:<3} correct   "
              f"missed {len(s['missed'])}  extra {len(s['extra'])}  wrong {len(s['wrong'])}")
    print()
    print(f"Deadlines extracted correctly: {summary['accuracy']}%  "
          f"({summary['correct']}/{summary['labeled']} across {len(per_file)} syllabi)")
    print(f"  recall {summary['recall']}%   precision {summary['precision']}%   "
          f"date accuracy {summary['dateAccuracy']}%   weight accuracy {summary['weightAccuracy']}%")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--labels", default=HERE / "labels")
    parser.add_argument("--rescore", help="results JSON from an earlier run; skips model calls")
    args = parser.parse_args()

    labels = load_labels(args.labels)
    if not labels:
        sys.exit(f"No labels in {args.labels}. Copy eval/labels/example.json and fill it in.")

    if args.rescore:
        predictions = json.loads(Path(args.rescore).read_text(encoding="utf-8"))["predictions"]
    else:
        os.environ.setdefault("AWS_REGION", "us-east-1")
        predictions = {}
        for name, label in labels.items():
            print(f"extracting {name}...", flush=True)
            predictions[name] = predict(label)

    per_file = {name: score(label["deadlines"], predictions.get(name, [])) for name, label in labels.items()}
    summary = summarize(per_file)
    report(summary, per_file)

    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{datetime.now().strftime('%Y-%m-%dT%H-%M-%S')}.json"
    out.write_text(json.dumps({
        "model": os.environ.get("MODEL_ID", DEFAULT_MODEL_ID),
        "summary": summary,
        "perFile": per_file,
        "predictions": predictions,
    }, indent=2), encoding="utf-8")
    print(f"\nSaved {out.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
