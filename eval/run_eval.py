"""Evaluation: categorise data/sample_sept.csv with the real model 3 times and compare
with the hand-made labels. Run from the repo root:  python -m eval.run_eval

Reports accuracy (overall, per run, per category), the mismatches, consistency across runs,
and whether the category totals add up to the statement total. Writes eval/results.md.
The model is only reached through backend.categorise -> backend.llm.
"""
import os
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from dotenv import load_dotenv

from backend import analysis, categorise
from backend.agent import money
from backend.categorise import CATEGORIES, NEEDS_REVIEW, read_labels
from backend.parser import parse_csv

ROOT = Path(__file__).resolve().parent.parent
STATEMENT = ROOT / "data" / "sample_sept.csv"
LABELS = ROOT / "data" / "sample_sept_labels.csv"
RESULTS_PATH = Path(__file__).resolve().parent / "results.md"
RUNS = 3
TARGET_PERCENT = 90  # project goal (README): at least 90% matching categories, totals exact


def pct(matches: int, total: int) -> str:
    """e.g. '96.0% (72/75)'; computed from counts with Decimal. 'n/a' if there is nothing to count."""
    if total == 0:
        return "n/a"
    value = (Decimal(100 * matches) / Decimal(total)).quantize(Decimal("0.1"), ROUND_HALF_UP)
    return f"{value}% ({matches}/{total})"


def evaluate(transactions, truth, runs) -> dict:
    """Compare each run's labels with the ground truth. All inputs are label lists in statement order."""
    n, k = len(transactions), len(runs)
    per_run = [(sum(a == b for a, b in zip(run, truth)), n) for run in runs]
    overall = (sum(m for m, _ in per_run), n * k)

    per_category = {}
    for category in CATEGORIES:
        idx = [i for i, t in enumerate(truth) if t == category]
        per_category[category] = (sum(run[i] == category for run in runs for i in idx), len(idx) * k)

    mismatches = [
        {"id": i, "date": transactions[i].date.isoformat(), "description": transactions[i].description,
         "truth": truth[i], "answers": [run[i] for run in runs]}
        for i in range(n) if any(run[i] != truth[i] for run in runs)
    ]
    consistency = (sum(len({run[i] for run in runs}) == 1 for i in range(n)), n)

    statement_total = sum((t.amount for t in transactions), Decimal("0"))
    reconciliation = []
    for run in runs:
        try:
            totals = analysis.totals_by_category(transactions, run)
            analysis.check_totals(totals, transactions)
            ok, category_total, needs_review = True, sum(totals.values(), Decimal("0")), totals[NEEDS_REVIEW]
        except ValueError:
            ok, category_total, needs_review = False, None, None
        reconciliation.append({"ok": ok, "statement_total": statement_total,
                               "category_total": category_total, "needs_review": needs_review})

    meets_target = (100 * overall[0] >= TARGET_PERCENT * overall[1]
                    and all(r["ok"] for r in reconciliation))
    return {"transactions": n, "runs": k, "per_run": per_run, "overall": overall,
            "per_category": per_category, "mismatches": mismatches, "consistency": consistency,
            "reconciliation": reconciliation, "meets_target": meets_target}


def _cell(text) -> str:
    return str(text).replace("|", "\\|")


def render_report(result: dict, model: str, when: str) -> str:
    k, rec = result["runs"], result["reconciliation"]
    reconciled = sum(r["ok"] for r in rec)
    lines = [
        "# Categorisation evaluation", "",
        f"- Model: `{model}`", f"- Date: {when}",
        f"- Statement: `data/sample_sept.csv` ({result['transactions']} transactions), "
        f"{k} runs, compared with `data/sample_sept_labels.csv`", "",
        "## Summary", "",
        "| Metric | Result |", "|---|---|",
        f"| Matching the hand labels (all runs) | {pct(*result['overall'])} |",
        f"| Same category in all {k} runs | {pct(*result['consistency'])} |",
        f"| Runs whose category totals add up to the statement total | {reconciled}/{k} |",
        f"| Project target (at least {TARGET_PERCENT}% matching and exact totals) | "
        f"{'met' if result['meets_target'] else 'not met'} |", "",
        "## Per run", "",
        "| Run | Matching | Needs review amount | Totals add up |", "|---|---|---|---|",
    ]
    for i, ((m, t), r) in enumerate(zip(result["per_run"], rec), start=1):
        nr = "n/a" if r["needs_review"] is None else money(r["needs_review"])
        if r["ok"]:
            check = f"yes ({money(r['category_total'])} = {money(r['statement_total'])})"
        else:
            check = f"FAIL (statement {money(r['statement_total'])})"
        lines.append(f"| {i} | {pct(m, t)} | {nr} | {check} |")
    lines += ["", "## Per category (hand label, all runs pooled)", "",
              "| Category | Matching |", "|---|---|"]
    lines += [f"| {c} | {pct(*result['per_category'][c])} |" for c in CATEGORIES]
    lines += ["", "## Mismatches", ""]
    if not result["mismatches"]:
        lines.append("None.")
    else:
        header = ["Date", "Description", "Hand label"] + [f"Run {i}" for i in range(1, k + 1)]
        lines += ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        for m in result["mismatches"]:
            row = [m["date"], m["description"], m["truth"], *m["answers"]]
            lines.append("| " + " | ".join(_cell(c) for c in row) + " |")
    return "\n".join(lines) + "\n"


def main(results_path=RESULTS_PATH) -> int:
    load_dotenv()
    missing = [name for name in ("OPENAI_API_KEY", "OPENAI_MODEL") if not os.environ.get(name)]
    if missing:
        print(f"Cannot run the evaluation. Not set: {', '.join(missing)}. "
              "Put them in the .env file (see .env.example) and run again. No model calls were made.")
        return 1

    transactions = parse_csv(STATEMENT)
    truth = read_labels(LABELS, transactions)
    runs = []
    for i in range(1, RUNS + 1):
        print(f"Run {i}/{RUNS}: asking the model to categorise {len(transactions)} transactions...")
        try:
            runs.append(categorise.categorise(transactions))
        except Exception as e:  # stop cleanly; never leave a half-finished results file
            print(f"Evaluation stopped: the model call failed ({type(e).__name__}). "
                  "Check the API key, the model name and the network. Nothing was saved.")
            return 1

    report = render_report(evaluate(transactions, truth, runs), os.environ["OPENAI_MODEL"],
                           datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
    Path(results_path).write_text(report, encoding="utf-8")
    print()
    print(report)
    print(f"Saved to {results_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
