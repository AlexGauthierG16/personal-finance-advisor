import json
from decimal import Decimal as D
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import llm, main
from backend.categorise import CATEGORIES, read_labels
from backend.parser import parse_csv

DATA = Path(__file__).resolve().parent.parent / "data"
SEPT_CSV = (DATA / "sample_sept.csv").read_text(encoding="utf-8")
BUDGET = {"Groceries": "200.00", "Rent": "650.00", "Eating out": "120.00"}

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def clean_state():
    main._STATE.clear()
    yield
    main._STATE.clear()


@pytest.fixture
def labels():
    txs = parse_csv(DATA / "sample_sept.csv")
    return read_labels(DATA / "sample_sept_labels.csv", txs)


def model_answer(labels):
    return json.dumps({"categories": [{"id": i, "category": c} for i, c in enumerate(labels)]})


def fake_categoriser(monkeypatch, raw):
    monkeypatch.setattr(llm, "categorise_with_model", lambda txs, cats: raw)


def fake_agent(monkeypatch, replies):
    calls = []

    def fake(messages, tools):
        calls.append(json.loads(json.dumps(messages)))
        return replies[len(calls) - 1]
    monkeypatch.setattr(llm, "chat_with_tools", fake)
    return calls


def analyse(csv=SEPT_CSV, budget=BUDGET):
    return client.post("/api/analyse", json={"csv": csv, "budget": budget})


@pytest.fixture
def analysed(monkeypatch, labels):
    fake_categoriser(monkeypatch, model_answer(labels))
    r = analyse()
    assert r.status_code == 200
    return r.json()


def row(payload, category):
    return next(r for r in payload["rows"] if r["category"] == category)


def tool_call(name, args="{}"):
    return {"content": None, "tool_calls": [{"id": "c1", "name": name, "arguments": args}]}


def text(t):
    return {"content": t, "tool_calls": []}


def no_key(monkeypatch):
    monkeypatch.setattr(llm, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)


# ---------------------------------------------------------------- /api/analyse

def test_analyse_numbers(analysed):
    p = analysed
    assert p["transaction_count"] == 25
    g = row(p, "Groceries")
    assert (g["actual"], g["budget"], g["variance"], g["over_budget"]) == ("208.10", "200.00", "8.10", True)
    e = row(p, "Eating out")
    assert (e["actual"], e["variance"], e["over_budget"]) == ("107.80", "-12.20", False)
    r = row(p, "Rent")
    assert (r["variance"], r["over_budget"]) == ("0.00", False)
    t = row(p, "Transport")  # no budget given -> 0.00, spend shows as over
    assert (t["actual"], t["budget"], t["variance"]) == ("43.40", "0.00", "43.40")
    assert p["income"] == "1100.00"
    assert p["savings"] == "-27.18"
    assert p["transfers"] == "100.00"
    assert {r["category"] for r in p["rows"]} == {"Rent", "Groceries", "Eating out", "Transport",
                                                  "Subscriptions", "Shopping", "Other"}


def test_analyse_needs_review(analysed):
    nr = analysed["needs_review"]
    assert nr["total"] == "-37.90"
    assert nr["spend"] == "37.90"
    assert [(i["id"], i["description"], i["amount"]) for i in nr["items"]] == [
        (9, "PAYPAL *XYZ", "-15.00"), (13, "POS 4421", "-14.00"), (21, "POS 7730", "-8.90")]
    assert "Needs review" not in analysed["assignable_categories"]
    assert set(analysed["assignable_categories"]) == set(CATEGORIES) - {"Needs review"}


def test_analyse_broken_model_answer_is_all_needs_review(monkeypatch):
    fake_categoriser(monkeypatch, "not json {")
    r = analyse()
    assert r.status_code == 200
    assert r.json()["needs_review"]["total"] == "-127.18"
    assert len(r.json()["needs_review"]["items"]) == 25


def test_analyse_replaces_previous_state(monkeypatch, labels):
    fake_categoriser(monkeypatch, model_answer(labels))
    analyse()
    csv2 = "date,description,amount\n2025-10-01,SALARY,500.00\n2025-10-02,MYSTERY,-5.00\n"
    fake_categoriser(monkeypatch, json.dumps({"categories": [{"id": 0, "category": "Income"}]}))
    r = analyse(csv2, {})
    assert r.status_code == 200
    assert r.json()["transaction_count"] == 2
    assert r.json()["needs_review"]["total"] == "-5.00"  # missing id 1 -> Needs review


