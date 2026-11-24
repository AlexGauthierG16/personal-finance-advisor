# Notes

## Parser (backend/parser.py)
- CSV format: header `date,description,amount`; date `YYYY-MM-DD`; amount a `.`-decimal in EUR; negative = expense, positive = income.
- Strict: bad date, non-decimal amount (e.g. `12,50`), missing column or empty description raises `ValueError` with the line number. Nothing is guessed.
- The parser does not know about transfers: the savings transfer is an ordinary negative row. Excluding own-account transfers from savings is `analysis.py`'s job.
- Sample data (synthetic): 25 rows each. Sept income 1100.00 / expenses 1227.18; Oct income 1100.00 / expenses 1266.67 (both include the savings transfer). 3 ambiguous rows per file (`PAYPAL *XYZ`, `POS ####`).

## Categories and analysis
- `CATEGORIES` in `backend/categorise.py` is the fixed list; anything else raises `ValueError`.
- `data/sample_sept_labels.csv` is hand-labelled ground truth for the later model evaluation (Sept only; 3 "Needs review"). Rows are matched to the statement by order, and date + description are checked.
- Totals are signed like the statement. `spend()` flips to positive spend; `variance = actual - budget` (positive = over budget). A category present on only one side counts as 0 on the other.
- Savings = income - expenses, excluding "Transfer to own account". "Needs review" amounts count as expenses (conservative) and are also reported separately via `needs_review_total`. Sept savings = -27.18.
- `check_totals` raises if the category totals do not sum to the statement total.
