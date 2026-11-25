"""What llm.py sends to the API (fake client, no key, no network).

gpt-6.1-terra rejected two things the earlier code sent: temperature=0 (only the default is
allowed) and function tools while reasoning is on (needs reasoning_effort="none" on
/v1/chat/completions). These tests keep the requests acceptable."""
import pytest

from backend import llm

TOOLS = [{"type": "function", "function": {"name": "savings", "description": "x",
                                           "parameters": {"type": "object", "properties": {}}}}]
MESSAGES = [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}]


@pytest.fixture
def sent(monkeypatch):
    import openai
    requests = []

    class FakeOpenAI:
        def __init__(self, api_key=None):
            class Completions:
                def create(self, **kwargs):
                    requests.append(kwargs)
                    message = type("M", (), {"content": '{"categories": []}', "tool_calls": None})
                    return type("R", (), {"choices": [type("C", (), {"message": message})]})
            self.chat = type("Chat", (), {"completions": Completions()})

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(llm, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("OPENAI_MODEL", "fake-model")
    return requests


def test_categorising_request_leaves_temperature_at_its_default(sent):
    llm.categorise_with_model(["ESSELUNGA MILANO", "SPOTIFY AB"], ["Rent", "Needs review"])
    (request,) = sent
    assert "temperature" not in request            # the model only accepts its default
    assert request["model"] == "fake-model"
    assert request["response_format"] == {"type": "json_object"}
    assert [m["role"] for m in request["messages"]] == ["system", "user"]


def test_tool_calling_request_turns_reasoning_off_and_leaves_temperature(sent):
    llm.chat_with_tools(MESSAGES, TOOLS)
    (request,) = sent
    assert "temperature" not in request
    assert request["reasoning_effort"] == "none"   # function tools need it on /v1/chat/completions
    assert request["tools"] == TOOLS
    assert request["messages"] == MESSAGES


def test_a_call_without_tools_sends_no_tools_key(sent):
    llm.chat_with_tools(MESSAGES, [])
    assert "tools" not in sent[0]
