"""Local memory for a single user: the last budget and the savings of each analysed month.

Stored in data/user_state.json (gitignored). Only main.py uses this module: the file is never
read by, or sent to, the model (llm.py, agent.py, categorise.py and privacy.py do not import it).

Format: {"version": 1, "budget": {"Rent": "600", ...} | null, "months": {"2025-09": "-27.18"}}.
Money is stored as strings and parsed with Decimal, never floats. Writes are atomic. A file that
cannot be read as this format is moved aside to user_state.json.corrupt and treated as empty.
Single local user: no locking, not safe for concurrent use.
"""
import json
import os
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from backend.categorise import EXPENSE_CATEGORIES

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "user_state.json"
STATE_PATH = DEFAULT_PATH  # read at call time, so tests can point it at a temporary file
VERSION = 1
MONTH = re.compile(r"\d{4}-(?:0[1-9]|1[0-2])")
BUDGET_CATEGORIES = EXPENSE_CATEGORIES + ("Other",)


def _empty() -> dict:
    return {"budget": None, "months": {}}


def _decimal(value) -> Decimal:
    if not isinstance(value, str):
        raise ValueError("amounts are stored as text")
    number = Decimal(value)  # InvalidOperation (a subclass of ArithmeticError) if not a number
    if not number.is_finite():
        raise ValueError("amount is not finite")
    return number


def _parse(text: str) -> dict:
    data = json.loads(text)
    if not isinstance(data, dict) or data.get("version") != VERSION:
        raise ValueError("unknown format")
    budget = data.get("budget")
    if budget is not None:
        if not isinstance(budget, dict):
            raise ValueError("budget must be an object")
        parsed = {}
        for category, value in budget.items():
            if category not in BUDGET_CATEGORIES:
                raise ValueError(f"unknown category {category!r}")
            parsed[category] = _decimal(value)
            if parsed[category] < 0:
                raise ValueError("negative budget")
        budget = parsed
    months = data.get("months", {})
    if not isinstance(months, dict):
        raise ValueError("months must be an object")
    parsed_months = {}
    for month, value in months.items():
        if not MONTH.fullmatch(str(month)):
            raise ValueError(f"bad month {month!r}")
        parsed_months[month] = _decimal(value)
    return {"budget": budget, "months": parsed_months}


def load() -> dict:
    """{"budget": {category: Decimal} | None, "months": {"YYYY-MM": Decimal}}. Never creates the file."""
    path = Path(STATE_PATH)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _empty()
    try:
        return _parse(text)
    except (ValueError, InvalidOperation, TypeError):  # includes bad JSON
        try:
            os.replace(path, path.with_name(path.name + ".corrupt"))
        except OSError:
            pass
        return _empty()


def _write(state: dict) -> None:
    path = Path(STATE_PATH)
    data = {
        "version": VERSION,
        "budget": None if state["budget"] is None else {c: str(v) for c, v in state["budget"].items()},
        "months": {m: str(v) for m, v in sorted(state["months"].items())},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def save_budget(budget: dict) -> None:
    """Replace the saved budget ({category: Decimal})."""
    state = load()
    state["budget"] = {c: Decimal(v) for c, v in budget.items()}
    _write(state)


def record_month(month: str, savings: Decimal) -> None:
    """Set the savings of one month; recording the same month again replaces it (never adds)."""
    if not MONTH.fullmatch(month):
        raise ValueError(f"bad month {month!r}")
    if not Decimal(savings).is_finite():
        raise ValueError("savings must be a finite number")
    state = load()
    state["months"][month] = Decimal(savings)
    _write(state)


def reset() -> None:
    """Forget everything."""
    Path(STATE_PATH).unlink(missing_ok=True)


def _fmt(value: Decimal) -> str:
    return "0.00" if value == 0 else str(value)


def summary() -> dict:
    """Display strings: the budget, the running total over all months, the month count, per month."""
    state = load()
    total = sum(state["months"].values(), Decimal("0"))
    return {
        "budget": None if state["budget"] is None else {c: _fmt(v) for c, v in state["budget"].items()},
        "saved_so_far": _fmt(total),
        "months": len(state["months"]),
        "by_month": {m: _fmt(v) for m, v in sorted(state["months"].items())},
    }
