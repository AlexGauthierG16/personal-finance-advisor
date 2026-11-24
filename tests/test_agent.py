import copy
import json
from decimal import Decimal as D
from pathlib import Path

import pytest

from backend import agent, llm
from backend.categorise import CATEGORIES, read_labels
from backend.parser import parse_csv

DATA = Path(__file__).resolve().parent.parent / "data"
BUDGET = {"Groceries": D("200.00"), "Rent": D("650.00"), "Eating out": D("120.00")}


@pytest.fixture
def sept():
    txs = parse_csv(DATA / "sample_sept.csv")
    return txs, read_labels(DATA / "sample_sept_labels.csv", txs)


def call(name, args="{}", id="c1"):
    return {"id": id, "name": name, "arguments": args}


def say(text):
    return {"content": text, "tool_calls": []}


def ask(tool_calls):
    return {"content": None, "tool_calls": tool_calls}


class FakeModel:
    """Scripted stand-in for llm.chat_with_tools. `script` is a list of replies, or a callable."""

    def __init__(self, monkeypatch, script):
        self.script = script
        self.calls = []  # deep copies of (messages, tools) per model call
        monkeypatch.setattr(llm, "chat_with_tools", self)

    def __call__(self, messages, tools):
        self.calls.append((copy.deepcopy(messages), tools))
        if callable(self.script):
            return self.script(len(self.calls))
        return self.script[len(self.calls) - 1]


def run(sept, question="How am I doing?", budget=BUDGET):
    txs, labels = sept
    return agent.answer_question(question, txs, labels, budget)


def tool_results(messages):
    return [json.loads(m["content"]) for m in messages if m["role"] == "tool"]


def test_tool_then_answer(monkeypatch, sept):
    fake = FakeModel(monkeypatch, [ask([call("savings")]), say("Your savings are -27.18 EUR.")])
    result = run(sept)
    assert result.answer == "Your savings are -27.18 EUR."
    assert result.finished is True
    assert len(fake.calls) == 2
    assert [c["name"] for c in result.tool_calls] == ["savings"]
    second_messages = fake.calls[1][0]
    assert second_messages[-1]["role"] == "tool"
    assert "-27.18" in second_messages[-1]["content"]
    assert second_messages[-1]["tool_call_id"] == "c1"
    assert any(m["role"] == "user" and m["content"] == "How am I doing?" for m in second_messages)


def test_stops_after_five_steps(monkeypatch, sept):
    fake = FakeModel(monkeypatch, lambda n: ask([call("savings", id=f"c{n}")]))
    result = run(sept)
    assert len(fake.calls) == 5
    assert result.finished is False
    assert "5" in result.answer
    assert len(result.tool_calls) == 5


def test_answer_on_fifth_step_is_accepted(monkeypatch, sept):
    script = [ask([call("savings", id=f"c{i}")]) for i in range(4)] + [say("done: -27.18")]
    FakeModel(monkeypatch, script)
    result = run(sept)
    assert result.finished is True and result.answer == "done: -27.18"


def test_unknown_tool_does_not_crash(monkeypatch, sept):
    fake = FakeModel(monkeypatch, [ask([call("delete_everything")]), say("I cannot do that.")])
    result = run(sept)
    assert result.answer == "I cannot do that."
    (res,) = tool_results(fake.calls[1][0])
    assert "unknown tool" in res["error"]
    assert result.tool_calls[0]["name"] == "delete_everything"


@pytest.mark.parametrize("args", ["not json", "[1, 2]", "null"])
def test_bad_arguments_do_not_crash(monkeypatch, sept, args):
    fake = FakeModel(monkeypatch, [ask([call("list_transactions", args)]), say("ok")])
    assert run(sept).answer == "ok"
    (res,) = tool_results(fake.calls[1][0])
    assert "error" in res


def test_list_transactions_unknown_category_is_an_error(monkeypatch, sept):
    fake = FakeModel(monkeypatch, [ask([call("list_transactions", '{"category": "Fun money"}')]), say("ok")])
    run(sept)
    (res,) = tool_results(fake.calls[1][0])
    assert "error" in res


