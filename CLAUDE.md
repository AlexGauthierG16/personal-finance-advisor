# Spend Analyzer

## What this is
- We help students understand their spending: the model categorises bank transactions, Python computes and verifies every number.
- User: a student with one or more bank statements (CSV) who wants to compare monthly spending with a budget, without manual entry.
- Done by 26 Nov: import statements, confirm a monthly budget, categorise transactions, show verified totals and budget variances, flag uncertain items for review.

## How to run it
- Create venv: `python3 -m venv .venv`
- Activate: `source .venv/bin/activate` (macOS) or `.venv\Scripts\Activate.ps1` (Windows)
- Install: `pip install -r requirements.txt`
- Start: `uvicorn backend.main:app --reload`; page at http://127.0.0.1:8000, `/health` returns `{"ok": true}`
- Tests: `pytest` from the repo root

## Where things live
- `backend/main.py`: entry point; serves the page and the API on one port.
- `backend/llm.py`: the only file that calls the model (categorising and tool calling).
- `backend/parser.py`: reads statements into transactions.
- `backend/categorise.py`: gets categories from llm.py and validates the structured output.
- `backend/analysis.py`: all totals, variances and savings, in code.
- `backend/agent.py`: runs the tool-calling loop (max 5 steps) and executes the tools that wrap analysis.py; the API call itself is in llm.py.
- `frontend/`: plain HTML, CSS and JavaScript, no framework.
- `data/`: synthetic sample statements only.
- `tests/`: one test per feature, with fixtures whose expected totals are known.
- `NOTES.md`: decisions, limitations, ideas for later.

## How to behave
1. State assumptions before coding. Ask when an ambiguity affects correctness.
2. Never guess a column's meaning, a date format, a currency or a transaction's sign. Ask.
3. The model only categorises. Every number shown to the user is computed in Python. Money is integer cents or Decimal, never float.
4. Use the fixed category list and validated structured output. Uncertain lines are labelled "Needs review" and their amounts are shown separately.
5. Variance = actual − budget (positive means over budget). Savings = income − expenses, excluding transfers between the user's own accounts.
6. Write a failing test first, then make it pass. Check totals against fixtures with known results.
7. Make the smallest change that works; touch only what the task needs.
8. When done, say how you verified it. Record decisions in NOTES.md.

## What not to do
- No new frameworks, no database, no features nobody asked for.
- Never edit a test or an expected result to make it pass. If a test seems wrong, say so and ask.
- Never call the model outside `backend/llm.py`.
- Never read, print or commit `.env`. Never commit real bank statements.
- Never invent transactions, amounts, dates or balances.
- Never combine currencies without an agreed conversion rule.

## Mistakes we have seen
- Plain `pytest` could not import `backend`; `pytest.ini` fixes the path. Always run tests from the repo root.
- `sed -i` without '' fails on macOS; use Python or the edit tool to change files.