def test_analyse_bad_csv(monkeypatch):
    fake_categoriser(monkeypatch, "{}")
    r = analyse("date,description,amount\n01/09/2025,SHOP,-1.00\n")
    assert r.status_code == 400
    assert "line 2" in r.json()["error"]


@pytest.mark.parametrize("csv", ["date,description,amount\n", "", "date,description\n2025-09-01,X\n"])
def test_analyse_empty_or_malformed_csv(csv):
    assert analyse(csv).status_code == 400


def test_analyse_too_many_rows():
    rows = "".join(f"2025-09-01,SHOP {i},-1.00\n" for i in range(301))
    r = analyse("date,description,amount\n" + rows)
    assert r.status_code == 400
    assert "300" in r.json()["error"]


def test_analyse_too_large():
    r = analyse("date,description,amount\n" + "x" * 1_000_001)
    assert r.status_code == 400


@pytest.mark.parametrize("budget", [
    {"Rent": "-1"}, {"Rent": "abc"}, {"Rent": "NaN"}, {"Rent": None}, {"Fun money": "10"},
    {"Income": "10"}, {"Rent": True},
])
def test_analyse_bad_budget(monkeypatch, budget):
    fake_categoriser(monkeypatch, "{}")
    r = analyse(budget=budget)
    assert r.status_code == 400
    assert "error" in r.json()


def test_analyse_missing_key_is_a_clear_error(monkeypatch):
    no_key(monkeypatch)
    r = analyse()
    assert r.status_code == 503
    assert "OPENAI_API_KEY" in r.json()["error"]
    assert main._STATE == {}


def test_analyse_other_model_failure(monkeypatch):
    def boom(txs, cats):
        raise ConnectionError("secret-detail")
    monkeypatch.setattr(llm, "categorise_with_model", boom)
    r = analyse()
    assert r.status_code == 502
    assert "secret-detail" not in r.json()["error"]


# ---------------------------------------------------------------- /api/review

def review(id, category):
    return client.post("/api/review", json={"id": id, "category": category})


def test_review_recomputes(analysed):
    r = review(9, "Shopping")  # PAYPAL *XYZ, -15.00
    assert r.status_code == 200
    p = r.json()
    assert row(p, "Shopping")["actual"] == "83.99"     # 68.99 + 15.00
    assert p["needs_review"]["total"] == "-22.90"
    assert p["needs_review"]["spend"] == "22.90"
    assert [i["id"] for i in p["needs_review"]["items"]] == [13, 21]
    assert p["savings"] == "-27.18"
    assert row(p, "Shopping")["variance"] == "83.99"   # no Shopping budget


def test_review_all_three_leaves_nothing_to_review(analysed):
    review(9, "Shopping")
    review(13, "Other")
    p = review(21, "Eating out").json()
    assert p["needs_review"]["items"] == []
    assert p["needs_review"]["total"] == "0.00"
    assert row(p, "Eating out")["actual"] == "116.70"  # 107.80 + 8.90


@pytest.mark.parametrize("id,category", [
    (99, "Shopping"), (-1, "Shopping"), (0, "Shopping"),   # out of range / already labelled
    (9, "Fun money"), (9, "Needs review"),
    (9, "Income"),                                          # negative amount can't be Income
])
def test_review_rejected(analysed, id, category):
    r = review(id, category)
    assert r.status_code == 400
    assert "error" in r.json()
    # state unchanged: the line is still waiting for review
    assert main._STATE["labels"][9] == "Needs review"


def test_review_without_analysis():
    assert review(0, "Shopping").status_code == 409


# ---------------------------------------------------------------- /api/ask

def ask(question="How are my savings?"):
    return client.post("/api/ask", json={"question": question})


def test_ask_verified_answer(monkeypatch, analysed):
    calls = fake_agent(monkeypatch, [tool_call("savings"), text("Your savings are -27.18 EUR.")])
    r = ask()
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "Your savings are -27.18 EUR."
    assert body["warning"] is False
    assert body["unverified_numbers"] == []
    assert body["finished"] is True
    assert body["tools_used"] == ["savings"]
    assert len(calls) == 2


