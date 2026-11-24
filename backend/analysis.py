"""All totals, variances and savings, computed in code (Decimal only, never the model).

Sign convention: totals keep the statement's signs (expenses negative, income positive).
`spend` and `variance` work with spend as positive numbers; variance = actual - budget,
so positive means over budget.
"""
from decimal import Decimal

from backend.categorise import CATEGORIES, INCOME, NEEDS_REVIEW, TRANSFER

ZERO = Decimal("0")
NOT_SPENDING = (INCOME, TRANSFER, NEEDS_REVIEW)


def totals_by_category(transactions, categories) -> dict[str, Decimal]:
    """Signed total per category; `categories[i]` is the label of `transactions[i]`."""
    if len(categories) != len(transactions):
        raise ValueError(f"{len(categories)} labels for {len(transactions)} transactions")
    totals = {c: ZERO for c in CATEGORIES}
    for tx, cat in zip(transactions, categories):
        if cat not in totals:
            raise ValueError(f"unknown category {cat!r}")
        totals[cat] += tx.amount
    return totals


def check_totals(totals, transactions) -> None:
    """Raise if the category totals do not add up to the statement total."""
    statement = sum((t.amount for t in transactions), ZERO)
    by_category = sum(totals.values(), ZERO)
    if by_category != statement:
        raise ValueError(f"categories sum to {by_category}, statement sums to {statement}")


def needs_review_total(totals) -> Decimal:
    """Amount (signed) on lines the model was unsure about, reported separately."""
    return -totals.get(NEEDS_REVIEW, ZERO)


def spend(totals) -> dict[str, Decimal]:
    """Positive spend per category; excludes income, own-account transfers and Needs review."""
    return {c: -v for c, v in totals.items() if c not in NOT_SPENDING}


def variance(actual, budget) -> dict[str, Decimal]:
    """actual - budget per category (positive = over budget); missing side counts as 0."""
    return {c: actual.get(c, ZERO) - budget.get(c, ZERO) for c in {*actual, *budget}}


def savings(totals) -> Decimal:
    """Income minus expenses, excluding transfers to own account.

    Needs review lines count as expenses (conservative); see needs_review_total.
    """
    expenses = sum((-v for c, v in totals.items() if c not in (INCOME, TRANSFER)), ZERO)
    return totals.get(INCOME, ZERO) - expenses


def needs_review_items(transactions, categories) -> list:
    """The transactions labelled "Needs review", in statement order."""
    if len(categories) != len(transactions):
        raise ValueError(f"{len(categories)} labels for {len(transactions)} transactions")
    return [t for t, c in zip(transactions, categories) if c == NEEDS_REVIEW]


def transactions_in_category(transactions, categories, category) -> list:
    """The transactions labelled with `category`, in statement order."""
    if category not in CATEGORIES:
        raise ValueError(f"unknown category {category!r}")
    if len(categories) != len(transactions):
        raise ValueError(f"{len(categories)} labels for {len(transactions)} transactions")
    return [t for t, c in zip(transactions, categories) if c == category]
