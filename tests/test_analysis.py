from decimal import Decimal as D
from pathlib import Path

import pytest

from backend.analysis import (
    check_totals, needs_review_total, savings, spend, totals_by_category, variance,
)
from backend.categorise import CATEGORIES, read_labels
from backend.parser import Transaction, parse_csv

DATA = Path(__file__).resolve().parent.parent / "data"

# Hand-computed from sample_sept.csv + sample_sept_labels.csv (signed: expenses negative).
SEPT_TOTALS = {
    "Rent": D("-650.00"),
    "Groceries": D("-208.10"),      # Esselunga 126.70 + Carrefour 81.40
    "Eating out": D("-107.80"),     # Glovo 56.80 + bars 51.00
    "Transport": D("-43.40"),
    "Subscriptions": D("-10.99"),
    "Shopping": D("-68.99"),
    "Income": D("1100.00"),
    "Transfer to own account": D("-100.00"),
    "Other": D("0.00"),
    "Needs review": D("-37.90"),    # 15.00 + 14.00 + 8.90
}
SEPT_STATEMENT_SUM = D("-127.18")   # 1100.00 - 1227.18
SEPT_SAVINGS = D("-27.18")          # 1100.00 - (1227.18 - 100.00 transfer)


@pytest.fixture
def sept():
    txs = parse_csv(DATA / "sample_sept.csv")
    labels = read_labels(DATA / "sample_sept_labels.csv", txs)
    return txs, labels


def test_labels_file_shape(sept):
    txs, labels = sept
    assert len(labels) == len(txs) == 25
    assert labels.count("Needs review") == 3
    assert set(labels) <= set(CATEGORIES)


def test_totals_by_category(sept):
    totals = totals_by_category(*sept)
    assert totals == SEPT_TOTALS
    assert list(totals) == list(CATEGORIES)
    assert all(isinstance(v, D) for v in totals.values())
    assert sum(totals.values()) == SEPT_STATEMENT_SUM


def test_check_totals_ok_and_tampered(sept):
    txs, labels = sept
    totals = totals_by_category(txs, labels)
    check_totals(totals, txs)  # no error
    totals["Groceries"] += D("0.01")
    with pytest.raises(ValueError):
        check_totals(totals, txs)


def test_unknown_category_raises(sept):
    txs, labels = sept
    with pytest.raises(ValueError):
        totals_by_category(txs, labels[:-1] + ["Fun money"])


def test_label_count_mismatch_raises(sept):
    txs, labels = sept
    with pytest.raises(ValueError):
        totals_by_category(txs, labels[:-1])


def test_read_labels_mismatch_raises(sept, tmp_path):
    txs, _ = sept
    p = tmp_path / "bad.csv"
    p.write_text("date,description,category\n2025-09-01,SOMETHING ELSE,Income\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read_labels(p, txs)


def test_needs_review_reported_separately(sept):
    totals = totals_by_category(*sept)
    assert needs_review_total(totals) == D("37.90")


def test_savings_excludes_transfer(sept):
    txs, labels = sept
    totals = totals_by_category(txs, labels)
    assert savings(totals) == SEPT_SAVINGS
    totals["Transfer to own account"] = D("-999.00")
    assert savings(totals) == SEPT_SAVINGS


def test_spend_is_positive_and_excludes_non_spending(sept):
    s = spend(totals_by_category(*sept))
    assert s["Groceries"] == D("208.10")
    assert "Income" not in s and "Transfer to own account" not in s and "Needs review" not in s


def test_variance_positive_means_over_budget():
    actual = {"Groceries": D("208.10"), "Rent": D("650.00"), "Eating out": D("107.80"),
              "Shopping": D("68.99")}
    budget = {"Groceries": D("200.00"), "Rent": D("650.00"), "Eating out": D("120.00"),
              "Transport": D("40.00")}
    v = variance(actual, budget)
    assert v["Groceries"] == D("8.10")
    assert v["Rent"] == D("0.00")
    assert v["Eating out"] == D("-12.20")
    assert v["Shopping"] == D("68.99")      # spend with no budget
    assert v["Transport"] == D("-40.00")    # budget with no spend
    assert all(isinstance(x, D) for x in v.values())


def test_hand_made_transactions():
    txs = [Transaction(__import__("datetime").date(2025, 1, 1), "X", D("-0.10")),
           Transaction(__import__("datetime").date(2025, 1, 2), "Y", D("-0.20"))]
    totals = totals_by_category(txs, ["Other", "Other"])
    assert totals["Other"] == D("-0.30")  # exact, no float error
