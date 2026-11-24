"""Reads bank statements (CSV) into transactions."""
import csv
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

COLUMNS = ("date", "description", "amount")


@dataclass(frozen=True)
class Transaction:
    date: date
    description: str
    amount: Decimal  # EUR; negative = expense, positive = income


def parse_csv(path) -> list[Transaction]:
    """Parse a statement file; see parse_csv_text for the format."""
    with Path(path).open(newline="", encoding="utf-8") as f:
        return parse_csv_text(f.read())


def parse_csv_text(text: str) -> list[Transaction]:
    """Parse statement text with columns date (YYYY-MM-DD), description, amount.

    Strict: anything unexpected raises ValueError instead of being guessed.
    """
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff"), newline=""))
    missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
    if missing:
        raise ValueError(f"missing column(s): {', '.join(missing)}")
    txs = []
    for n, row in enumerate(reader, start=2):  # line 1 is the header
        try:
            d = date.fromisoformat((row["date"] or "").strip())
            amount = Decimal((row["amount"] or "").strip())
        except (ValueError, InvalidOperation) as e:
            raise ValueError(f"line {n}: bad date or amount ({e})") from e
        if not amount.is_finite():
            raise ValueError(f"line {n}: amount is not a finite number")
        desc = (row["description"] or "").strip()
        if not desc:
            raise ValueError(f"line {n}: empty description")
        txs.append(Transaction(d, desc, amount))
    return txs
