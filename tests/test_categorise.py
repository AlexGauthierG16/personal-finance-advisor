import json
from decimal import Decimal as D
from pathlib import Path

import pytest

from backend import llm
from backend.analysis import check_totals, totals_by_category
from backend.categorise import CATEGORIES, NEEDS_REVIEW, categorise, read_labels
from backend.parser import parse_csv

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture
def sept():
    txs = parse_csv(DATA / "sample_sept.csv")
    labels = read_labels(DATA / "sample_sept_labels.csv", txs)
    return txs, labels


def answer(labels):
    return json.dumps({"categories": [{"id": i, "category": c} for i, c in enumerate(labels)]})


def fake_model(monkeypatch, raw, seen=None):
    def fake(transactions, categories):
        if seen is not None:
            seen.append((transactions, categories))
        return raw
    monkeypatch.setattr(llm, "categorise_with_model", fake)


def test_valid_answer(monkeypatch, sept):
    txs, labels = sept
    fake_model(monkeypatch, answer(labels))
    result = categorise(txs)
    assert result == labels
    totals = totals_by_category(txs, result)
    check_totals(totals, txs)
    assert totals["Groceries"] == D("-208.10")
    assert totals["Needs review"] == D("-37.90")


def test_invented_category(monkeypatch, sept):
    txs, labels = sept
    bad = list(labels)
    bad[2] = "Fun money"  # was Groceries
    fake_model(monkeypatch, answer(bad))
    result = categorise(txs)
    assert result[2] == NEEDS_REVIEW
    assert result[:2] + result[3:] == labels[:2] + labels[3:]


def test_missing_transaction(monkeypatch, sept):
    txs, labels = sept
    items = [{"id": i, "category": c} for i, c in enumerate(labels) if i != 4]
    fake_model(monkeypatch, json.dumps({"categories": items}))
    result = categorise(txs)
    assert len(result) == len(txs)
    assert result[4] == NEEDS_REVIEW
    assert result[:4] + result[5:] == labels[:4] + labels[5:]


def test_broken_json(monkeypatch, sept):
    txs, _ = sept
    fake_model(monkeypatch, "not json {")
    assert categorise(txs) == [NEEDS_REVIEW] * len(txs)


@pytest.mark.parametrize("raw", ['[1, 2]', '{"foo": []}', '{"categories": "Rent"}', 'null', '"x"'])
def test_wrong_shape_is_all_needs_review(monkeypatch, sept, raw):
    txs, _ = sept
    fake_model(monkeypatch, raw)
    assert categorise(txs) == [NEEDS_REVIEW] * len(txs)


def test_duplicate_id_goes_to_needs_review(monkeypatch, sept):
    txs, labels = sept
    items = [{"id": i, "category": c} for i, c in enumerate(labels)]
    items.append({"id": 0, "category": "Shopping"})  # conflicting second answer for id 0
    fake_model(monkeypatch, json.dumps({"categories": items}))
    result = categorise(txs)
    assert result[0] == NEEDS_REVIEW
    assert result[1:] == labels[1:]


def test_out_of_range_and_malformed_items_ignored(monkeypatch, sept):
    txs, labels = sept
    items = [{"id": i, "category": c} for i, c in enumerate(labels)]
    items += [{"id": 999, "category": "Rent"}, {"id": "x", "category": "Rent"}, "junk", {"id": True, "category": "Rent"}]
    fake_model(monkeypatch, json.dumps({"categories": items}))
    assert categorise(txs) == labels


def test_everything_needs_review_still_reconciles(monkeypatch, sept):
    txs, _ = sept
    fake_model(monkeypatch, "broken")
    result = categorise(txs)
    totals = totals_by_category(txs, result)
    check_totals(totals, txs)
    assert totals[NEEDS_REVIEW] == D("-127.18")


def test_model_receives_descriptions_amounts_and_categories(monkeypatch, sept):
    txs, labels = sept
    seen = []
    fake_model(monkeypatch, answer(labels), seen)
    categorise(txs)
    sent_txs, sent_categories = seen[0]
    assert sent_txs == txs
    assert tuple(sent_categories) == CATEGORIES


def test_llm_payload_and_prompt():
    payload = llm.build_payload(parse_csv(DATA / "sample_sept.csv"))
    first = json.loads(payload)["transactions"][0]
    assert first == {"id": 0, "description": "BONIFICO STIPENDIO CAFFE NAVIGLI", "amount": "1100.00"}
    prompt = llm.build_system_prompt(CATEGORIES)
    assert all(c in prompt for c in CATEGORIES)


def test_missing_env_raises_without_leaking(monkeypatch):
    monkeypatch.setattr(llm, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        llm.categorise_with_model(parse_csv(DATA / "sample_sept.csv"), CATEGORIES)


def relabel(txs, labels, index, category):
    out = list(labels)
    out[index] = category
    return out


def test_negative_amount_labelled_income_needs_review(monkeypatch, sept):
    txs, labels = sept
    i = 2  # ESSELUNGA, -42.30, truth: Groceries
    assert txs[i].amount < 0
    fake_model(monkeypatch, answer(relabel(txs, labels, i, "Income")))
    result = categorise(txs)
    assert result[i] == NEEDS_REVIEW
    assert result[:i] + result[i + 1:] == labels[:i] + labels[i + 1:]


@pytest.mark.parametrize("category", ["Rent", "Groceries", "Eating out", "Transport", "Subscriptions", "Shopping"])
def test_positive_amount_labelled_expense_needs_review(monkeypatch, sept, category):
    txs, labels = sept
    i = 0  # salary, +1100.00, truth: Income
    assert txs[i].amount > 0
    fake_model(monkeypatch, answer(relabel(txs, labels, i, category)))
    result = categorise(txs)
    assert result[i] == NEEDS_REVIEW
    assert result[1:] == labels[1:]


def test_sign_neutral_categories_are_kept(monkeypatch, sept):
    txs, labels = sept
    # Positive amount as a transfer (money coming back from savings) or Other is not rejected.
    for category in ("Transfer to own account", "Other"):
        fake_model(monkeypatch, answer(relabel(txs, labels, 0, category)))
        assert categorise(txs)[0] == category
    # Negative amount as Other / Transfer is fine too.
    fake_model(monkeypatch, answer(relabel(txs, labels, 2, "Other")))
    assert categorise(txs)[2] == "Other"


def test_sign_check_keeps_totals_reconciled(monkeypatch, sept):
    txs, labels = sept
    fake_model(monkeypatch, answer(relabel(txs, labels, 0, "Rent")))  # salary called Rent
    result = categorise(txs)
    totals = totals_by_category(txs, result)
    check_totals(totals, txs)
    assert totals["Income"] == D("0.00")
    assert totals["Needs review"] == D("-37.90") + D("1100.00")