def test_ask_invented_number_gets_warning(monkeypatch, analysed):
    fake_agent(monkeypatch, [tool_call("savings"), text("Savings are -27.18 but save 150.00 more.")])
    body = ask().json()
    assert body["warning"] is True
    assert body["unverified_numbers"] == ["150.00"]
    assert body["answer"].startswith("Warning")
    assert "Savings are -27.18 but save 150.00 more." in body["answer"]


def test_ask_accepts_numbers_from_the_question(monkeypatch, analysed):
    fake_agent(monkeypatch, [tool_call("variance"), text("Groceries are 8.10 over your 200.")])
    body = ask("Is 200 enough for groceries?").json()
    assert body["warning"] is False


def test_ask_uses_reviewed_labels(monkeypatch, analysed):
    review(9, "Shopping")
    calls = fake_agent(monkeypatch, [tool_call("totals_by_category"), text("Shopping is -83.99.")])
    body = ask().json()
    assert body["warning"] is False
    tool_msg = [m for m in calls[1] if m["role"] == "tool"][0]
    assert json.loads(tool_msg["content"])["totals"]["Shopping"] == "-83.99"


def test_ask_step_limit_reported(monkeypatch, analysed):
    fake_agent(monkeypatch, [tool_call("savings")] * 5)
    body = ask().json()
    assert body["finished"] is False
    assert "5 steps" in body["answer"]


def test_ask_without_analysis():
    assert ask().status_code == 409


@pytest.mark.parametrize("question", ["", "   ", "x" * 1001])
def test_ask_bad_question(analysed, question):
    r = ask(question)
    assert r.status_code == 400
    assert "error" in r.json()


def test_ask_missing_key(monkeypatch, analysed):
    no_key(monkeypatch)
    r = ask()
    assert r.status_code == 503
    assert "OPENAI_API_KEY" in r.json()["error"]


def test_ask_other_model_failure(monkeypatch, analysed):
    def boom(messages, tools):
        raise TimeoutError("secret-detail")
    monkeypatch.setattr(llm, "chat_with_tools", boom)
    r = ask()
    assert r.status_code == 502
    assert "secret-detail" not in r.json()["error"]


# ---------------------------------------------------------------- static files

def test_page_and_assets_are_served():
    assert client.get("/health").json() == {"ok": True}
    page = client.get("/")
    assert page.status_code == 200 and "<html" in page.text
    assert client.get("/app.js").status_code == 200
    assert client.get("/style.css").status_code == 200


# ---------------------------------------------------------------- /api/preview and privacy

PRIVATE_CSV = (DATA / "sample_private.csv").read_text(encoding="utf-8")


def preview(csv=SEPT_CSV):
    return client.post("/api/preview", json={"csv": csv})


