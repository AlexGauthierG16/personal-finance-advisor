import json
from decimal import Decimal as D
from pathlib import Path

import pytest

from backend import llm
from backend.categorise import read_labels
from backend.parser import parse_csv
from eval import run_eval

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture
def sept():
    txs = parse_csv(DATA / "sample_sept.csv")
    return txs, read_labels(DATA / "sample_sept_labels.csv", txs)


@pytest.fixture(autouse=True)
def safe_env(monkeypatch):
    """Never read the real .env; pretend a key and model are configured."""
    monkeypatch.setattr(run_eval, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("OPENAI_MODEL", "fake-model")


def answer(labels):
    return json.dumps({"categories": [{"id": i, "category": c} for i, c in enumerate(labels)]})


def fake_runs(monkeypatch, per_run):
    """Fake model: call n returns per_run[n] (a list of labels, or a raw string)."""
    calls = []

    def fake(transactions, categories):
        out = per_run[len(calls)]
        calls.append(1)
        return out if isinstance(out, str) else answer(out)
    monkeypatch.setattr(llm, "categorise_with_model", fake)
    return calls


def imperfect_runs(labels):
    run2, run3 = list(labels), list(labels)
    run2[2] = "Shopping"            # Esselunga, truth Groceries
    run3[2] = "Other"
    run3[4] = "Shopping"            # Glovo, truth Eating out
    return [list(labels), run2, run3]


# ------------------------------------------------------------------ evaluate()

def test_evaluate_imperfect_inconsistent(sept):
    txs, truth = sept
    r = run_eval.evaluate(txs, truth, imperfect_runs(truth))
    assert r["per_run"] == [(25, 25), (24, 25), (23, 25)]
    assert r["overall"] == (72, 75)
    assert r["per_category"]["Groceries"] == (16, 18)
    assert r["per_category"]["Eating out"] == (20, 21)
    assert r["per_category"]["Needs review"] == (9, 9)
    assert r["per_category"]["Other"] == (0, 0)          # no such transactions in Sept
    assert r["consistency"] == (23, 25)
    assert [(m["id"], m["truth"], m["answers"]) for m in r["mismatches"]] == [
        (2, "Groceries", ["Groceries", "Shopping", "Other"]),
        (4, "Eating out", ["Eating out", "Eating out", "Shopping"]),
    ]
    assert r["mismatches"][0]["description"] == "ESSELUNGA MILANO LORENTEGGIO"
    assert all(x["ok"] and x["statement_total"] == D("-127.18") for x in r["reconciliation"])
    assert r["meets_target"] is True      # 96.0% >= 90%


def test_evaluate_detects_a_broken_reconciliation(sept):
    txs, truth = sept
    bad = list(truth)
    bad[0] = "Fun money"                  # not a category: totals cannot be trusted
    r = run_eval.evaluate(txs, truth, [truth, bad, truth])
    assert [x["ok"] for x in r["reconciliation"]] == [True, False, True]
    assert r["meets_target"] is False     # totals must be exact too


# ------------------------------------------------------------------ main()

def test_perfect_model(monkeypatch, sept, tmp_path, capsys):
    _, truth = sept
    calls = fake_runs(monkeypatch, [truth] * 3)
    out = tmp_path / "results.md"
    assert run_eval.main(results_path=out, datasets=[run_eval.EASY_SET]) == 0
    assert len(calls) == 3
    report = out.read_text(encoding="utf-8")
    assert report in capsys.readouterr().out
    assert "100.0% (75/75)" in report
    assert "100.0% (25/25)" in report                 # consistency
    assert "3/3" in report                            # runs that reconcile
    assert "-127.18" in report
    assert "fake-model" in report
    assert "test-key-not-real" not in report
    assert "None" in report                           # no mismatches


def test_imperfect_model_report(monkeypatch, sept, tmp_path):
    _, truth = sept
    fake_runs(monkeypatch, imperfect_runs(truth))
    out = tmp_path / "results.md"
    assert run_eval.main(results_path=out, datasets=[run_eval.EASY_SET]) == 0
    report = out.read_text(encoding="utf-8")
    for expected in ["96.0% (72/75)", "100.0% (25/25)", "96.0% (24/25)", "92.0% (23/25)",
                     "88.9% (16/18)", "95.2% (20/21)", "100.0% (9/9)", "n/a",
                     "ESSELUNGA MILANO LORENTEGGIO", "GLOVO ORDER 8841", "Shopping"]:
        assert expected in report, expected


def test_garbage_model_output_everything_needs_review(monkeypatch, sept, tmp_path):
    fake_runs(monkeypatch, ["not json"] * 3)
    out = tmp_path / "results.md"
    assert run_eval.main(results_path=out, datasets=[run_eval.EASY_SET]) == 0
    report = out.read_text(encoding="utf-8")
    assert "12.0% (9/75)" in report                   # only the 3 ambiguous rows match, 3 times
    assert "100.0% (25/25)" in report                 # perfectly consistent, perfectly useless
    assert "-127.18" in report                        # whole statement sits in Needs review
    assert "not met" in report


def test_missing_key_stops_with_a_clear_message(monkeypatch, sept, tmp_path, capsys):
    calls = fake_runs(monkeypatch, [sept[1]] * 3)
    monkeypatch.delenv("OPENAI_API_KEY")
    out = tmp_path / "results.md"
    assert run_eval.main(results_path=out) == 1
    assert "OPENAI_API_KEY" in capsys.readouterr().out
    assert calls == [] and not out.exists()


def test_missing_model_name_stops_too(monkeypatch, sept, tmp_path, capsys):
    calls = fake_runs(monkeypatch, [sept[1]] * 3)
    monkeypatch.setenv("OPENAI_MODEL", "")
    assert run_eval.main(results_path=tmp_path / "r.md") == 1
    assert "OPENAI_MODEL" in capsys.readouterr().out
    assert calls == []


def test_model_failure_stops_without_partial_results(monkeypatch, sept, tmp_path, capsys):
    def boom(transactions, categories):
        raise ConnectionError("secret-detail")
    monkeypatch.setattr(llm, "categorise_with_model", boom)
    out = tmp_path / "results.md"
    assert run_eval.main(results_path=out) == 1
    shown = capsys.readouterr().out
    assert "ConnectionError" in shown and "secret-detail" not in shown
    assert not out.exists()


# ------------------------------------------------------------------ two sets, reported separately

@pytest.fixture
def nov():
    txs = parse_csv(DATA / "demo_nov.csv")
    return txs, read_labels(DATA / "demo_nov_labels.csv", txs)


def fake_by_size(monkeypatch, runs_by_size):
    """Fake model keyed by statement size (25 = sample_sept, 70 = demo_nov); call n gets run n."""
    counts = {}

    def fake(descriptions, categories):
        n = len(descriptions)
        i = counts.get(n, 0)
        counts[n] = i + 1
        out = runs_by_size[n][i]
        return out if isinstance(out, str) else answer(out)
    monkeypatch.setattr(llm, "categorise_with_model", fake)
    return counts


def sections(report):
    easy_at, real_at = report.index("## Easy set"), report.index("## Realistic set")
    assert easy_at < real_at
    return report[easy_at:real_at], report[real_at:]


def test_default_evaluates_both_sets_separately(monkeypatch, sept, nov, tmp_path, capsys):
    counts = fake_by_size(monkeypatch, {25: [sept[1]] * 3, 70: [nov[1]] * 3})
    out = tmp_path / "results.md"
    assert run_eval.main(results_path=out) == 0
    assert counts == {25: 3, 70: 3}                               # 3 runs per set
    report = out.read_text(encoding="utf-8")
    assert report in capsys.readouterr().out
    easy, real = sections(report)
    assert "sample_sept" in easy and "demo_nov" in real
    assert "100.0% (75/75)" in easy and "-127.18" in easy
    assert "100.0% (210/210)" in real and "100.0% (70/70)" in real and "-410.06" in real
    assert "210" not in easy and "75/75" not in real              # nothing is pooled across the sets
    assert "285" not in report                                    # no combined figure either


def test_summary_table_has_one_row_per_set(monkeypatch, sept, nov, tmp_path):
    fake_by_size(monkeypatch, {25: [sept[1]] * 3, 70: [nov[1]] * 3})
    out = tmp_path / "results.md"
    run_eval.main(results_path=out)
    lines = out.read_text(encoding="utf-8").splitlines()
    easy = next(l for l in lines if l.startswith("| Easy set"))
    real = next(l for l in lines if l.startswith("| Realistic set"))
    assert "sample_sept" in easy and "100.0% (75/75)" in easy and "met" in easy
    assert "demo_nov" in real and "100.0% (210/210)" in real and "met" in real


def test_each_set_is_scored_on_its_own_labels(monkeypatch, sept, nov, tmp_path):
    txs, truth = nov
    g = truth.index("Groceries")          # first Groceries line
    e = truth.index("Eating out")         # first Eating out line
    run2, run3 = list(truth), list(truth)
    run2[g] = "Shopping"
    run3[g], run3[e] = "Other", "Shopping"
    fake_by_size(monkeypatch, {25: [sept[1]] * 3, 70: [list(truth), run2, run3]})
    out = tmp_path / "results.md"
    assert run_eval.main(results_path=out) == 0
    easy, real = sections(out.read_text(encoding="utf-8"))
    assert "100.0% (75/75)" in easy and "98.6%" not in easy       # Sept untouched by Nov's mistakes
    # 210 comparisons, 3 wrong: 207/210; per run 70, 69, 68 of 70
    for expected in ["98.6% (207/210)", "100.0% (70/70)", "98.6% (69/70)", "97.1% (68/70)",
                     "95.2% (40/42)",          # Groceries: 14 lines x 3 runs, 2 wrong
                     "98.6% (71/72)",          # Eating out: 24 lines x 3 runs, 1 wrong
                     "97.1% (68/70)",          # consistency: 2 of 70 lines changed between runs
                     txs[g].description, txs[e].description, "-410.06"]:
        assert expected in real, expected


def test_garbage_model_is_scored_per_set(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "categorise_with_model", lambda descriptions, categories: "not json")
    out = tmp_path / "results.md"
    assert run_eval.main(results_path=out) == 0
    easy, real = sections(out.read_text(encoding="utf-8"))
    assert "12.0% (9/75)" in easy                                 # 3 ambiguous lines x 3 runs
    assert "4.3% (9/210)" in real and "100.0% (70/70)" in real    # same 3 lines; all runs agree
    assert "-127.18" in easy and "-410.06" in real                # everything sits in Needs review
    assert "not met" in easy and "not met" in real


def test_failure_in_the_second_set_stops_and_names_it(monkeypatch, sept, tmp_path, capsys):
    def fake(descriptions, categories):
        if len(descriptions) == 70:
            raise ConnectionError("secret-detail")
        return answer(sept[1])
    monkeypatch.setattr(llm, "categorise_with_model", fake)
    out = tmp_path / "results.md"
    assert run_eval.main(results_path=out) == 1
    shown = capsys.readouterr().out
    assert "realistic set" in shown and "demo_nov" in shown and "ConnectionError" in shown
    assert "secret-detail" not in shown
    assert not out.exists()


def test_unreadable_labels_stop_before_any_model_call(monkeypatch, sept, tmp_path, capsys):
    bad = tmp_path / "bad_labels.csv"
    bad.write_text("date,description,category\n2025-09-01,SOMETHING ELSE,Income\n", encoding="utf-8")
    broken = run_eval.Dataset("realistic", "Realistic set", "demo_nov", DATA / "demo_nov.csv", bad)
    counts = fake_by_size(monkeypatch, {25: [sept[1]] * 3})
    out = tmp_path / "results.md"
    assert run_eval.main(results_path=out, datasets=[run_eval.EASY_SET, broken]) == 1
    shown = capsys.readouterr().out
    assert "demo_nov" in shown and "No model calls were made" in shown
    assert counts == {} and not out.exists()                      # the easy set was not even started


def test_the_real_labels_match_the_statements():
    for ds in run_eval.DATASETS:
        txs = parse_csv(ds.statement)
        labels = read_labels(ds.labels, txs)                      # raises if rows or categories differ
        assert len(labels) == len(txs)
    assert [ds.name for ds in run_eval.DATASETS] == ["sample_sept", "demo_nov"]
