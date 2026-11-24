"""Assigns a category to each transaction: asks llm.py, then validates the answer."""
import json

from backend import llm

INCOME = "Income"
TRANSFER = "Transfer to own account"
NEEDS_REVIEW = "Needs review"

CATEGORIES = (
    "Rent",
    "Groceries",
    "Eating out",
    "Transport",
    "Subscriptions",
    "Shopping",
    INCOME,
    TRANSFER,
    "Other",
    NEEDS_REVIEW,
)


def read_labels(path, transactions) -> list[str]:
    """Read a labels CSV (date,description,category) aligned row-by-row with transactions.

    Raises ValueError on a length/date/description mismatch or a category outside CATEGORIES.
    """
    import csv
    from datetime import date
    from pathlib import Path

    with Path(path).open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != len(transactions):
        raise ValueError(f"{len(rows)} labels for {len(transactions)} transactions")
    labels = []
    for n, (row, tx) in enumerate(zip(rows, transactions), start=2):
        if date.fromisoformat(row["date"].strip()) != tx.date or row["description"].strip() != tx.description:
            raise ValueError(f"line {n}: label row does not match the transaction")
        category = row["category"].strip()
        if category not in CATEGORIES:
            raise ValueError(f"line {n}: unknown category {category!r}")
        labels.append(category)
    return labels


def parse_model_answer(raw, n: int) -> list[str]:
    """Turn the model's raw text into exactly n labels, all from CATEGORIES.

    Bad content is never trusted: invalid JSON or wrong shape -> everything "Needs review";
    an unknown category, a missing id or a duplicated id -> only that line is "Needs review".
    """
    try:
        items = json.loads(raw)["categories"]
    except (TypeError, ValueError, KeyError):
        return [NEEDS_REVIEW] * n
    if not isinstance(items, list):
        return [NEEDS_REVIEW] * n

    answers: dict[int, str] = {}
    conflicted: set[int] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        i, category = item.get("id"), item.get("category")
        if type(i) is not int or not 0 <= i < n:
            continue
        if i in answers:
            conflicted.add(i)
        answers[i] = category

    return [
        answers[i] if i in answers and i not in conflicted and answers[i] in CATEGORIES
        else NEEDS_REVIEW
        for i in range(n)
    ]


# Categories that only make sense for money going out. "Other" and the transfer category
# are sign-neutral (a refund of unknown origin, money coming back from savings).
EXPENSE_CATEGORIES = ("Rent", "Groceries", "Eating out", "Transport", "Subscriptions", "Shopping")


def check_signs(labels, transactions) -> list[str]:
    """Downgrade labels that contradict the amount's sign to "Needs review".

    Income needs a positive amount; expense categories need a negative one. Zero is neutral.
    """
    checked = []
    for label, tx in zip(labels, transactions):
        if (label == INCOME and tx.amount < 0) or (label in EXPENSE_CATEGORIES and tx.amount > 0):
            label = NEEDS_REVIEW
        checked.append(label)
    return checked


def categorise(transactions) -> list[str]:
    """One category per transaction (same order). The model only returns labels, never amounts."""
    raw = llm.categorise_with_model(transactions, CATEGORIES)
    return check_signs(parse_model_answer(raw, len(transactions)), transactions)
