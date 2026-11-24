from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from backend.parser import parse_csv

DATA = Path(__file__).resolve().parent.parent / "data"

# Totals computed by hand from the CSV rows (expenses include the savings transfer).
SEPT = {"rows": 25, "income": Decimal("1100.00"), "expenses": Decimal("-1227.18")}
OCT = {"rows": 25, "income": Decimal("1100.00"), "expenses": Decimal("-1266.67")}


@pytest.mark.parametrize("name,expected", [("sample_sept.csv", SEPT), ("sample_oct.csv", OCT)])
def test_sample_totals(name, expected):
    txs = parse_csv(DATA / name)
    assert len(txs) == expected["rows"]
    assert sum((t.amount for t in txs if t.amount > 0), Decimal("0")) == expected["income"]
    assert sum((t.amount for t in txs if t.amount < 0), Decimal("0")) == expected["expenses"]


def test_types():
    first = parse_csv(DATA / "sample_sept.csv")[0]
    assert first.date == date(2025, 9, 1)
    assert isinstance(first.amount, Decimal)
    assert first.description == "BONIFICO STIPENDIO CAFFE NAVIGLI"


def write(tmp_path, body):
    p = tmp_path / "x.csv"
    p.write_text(body, encoding="utf-8")
    return p


@pytest.mark.parametrize("body", [
    "date,description,amount\n01/09/2025,SHOP,-1.00\n",   # wrong date format
    'date,description,amount\n2025-09-01,SHOP,"12,50"\n',  # comma decimal
    "date,description\n2025-09-01,SHOP\n",                 # missing column
    "date,description,amount\n2025-09-01,,-1.00\n",        # blank description
])
def test_bad_input_raises(tmp_path, body):
    with pytest.raises(ValueError):
        parse_csv(write(tmp_path, body))


# --- parse_csv_text (used by the upload endpoint) ---

from backend.parser import parse_csv_text  # noqa: E402


def test_parse_csv_text_matches_parse_csv():
    text = (DATA / "sample_sept.csv").read_text(encoding="utf-8")
    assert parse_csv_text(text) == parse_csv(DATA / "sample_sept.csv")


def test_parse_csv_text_accepts_bom():
    txs = parse_csv_text("﻿date,description,amount\n2025-09-01,SHOP,-1.50\n")
    assert [(t.description, t.amount) for t in txs] == [("SHOP", Decimal("-1.50"))]


def test_parse_csv_text_bad_input_raises():
    with pytest.raises(ValueError):
        parse_csv_text("date,description,amount\n01/09/2025,SHOP,-1.00\n")
    with pytest.raises(ValueError):
        parse_csv_text("")