def test_list_transactions_result(monkeypatch, sept):
    fake = FakeModel(monkeypatch, [ask([call("list_transactions", '{"category": "Groceries"}')]), say("ok")])
    run(sept)
    (res,) = tool_results(fake.calls[1][0])
    assert len(res["transactions"]) == 6
    assert res["total"] == "-208.10"
    # no per-transaction date: dates are never sent to the model
    assert res["transactions"][0] == {"description": "ESSELUNGA MILANO LORENTEGGIO", "amount": "-42.30"}


def test_two_tool_calls_in_one_reply(monkeypatch, sept):
    fake = FakeModel(monkeypatch, [ask([call("savings", id="a"), call("needs_review_items", id="b")]), say("ok")])
    result = run(sept)
    tool_msgs = [m for m in fake.calls[1][0] if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["a", "b"]
    assert [c["name"] for c in result.tool_calls] == ["savings", "needs_review_items"]
    assistant = [m for m in fake.calls[1][0] if m["role"] == "assistant"][0]
    assert [t["id"] for t in assistant["tool_calls"]] == ["a", "b"]


def test_needs_review_items_result(monkeypatch, sept):
    fake = FakeModel(monkeypatch, [ask([call("needs_review_items")]), say("ok")])
    run(sept)
    (res,) = tool_results(fake.calls[1][0])
    assert res["total"] == "-37.90"
    assert [t["description"] for t in res["items"]] == ["PAYPAL *XYZ", "POS 4421", "POS 7730"]


def test_totals_by_category_result(monkeypatch, sept):
    fake = FakeModel(monkeypatch, [ask([call("totals_by_category")]), say("ok")])
    run(sept)
    (res,) = tool_results(fake.calls[1][0])
    assert res["totals"]["Groceries"] == "-208.10"
    assert res["totals"]["Income"] == "1100.00"
    assert list(res["totals"]) == list(CATEGORIES)


def test_variance_result_positive_means_over(monkeypatch, sept):
    fake = FakeModel(monkeypatch, [ask([call("variance")]), say("ok")])
    run(sept)
    (res,) = tool_results(fake.calls[1][0])
    assert res["variance"]["Groceries"] == "8.10"       # 208.10 - 200.00
    assert res["variance"]["Rent"] == "0.00"
    assert res["variance"]["Eating out"] == "-12.20"    # 107.80 - 120.00


def test_variance_without_budget_is_an_error(monkeypatch, sept):
    fake = FakeModel(monkeypatch, [ask([call("variance")]), say("No budget set.")])
    run(sept, budget={})
    (res,) = tool_results(fake.calls[1][0])
    assert "budget" in res["error"]


def test_system_prompt_rules_and_tools(monkeypatch, sept):
    fake = FakeModel(monkeypatch, [say("hi")])
    run(sept)
    messages, tools = fake.calls[0]
    assert messages[0]["role"] == "system"
    prompt = messages[0]["content"]
    assert "tool result" in prompt                      # numbers only from tool results
    assert "own arithmetic" in prompt or "calculate" in prompt
    assert "cannot" in prompt or "can't" in prompt      # say so when data cannot answer
    assert "Needs review" in prompt
    assert all(c in prompt for c in CATEGORIES)
    names = [t["function"]["name"] for t in tools]
    assert names == ["totals_by_category", "variance", "savings", "needs_review_items", "list_transactions"]
    enum = next(t for t in tools if t["function"]["name"] == "list_transactions")["function"]["parameters"]["properties"]["category"]["enum"]
    assert tuple(enum) == CATEGORIES


def test_infrastructure_errors_propagate(monkeypatch, sept):
    def boom(messages, tools):
        raise RuntimeError("OPENAI_API_KEY is not set (put it in .env)")
    monkeypatch.setattr(llm, "chat_with_tools", boom)
    with pytest.raises(RuntimeError):
        run(sept)


def test_llm_chat_with_tools_missing_env(monkeypatch):
    monkeypatch.setattr(llm, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        llm.chat_with_tools([{"role": "user", "content": "hi"}], [])


# --- number verification: every number in the final answer must appear in a tool result ---

def test_answer_with_numbers_from_tools_passes_unchanged(monkeypatch, sept):
    text = "You spent 208,10 on groceries and 650.00 on rent."  # tool results say -208.10 / -650.00
    FakeModel(monkeypatch, [ask([call("totals_by_category")]), say(text)])
    result = run(sept)
    assert result.unverified_numbers == []
    assert result.answer == text
    assert result.finished is True


def test_invented_number_gets_a_warning(monkeypatch, sept):
    text = "Your savings are -27.18 EUR, but you could save 150.00 more."
    FakeModel(monkeypatch, [ask([call("savings")]), say(text)])
    result = run(sept)
    assert result.unverified_numbers == ["150.00"]
    assert result.answer != text
    assert result.answer.startswith("Warning")
    assert "150.00" in result.answer.split("\n")[0]       # listed in the warning line
    assert "-27.18" not in result.answer.split("\n")[0]   # verified numbers are not listed
    assert text in result.answer                          # original answer is still included
    assert result.finished is True


def test_numbers_without_any_tool_call_are_unverified(monkeypatch, sept):
    FakeModel(monkeypatch, [say("You spent about 300 EUR.")])
    assert run(sept).unverified_numbers == ["300"]


def test_numbers_from_error_results_do_not_count(monkeypatch, sept):
    # the error text echoes the tool name, so "999" appears in a tool result - but only an error
    FakeModel(monkeypatch, [ask([call("delete_999")]), say("It is 999.")])
    assert run(sept).unverified_numbers == ["999"]


def test_amounts_and_description_numbers_from_tool_results_pass(monkeypatch, sept):
    text = "You paid 42.30 at Esselunga; POS 4421 needs review."
    FakeModel(monkeypatch, [ask([call("list_transactions", '{"category": "Groceries"}', id="a"),
                                 call("needs_review_items", id="b")]), say(text)])
    assert run(sept).unverified_numbers == []


def test_list_markers_and_trailing_punctuation_are_ignored(monkeypatch, sept):
    text = "1. Rent: 650.00\n2. Groceries: 208.10."
    FakeModel(monkeypatch, [ask([call("totals_by_category")]), say(text)])
    assert run(sept).unverified_numbers == []


def test_duplicates_are_listed_once(monkeypatch, sept):
    FakeModel(monkeypatch, [say("Try 150 or 150 or 75.")])
    assert run(sept).unverified_numbers == ["150", "75"]


def trace_with(**result):
    return [{"name": "t", "arguments": "{}", "result": result}]


@pytest.mark.parametrize("answer", [
    "208.10", "208,10", "-208.10", "€208.10", "EUR 208,10.", "(208.10)",
])
def test_same_value_different_formatting(answer):
    assert agent.unverified_numbers(answer, trace_with(total="-208.10")) == []


@pytest.mark.parametrize("answer", ["1,234.56", "1.234,56", "1234.56", "1234,56"])
def test_thousands_separators(answer):
    assert agent.unverified_numbers(answer, trace_with(total="1234.56")) == []


def test_near_miss_is_not_a_match():
    trace = trace_with(total="-208.10")
    assert agent.unverified_numbers("208.11", trace) == ["208.11"]
    assert agent.unverified_numbers("20.81", trace) == ["20.81"]
    assert agent.unverified_numbers("1,234.57", trace_with(total="1234.56")) == ["1,234.57"]


def test_trailing_zeros_do_not_matter():
    assert agent.unverified_numbers("208.1 and 208.100", trace_with(total="208.10")) == []


def test_no_numbers_means_nothing_to_verify():
    assert agent.unverified_numbers("You are under budget.", []) == []


# --- numbers the user typed in the question are accepted ---

def test_number_from_question_is_accepted():
    answer = "200 is lower than what you spent."
    assert agent.unverified_numbers(answer, [], "Is 200 too much for groceries?") == []
    assert agent.unverified_numbers(answer, [], "") == ["200"]


def test_question_number_formatting_and_other_numbers():
    q = "Can I afford 1.234,50 this month?"
    assert agent.unverified_numbers("1,234.50 is a lot; also 77.", [], q) == ["77"]


def test_question_number_accepted_end_to_end(monkeypatch, sept):
    FakeModel(monkeypatch, [ask([call("variance")]), say("Groceries are 8.10 over, so 200 is exceeded.")])
    result = run(sept, question="Is 200 too much for groceries?")
    assert result.unverified_numbers == []


def test_invented_number_still_flagged_with_question(monkeypatch, sept):
    FakeModel(monkeypatch, [ask([call("variance")]), say("200 is exceeded; try 150.00 instead.")])
    result = run(sept, question="Is 200 too much for groceries?")
    assert result.unverified_numbers == ["150.00"]


# --- student-focused system prompt ---

def test_system_prompt_is_for_students():
    p = agent.SYSTEM_PROMPT
    assert "student" in p and "tight budget" in p
    assert "5 sentences" in p
    assert "plain" in p                                   # plain language
    assert "concrete" in p and "own numbers" in p         # practical, based on their data
    assert "investment" in p                              # explicitly no investment advice
    assert "generic" in p                                 # no generic financial advice


def test_a_date_in_the_answer_is_flagged_because_dates_are_never_sent(monkeypatch, sept):
    FakeModel(monkeypatch, [ask([call("list_transactions", '{"category": "Groceries"}')]),
                            say("On 2025-09-02 you paid 42.30 at Esselunga.")])
    assert run(sept).unverified_numbers == ["2025", "09", "02"]


# --- the agent's work made visible: steps and numbers_checked ---

def steps_of(result):
    return agent.describe_steps(result.tool_calls)


def test_steps_in_order_with_tool_names_and_arguments(monkeypatch, sept):
    FakeModel(monkeypatch, [
        ask([call("totals_by_category", id="a")]),
        ask([call("list_transactions", '{"category": "Eating out"}', id="b")]),
        say("done"),
    ])
    assert steps_of(run(sept)) == [
        {"step": 1, "tool": "totals_by_category", "arguments": {}, "label": "totals_by_category",
         "summary": "9 categories with transactions", "ok": True},
        {"step": 2, "tool": "list_transactions", "arguments": {"category": "Eating out"},
         "label": "list_transactions(Eating out)", "summary": "7 transactions, total -107.80", "ok": True},
    ]


@pytest.mark.parametrize("name,args,summary", [
    ("variance", "{}", "7 categories, 4 over budget: Groceries, Shopping, Subscriptions, Transport"),
    ("savings", "{}", "savings -27.18, with 37.90 in Needs review counted as spending"),
    ("needs_review_items", "{}", "3 transactions, total -37.90"),
    ("list_transactions", '{"category": "Groceries"}', "6 transactions, total -208.10"),
    ("list_transactions", '{"category": "Other"}', "0 transactions, total 0.00"),
])
def test_step_summaries(monkeypatch, sept, name, args, summary):
    FakeModel(monkeypatch, [ask([call(name, args)]), say("ok")])
    (step,) = steps_of(run(sept))
    assert step["summary"] == summary
    assert step["ok"] is True


def test_two_tool_calls_in_one_reply_are_two_ordered_steps(monkeypatch, sept):
    FakeModel(monkeypatch, [ask([call("savings", id="a"), call("needs_review_items", id="b")]), say("ok")])
    steps = steps_of(run(sept))
    assert [(s["step"], s["tool"]) for s in steps] == [(1, "savings"), (2, "needs_review_items")]


def test_unknown_tool_step_is_marked_as_an_error(monkeypatch, sept):
    FakeModel(monkeypatch, [ask([call("delete_everything")]), say("no")])
    (step,) = steps_of(run(sept))
    assert step["ok"] is False
    assert step["summary"].startswith("error: unknown tool")
    assert step["tool"] == "delete_everything" and step["arguments"] == {}


def test_malformed_arguments_keep_the_raw_text(monkeypatch, sept):
    FakeModel(monkeypatch, [ask([call("list_transactions", "not json")]), say("no")])
    (step,) = steps_of(run(sept))
    assert step["ok"] is False
    assert step["arguments"] == "not json"
    assert step["label"] == "list_transactions"
    assert step["summary"].startswith("error:")


def test_unknown_category_and_missing_budget_are_error_steps(monkeypatch, sept):
    FakeModel(monkeypatch, [ask([call("list_transactions", '{"category": "Fun money"}', id="a"),
                                 call("variance", id="b")]), say("no")])
    steps = steps_of(run(sept, budget={}))
    assert [s["ok"] for s in steps] == [False, False]
    assert "Fun money" in steps[0]["summary"]
    assert "budget" in steps[1]["summary"]


def test_no_tool_calls_means_no_steps(monkeypatch, sept):
    FakeModel(monkeypatch, [say("I can only look at your statement.")])
    assert steps_of(run(sept)) == []


def test_step_limit_run_still_has_its_steps(monkeypatch, sept):
    FakeModel(monkeypatch, lambda n: ask([call("savings", id=f"c{n}")]))
    result = run(sept)
    assert result.finished is False
    assert [s["step"] for s in steps_of(result)] == [1, 2, 3, 4, 5]


def test_numbers_checked_counts_distinct_numbers(monkeypatch, sept):
    FakeModel(monkeypatch, [ask([call("savings")]), say("Savings -27.18; 37.90 is uncertain; again -27.18.")])
    result = run(sept)
    assert result.numbers_checked == 2
    assert result.unverified_numbers == []


def test_numbers_checked_zero_when_the_answer_has_no_numbers(monkeypatch, sept):
    FakeModel(monkeypatch, [say("You are under budget.")])
    assert run(sept).numbers_checked == 0


def test_numbers_checked_includes_invented_numbers(monkeypatch, sept):
    FakeModel(monkeypatch, [ask([call("savings")]), say("Savings -27.18 but save 150.00 more.")])
    result = run(sept)
    assert result.numbers_checked == 2
    assert result.unverified_numbers == ["150.00"]


def test_answer_numbers_ignores_list_markers():
    assert agent.answer_numbers("1. Rent 650.00\n2. Rent 650,00 and 12") == ["650.00", "650,00", "12"]


# --- the variance tool also returns actual and budget, so quoting them can be verified ---

def test_variance_result_includes_actual_and_budget(monkeypatch, sept):
    fake = FakeModel(monkeypatch, [ask([call("variance")]), say("ok")])
    run(sept)
    (res,) = tool_results(fake.calls[1][0])
    assert res["actual"]["Groceries"] == "208.10"
    assert res["budget"]["Groceries"] == "200.00"
    assert res["variance"]["Groceries"] == "8.10"
    assert res["actual"]["Eating out"] == "107.80" and res["budget"]["Eating out"] == "120.00"
    assert res["actual"]["Transport"] == "43.40" and res["budget"]["Transport"] == "0.00"   # no budget set
    assert set(res["actual"]) == set(res["budget"]) == set(res["variance"])


def test_quoting_actual_and_budget_from_variance_is_verified(monkeypatch, sept):
    FakeModel(monkeypatch, [ask([call("variance")]),
                            say("Groceries: 208.10 spent against a 200.00 budget, so 8.10 over. "
                                "Eating out: 107.80 against 120.00, so 12.20 under.")])
    result = run(sept)
    assert result.unverified_numbers == []
    assert result.numbers_checked == 6


def test_a_wrong_budget_figure_is_still_flagged(monkeypatch, sept):
    FakeModel(monkeypatch, [ask([call("variance")]), say("Groceries: 208.10 against a 250.00 budget.")])
    assert run(sept).unverified_numbers == ["250.00"]
