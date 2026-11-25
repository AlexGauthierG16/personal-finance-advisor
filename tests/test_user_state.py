import ast
import json
from decimal import Decimal as D
from pathlib import Path

import pytest

from backend import analysis, user_state
from backend.parser import parse_csv_text

ROOT = Path(__file__).resolve().parent.parent
EMPTY = {"budget": None, "months": {}}
BUDGET = {"Rent": D("600"), "Groceries": D("200.00"), "Eating out": D("100"), "Transport": D("30"),
          "Subscriptions": D("20"), "Shopping": D("50"), "Other": D("40")}


def raw():
    return json.loads(user_state.STATE_PATH.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ isolation

def test_tests_never_use_the_real_file():
    assert user_state.DEFAULT_PATH == ROOT / "data" / "user_state.json"
    assert user_state.STATE_PATH != user_state.DEFAULT_PATH


def test_the_state_file_is_gitignored():
    patterns = [l.strip() for l in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()]
    assert any(p.startswith("data/user_state.json") for p in patterns)


def imported_names(path):
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names |= {a.name for a in node.names}
    return names


@pytest.mark.parametrize("path", ["backend/llm.py", "backend/agent.py", "backend/categorise.py",
                                  "backend/privacy.py", "eval/run_eval.py"])
def test_nothing_that_talks_to_the_model_can_read_the_state(path):
    assert not any("user_state" in n for n in imported_names(ROOT / path))


def test_only_main_uses_the_state():
    assert any("user_state" in n for n in imported_names(ROOT / "backend/main.py"))


# ------------------------------------------------------------------ the store

def test_fresh_state_is_empty_and_reading_creates_nothing():
    assert user_state.load() == EMPTY
    assert user_state.summary() == {"budget": None, "saved_so_far": "0.00", "months": 0, "by_month": {}}
    assert not user_state.STATE_PATH.exists()


def test_budget_is_saved_and_reloaded_from_disk():
    user_state.save_budget(BUDGET)
    assert user_state.load()["budget"] == BUDGET          # a fresh read, Decimals again
    data = raw()
    assert data["version"] == 1
    assert data["budget"]["Groceries"] == "200.00" and data["budget"]["Rent"] == "600"
    assert all(isinstance(v, str) for v in data["budget"].values())   # never floats


def test_an_edited_budget_replaces_the_old_one():
    user_state.save_budget(BUDGET)
    user_state.save_budget({**BUDGET, "Rent": D("650.00")})
    assert user_state.load()["budget"]["Rent"] == D("650.00")
    assert user_state.load()["budget"]["Groceries"] == D("200.00")


def test_budget_and_months_do_not_overwrite_each_other():
    user_state.save_budget(BUDGET)
    user_state.record_month("2025-09", D("-27.18"))
    user_state.save_budget({**BUDGET, "Rent": D("700")})
    state = user_state.load()
    assert state["months"] == {"2025-09": D("-27.18")}
    assert state["budget"]["Rent"] == D("700")


def test_the_same_month_twice_counts_once_and_the_latest_value_wins():
    user_state.record_month("2025-09", D("-27.18"))
    user_state.record_month("2025-09", D("-27.18"))
    assert user_state.summary()["months"] == 1
    assert user_state.summary()["saved_so_far"] == "-27.18"
    user_state.record_month("2025-09", D("-12.18"))
    assert user_state.summary()["saved_so_far"] == "-12.18"
    assert user_state.summary()["by_month"] == {"2025-09": "-12.18"}


def test_two_different_months_add_up():
    user_state.record_month("2025-09", D("-27.18"))
    user_state.record_month("2025-10", D("-16.67"))
    s = user_state.summary()
    assert s["saved_so_far"] == "-43.85"                    # -27.18 + -16.67
    assert s["months"] == 2
    assert s["by_month"] == {"2025-09": "-27.18", "2025-10": "-16.67"}
    user_state.record_month("2025-10", D("-16.67"))         # re-upload of October: still -43.85
    assert user_state.summary()["saved_so_far"] == "-43.85"


def test_months_that_cancel_out_show_zero():
    user_state.record_month("2025-09", D("50.00"))
    user_state.record_month("2025-10", D("-50.00"))
    assert user_state.summary()["saved_so_far"] == "0.00"


def test_reset_clears_everything():
    user_state.save_budget(BUDGET)
    user_state.record_month("2025-09", D("-27.18"))
    user_state.reset()
    assert user_state.load() == EMPTY
    assert user_state.summary()["months"] == 0
    assert not user_state.STATE_PATH.exists()
    user_state.reset()                                      # nothing to delete: no error


def test_a_save_leaves_no_temporary_file_behind():
    user_state.save_budget(BUDGET)
    user_state.record_month("2025-09", D("1.00"))
    assert sorted(p.name for p in user_state.STATE_PATH.parent.iterdir()) == ["user_state.json"]


def test_record_month_rejects_a_bad_month_or_amount():
    for month in ["2025-9", "September", "2025-13", ""]:
        with pytest.raises(ValueError):
            user_state.record_month(month, D("1"))
    with pytest.raises(ValueError):
        user_state.record_month("2025-09", D("NaN"))
    assert not user_state.STATE_PATH.exists()


# ------------------------------------------------------------------ bad files

def write_bad(text):
    user_state.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    user_state.STATE_PATH.write_text(text, encoding="utf-8")


@pytest.mark.parametrize("text", [
    "not json {",
    "[]",
    '{"version": 2, "budget": null, "months": {}}',
    '{"version": 1, "budget": {"Rent": "-5"}, "months": {}}',
    '{"version": 1, "budget": {"Fun money": "5"}, "months": {}}',
    '{"version": 1, "budget": {"Rent": "abc"}, "months": {}}',
    '{"version": 1, "budget": "600", "months": {}}',
    '{"version": 1, "budget": null, "months": {"2025-13": "1.00"}}',
    '{"version": 1, "budget": null, "months": {"Sept": "1.00"}}',
    '{"version": 1, "budget": null, "months": {"2025-09": "abc"}}',
    '{"version": 1, "budget": null, "months": {"2025-09": "NaN"}}',
    '{"version": 1, "budget": null, "months": []}',
])
def test_a_corrupt_file_is_treated_as_empty_and_kept_aside(text):
    write_bad(text)
    assert user_state.load() == EMPTY                       # no crash
    backup = user_state.STATE_PATH.with_name("user_state.json.corrupt")
    assert backup.read_text(encoding="utf-8") == text       # nothing is lost
    assert not user_state.STATE_PATH.exists()
    user_state.record_month("2025-09", D("1.00"))           # and the app keeps working
    assert user_state.summary()["saved_so_far"] == "1.00"


# ------------------------------------------------------------------ statement_month

def txs(*dates):
    rows = "".join(f"{d},SHOP {i},-1.00\n" for i, d in enumerate(dates))
    return parse_csv_text("date,description,amount\n" + rows)


def test_statement_month_of_the_samples():
    for name, month in [("sample_sept.csv", "2025-09"), ("sample_oct.csv", "2025-10"),
                        ("demo_nov.csv", "2025-11")]:
        text = (ROOT / "data" / name).read_text(encoding="utf-8")
        assert analysis.statement_month(parse_csv_text(text)) == month


def test_statement_month_single_day():
    assert analysis.statement_month(txs("2025-01-05")) == "2025-01"


@pytest.mark.parametrize("dates,named", [
    (("2025-09-30", "2025-10-01"), ["2025-09", "2025-10"]),
    (("2025-12-31", "2026-01-01"), ["2025-12", "2026-01"]),
    (("2024-09-05", "2025-09-05"), ["2024-09", "2025-09"]),      # same month, different years
])
def test_statement_month_refuses_two_months(dates, named):
    with pytest.raises(ValueError) as e:
        analysis.statement_month(txs(*dates))
    message = str(e.value)
    assert "2 months" in message and all(m in message for m in named)


def test_statement_month_needs_transactions():
    with pytest.raises(ValueError):
        analysis.statement_month([])
