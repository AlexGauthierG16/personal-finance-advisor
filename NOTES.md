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

## Model categorisation
- `llm.categorise_with_model` is the only code that imports `openai` and reads `OPENAI_API_KEY` / `OPENAI_MODEL` (via python-dotenv). It returns raw text; `categorise.parse_model_answer` validates it.
- Wire format: sends `{id, description, amount}` per transaction (id = list index; dates are not sent); expects `{"categories": [{"id": 0, "category": "Rent"}, ...]}`.
- Bad content is downgraded, never trusted: invalid JSON or wrong shape -> all "Needs review"; unknown category, missing id, duplicated id -> that line only. The model never returns amounts, so amounts cannot change.
- Infrastructure problems (missing env var, network/API error) raise instead of becoming "Needs review", so config errors are not hidden.
- Privacy: descriptions and amounts go to OpenAI. Fine for synthetic samples; decide consciously before using real statements.
- Limitations / ideas: one API call per statement (no batching for long statements); no live evaluation against `sample_sept_labels.csv` yet.

## Sign check (categorise.check_signs)
- After validation, a negative amount labelled "Income", or a positive amount labelled Rent/Groceries/Eating out/Transport/Subscriptions/Shopping, becomes "Needs review".
- "Other" and "Transfer to own account" are sign-neutral (money back from savings, unknown refunds); a zero amount is neutral.
- Side effect: a genuine refund labelled e.g. "Groceries" lands in "Needs review" until we decide how to treat refunds.

## Agent (backend/agent.py)
- `answer_question(question, transactions, categories, budget)` -> `AgentResult(answer, tool_calls, finished)`. `categories` is the per-transaction label list; `budget` is `{category: Decimal}`.
- Tools: totals_by_category, variance, savings, needs_review_items, list_transactions(category). They wrap `analysis.py` (two new pure functions added there). Results are JSON with money as strings, never floats; zero is shown as "0.00".
- One step = one model call, max 5 (`MAX_STEPS`). If the model is still asking for tools after step 5, the result is a fixed message with `finished=False`; nothing is invented.
- Tool problems (unknown tool, bad arguments, unknown category, no budget set, exception in a tool) are returned to the model as `{"error": ...}` and never crash the loop. Infrastructure errors from llm.py (missing key, network) propagate.
- `variance` and `savings` results include `needs_review_spend` (positive) so the model can mention uncertain amounts. `needs_review_items.total` is the signed sum of the items (negative = money out).
- Idea for later (not built): check that every number in the final answer appears in some tool result, and flag it if not. Today this rule is enforced by the system prompt only.
- Not yet run against the real model; tests use a scripted fake.

## Number check (agent.unverified_numbers)
- After the model's final answer, every number in it must appear in a successful tool result from the same run. Otherwise `AgentResult.answer` starts with a "Warning: these numbers could not be verified ..." line (followed by the original text) and `unverified_numbers` lists them as written.
- Same value in another format is accepted: 208.10 = 208,10 = -208.10 = 1.234,56 = 1,234.56 (sign ignored; "1,234" may be 1234 or 1.234). Dates and numbers inside descriptions count, because they appear in tool results.
- Error results are not a source of truth (they can echo text the model supplied). "1. " list markers at line start are ignored. The fixed step-limit message is not checked.
- Numbers that appear in the user's own question are also accepted (e.g. "is 200 too much?" -> "200"). A count the model works out itself ("3 items") is still flagged unless a tool result contains it. Caveat: a number echoed from the question is trusted, even if the model attaches a wrong claim to it.
- This catches invented figures; it does not prove the number is attached to the right label (e.g. 8.10 described as the wrong category).

## Web interface (backend/main.py, frontend/)
- Endpoints: `POST /api/analyse` (CSV text + budget), `POST /api/review` (assign a category to a "Needs review" line), `POST /api/ask` (agent question), plus `/health`. Errors are `{"error": "..."}`: 400 bad input, 409 nothing analysed yet, 503 missing `OPENAI_API_KEY`/`OPENAI_MODEL`, 502 any other model failure (generic message; exception text is not echoed).
- **Limit: the analysis lives in memory** (`main._STATE`). Single user, demo only: each upload replaces it, it is lost on restart, and two people using the server at once would overwrite each other. Needs a session id or storage before any real use.
- The CSV is posted as JSON text (`file.text()` in the browser) instead of multipart, to avoid adding `python-multipart`. `parser.parse_csv_text` does the parsing (also strips a BOM); `parse_csv(path)` wraps it.
- Limits: 1 MB, 300 transactions (one model call per statement, no batching yet).
- Budget: the 7 spending categories, non-negative decimals sent as text; a missing category counts as 0.00, so its whole spend shows as over budget.
- Manual review uses the same sign rule as the model's labels (no "Income" for money out, no expense category for money in); the message suggests "Other". Only "Needs review" lines can be reassigned. A genuine refund must go to "Other" for now.
- The page does no arithmetic: every figure, including `over_budget`, comes from the API. Statement text is inserted with `textContent` only.
- Verified with TestClient tests and fake models, and by running the real server with a fake model; not yet tried in a browser or against the real model.

## Student focus
- Page title "Spend Analyzer, for students"; the privacy note stays under the upload box.
- Budget defaults (EUR/month, my rough estimates for a student in Milan, not sourced; editable): Rent 600, Groceries 200, Eating out 100, Transport 30, Subscriptions 20, Shopping 50, Other 40. Worth checking against real numbers from the team.
- Agent prompt: student on a tight budget, plain language, at most 5 sentences, concrete suggestions from their own numbers only, no generic or investment advice. The 5-sentence limit is a prompt instruction, not enforced in code.
- Three clickable example questions fill the question box.
