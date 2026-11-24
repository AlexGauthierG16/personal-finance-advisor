"""Assigns a category to each transaction (model calls will come later, via llm.py)."""

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
