# FastAPI app: serves frontend/ at / plus the API (/api/preview, /api/analyse, /api/review, /api/ask) and GET /health, on one port.
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import analysis, categorise, privacy
from backend.agent import answer_question, describe_steps, money
from backend.categorise import CATEGORIES, EXPENSE_CATEGORIES, INCOME, NEEDS_REVIEW
from backend.parser import parse_csv_text

MAX_CSV_CHARS = 1_000_000
MAX_ROWS = 300  # one model call per statement; no batching yet
MAX_QUESTION_CHARS = 1000
BUDGET_CATEGORIES = EXPENSE_CATEGORIES + ("Other",)

app = FastAPI()

# The current analysis, in memory. Single user, demo only: replaced by every /api/analyse,
# lost on restart, not safe for several users at once (see NOTES.md).
_STATE: dict = {}


class PreviewRequest(BaseModel):
    csv: str


class AnalyseRequest(BaseModel):
    csv: str
    budget: dict = {}


class ReviewRequest(BaseModel):
    id: int
    category: str


class AskRequest(BaseModel):
    question: str


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message


@app.exception_handler(ApiError)
def _api_error(request, exc: ApiError):
    return JSONResponse({"error": exc.message}, status_code=exc.status)


def _model_call(fn, *args):
    """Run a function that calls the model; turn failures into clear API errors."""
    try:
        return fn(*args)
    except RuntimeError as e:  # llm.py raises this when OPENAI_API_KEY / OPENAI_MODEL is missing
        raise ApiError(503, f"{e}. Restart the server after fixing it.") from e
    except Exception as e:
        raise ApiError(502, f"The model call failed ({type(e).__name__}). "
                            "Check the API key, the model name and the network, then try again.") from e


def _parse_budget(raw: dict) -> dict:
    budget = {}
    for category, value in raw.items():
        if category not in BUDGET_CATEGORIES:
            raise ApiError(400, f"budget: unknown category {category!r}")
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ApiError(400, f"budget for {category}: expected an amount")
        try:
            amount = Decimal(str(value).strip())
        except InvalidOperation:
            raise ApiError(400, f"budget for {category}: {value!r} is not a number") from None
        if not amount.is_finite() or amount < 0:
            raise ApiError(400, f"budget for {category}: must be a number of 0 or more")
        budget[category] = amount
    return {c: budget.get(c, Decimal("0.00")) for c in BUDGET_CATEGORIES}


def _require_state():
    if not _STATE:
        raise ApiError(409, "Upload and analyse a statement first.")
    return _STATE


def _analysis_payload() -> dict:
    s = _STATE
    totals = analysis.totals_by_category(s["transactions"], s["labels"])
    analysis.check_totals(totals, s["transactions"])
    spend = analysis.spend(totals)
    variance = analysis.variance(spend, s["budget"])
    items = analysis.needs_review_items(s["transactions"], s["labels"])
    ids = [i for i, label in enumerate(s["labels"]) if label == NEEDS_REVIEW]
    return {
        "rows": [
            {"category": c, "actual": money(spend[c]), "budget": money(s["budget"][c]),
             "variance": money(variance[c]), "over_budget": variance[c] > 0}
            for c in BUDGET_CATEGORIES
        ],
        "income": money(totals[INCOME]),
        "savings": money(analysis.savings(totals)),
        "transfers": money(-totals[categorise.TRANSFER]),
        "needs_review": {
            "items": [{"id": i, "date": t.date.isoformat(), "description": t.description,
                       "amount": money(t.amount)} for i, t in zip(ids, items)],
            "total": money(sum((t.amount for t in items), Decimal("0"))),
            "spend": money(analysis.needs_review_total(totals)),
        },
        "assignable_categories": [c for c in CATEGORIES if c != NEEDS_REVIEW],
        "transaction_count": len(s["transactions"]),
    }


def _read_statement(csv_text: str) -> list:
    """Parse an uploaded statement with the size and row limits; raises ApiError(400)."""
    if len(csv_text) > MAX_CSV_CHARS:
        raise ApiError(400, "The file is too large (limit 1 MB).")
    try:
        transactions = parse_csv_text(csv_text)
    except ValueError as e:
        raise ApiError(400, f"Could not read the statement: {e}") from e
    if not transactions:
        raise ApiError(400, "The statement has no transactions.")
    if len(transactions) > MAX_ROWS:
        raise ApiError(400, f"Too many transactions ({len(transactions)}); the limit is {MAX_ROWS}.")
    return transactions


@app.post("/api/preview")
def api_preview(req: PreviewRequest):
    """What would be sent to the AI for each row. No model call, nothing stored."""
    rows = []
    for t in _read_statement(req.csv):
        sent = privacy.anonymise(t.description)
        rows.append({"original": t.description, "sent": sent, "masked": sent != t.description})
    return {"rows": rows, "masked_count": sum(r["masked"] for r in rows)}


@app.post("/api/analyse")
def api_analyse(req: AnalyseRequest):
    transactions = _read_statement(req.csv)
    budget = _parse_budget(req.budget)
    labels = _model_call(categorise.categorise, transactions)
    _STATE.clear()
    _STATE.update(transactions=transactions, labels=labels, budget=budget)
    return _analysis_payload()


@app.post("/api/review")
def api_review(req: ReviewRequest):
    s = _require_state()
    if not 0 <= req.id < len(s["transactions"]):
        raise ApiError(400, "No such transaction.")
    if s["labels"][req.id] != NEEDS_REVIEW:
        raise ApiError(400, "Only transactions marked 'Needs review' can be reassigned.")
    if req.category not in CATEGORIES or req.category == NEEDS_REVIEW:
        raise ApiError(400, f"Choose one of: {', '.join(c for c in CATEGORIES if c != NEEDS_REVIEW)}.")
    tx = s["transactions"][req.id]
    if categorise.check_signs([req.category], [tx]) != [req.category]:
        direction = "money in" if tx.amount > 0 else "money out"
        raise ApiError(400, f"{req.category!r} does not fit a transaction of {money(tx.amount)} "
                            f"({direction}). Pick another category, for example 'Other'.")
    s["labels"][req.id] = req.category
    return _analysis_payload()


@app.post("/api/ask")
def api_ask(req: AskRequest):
    s = _require_state()
    question = req.question.strip()
    if not question or len(question) > MAX_QUESTION_CHARS:
        raise ApiError(400, f"Write a question of 1 to {MAX_QUESTION_CHARS} characters.")
    result = _model_call(answer_question, question, s["transactions"], s["labels"], s["budget"])
    return {
        "answer": result.answer,
        "warning": bool(result.unverified_numbers),
        "unverified_numbers": result.unverified_numbers,
        "finished": result.finished,
        "tools_used": [c["name"] for c in result.tool_calls],
        "steps": describe_steps(result.tool_calls),
        "numbers_checked": result.numbers_checked,
    }


@app.get("/health")
def health():
    return {"ok": True}


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn

    load_dotenv()
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