def forbid_model(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("the model must not be called")
    monkeypatch.setattr(llm, "categorise_with_model", boom)
    monkeypatch.setattr(llm, "chat_with_tools", boom)


def test_preview_shows_original_and_what_is_sent(monkeypatch):
    forbid_model(monkeypatch)
    r = preview(PRIVATE_CSV)
    assert r.status_code == 200
    body = r.json()
    assert len(body["rows"]) == 16
    assert body["masked_count"] == 10
    second = body["rows"][1]
    assert second == {"original": "BONIFICO DA ROSSI MARIO CAUSALE PAGAMENTO LEZIONI",
                      "sent": "BONIFICO DA [NAME] CAUSALE PAGAMENTO LEZIONI", "masked": True}
    first = body["rows"][0]
    assert first == {"original": "ESSELUNGA MILANO LORENTEGGIO",
                     "sent": "ESSELUNGA MILANO LORENTEGGIO", "masked": False}
    assert all("amount" not in row and "date" not in row for row in body["rows"])


def test_preview_of_a_clean_statement_masks_nothing(monkeypatch):
    forbid_model(monkeypatch)
    body = preview().json()
    assert body["masked_count"] == 0
    assert len(body["rows"]) == 25


def test_preview_creates_no_state(monkeypatch):
    forbid_model(monkeypatch)
    preview(PRIVATE_CSV)
    assert main._STATE == {}


@pytest.mark.parametrize("csv", ["date,description,amount\n01/09/2025,SHOP,-1.00\n",
                                 "date,description,amount\n", "", "x" * 1_000_001])
def test_preview_rejects_bad_statements(csv):
    r = preview(csv)
    assert r.status_code == 400
    assert "error" in r.json()


def test_preview_too_many_rows():
    rows = "".join(f"2025-09-01,SHOP {i},-1.00\n" for i in range(301))
    assert preview("date,description,amount\n" + rows).status_code == 400


def test_analyse_sends_only_anonymised_descriptions(monkeypatch):
    sent = []

    def capture(descriptions, categories):
        sent.append(descriptions)
        return "not json"
    monkeypatch.setattr(llm, "categorise_with_model", capture)
    r = analyse(PRIVATE_CSV, {})
    assert r.status_code == 200
    assert sent[0][1] == "BONIFICO DA [NAME] CAUSALE PAGAMENTO LEZIONI"
    assert all(type(d) is str for d in sent[0])
    joined = " ".join(sent[0]).upper()
    for secret in ["ROSSI", "BIANCHI", "VERDI", "IT60X0542811101000000123456", "5555555555554444",
                   "BNCNNA90A41F205Q", "EXAMPLE.COM"]:
        assert secret not in joined
    # the user's own view keeps the original text
    items = r.json()["needs_review"]["items"]
    assert items[1]["description"] == "BONIFICO DA ROSSI MARIO CAUSALE PAGAMENTO LEZIONI"


# ---------------------------------------------------------------- the agent's steps

def test_ask_returns_the_steps_in_order(monkeypatch, analysed):
    fake_agent(monkeypatch, [tool_call("savings"),
                             tool_call("list_transactions", '{"category": "Eating out"}'),
                             text("Savings are -27.18; eating out was -107.80.")])
    body = ask().json()
    assert body["steps"] == [
        {"step": 1, "tool": "savings", "arguments": {}, "label": "savings",
         "summary": "savings -27.18, with 37.90 in Needs review counted as spending", "ok": True},
        {"step": 2, "tool": "list_transactions", "arguments": {"category": "Eating out"},
         "label": "list_transactions(Eating out)", "summary": "7 transactions, total -107.80", "ok": True},
    ]
    assert body["tools_used"] == ["savings", "list_transactions"]
    assert body["numbers_checked"] == 2
    assert body["warning"] is False and body["finished"] is True


def test_ask_unknown_tool_is_a_failed_step_not_an_api_error(monkeypatch, analysed):
    fake_agent(monkeypatch, [tool_call("delete_everything"), text("I cannot do that.")])
    r = ask()
    assert r.status_code == 200
    (step,) = r.json()["steps"]
    assert step["ok"] is False and step["tool"] == "delete_everything"
    assert r.json()["numbers_checked"] == 0


def test_ask_invented_number_is_counted_and_flagged(monkeypatch, analysed):
    fake_agent(monkeypatch, [tool_call("savings"), text("Savings -27.18, save 150.00 more.")])
    body = ask().json()
    assert body["warning"] is True
    assert body["numbers_checked"] == 2
    assert body["unverified_numbers"] == ["150.00"]


def test_ask_without_tools_has_no_steps(monkeypatch, analysed):
    fake_agent(monkeypatch, [text("I can only look at your statement.")])
    body = ask().json()
    assert body["steps"] == [] and body["tools_used"] == []


def test_ask_step_limit_reports_unfinished_with_its_steps(monkeypatch, analysed):
    fake_agent(monkeypatch, [tool_call("savings")] * 5)
    body = ask().json()
    assert body["finished"] is False
    assert [s["step"] for s in body["steps"]] == [1, 2, 3, 4, 5]


def test_ask_quoting_the_budget_is_verified(monkeypatch, analysed):
    fake_agent(monkeypatch, [tool_call("variance"),
                             text("Eating out: 107.80 spent against a 120.00 budget, 12.20 under.")])
    body = ask().json()
    assert body["warning"] is False
    assert body["unverified_numbers"] == []
    assert body["numbers_checked"] == 3
