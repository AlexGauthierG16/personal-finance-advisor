import json
from pathlib import Path

import pytest

from backend import agent, llm, privacy
from backend.categorise import categorise
from backend.parser import parse_csv

DATA = Path(__file__).resolve().parent.parent / "data"
anonymise = privacy.anonymise

# Everything below is fictional (documentation-example IBANs, test card numbers, example.com).
PERSONAL_DATA = [
    "IT60X0542811101000000123456", "IT28 W800 0000 2921 0064 5211 208", "IT28W8000000292100645211208",
    "5555555555554444", "4929-1234-5678-9012", "4929123456789012",
    "ROSSI", "MARIO", "BIANCHI", "GIULIA", "ANNA", "VERDI", "LUCA",
    "BNCNNA90A41F205Q", "EXAMPLE.COM", "333 1234567", "3331234567", "1234567",
]

# Hand-written expected output for every row of data/sample_private.csv.
PRIVATE_EXPECTED = [
    "ESSELUNGA MILANO LORENTEGGIO",
    "BONIFICO DA [NAME] CAUSALE PAGAMENTO LEZIONI",
    "BONIFICO A FAVORE DI [NAME] [IBAN] AFFITTO",
    "AMAZON EU SARL CARTA [CARD]",
    "SPOTIFY AB",
    "RICARICA TELEFONICA [PHONE]",
    "ORDINANTE: [NAME] CF [CF]",
    "GLOVO ORDER 8841",
    "RIMBORSO PAYPAL [EMAIL]",
    "CARREFOUR EXPRESS MILANO",
    "BONIFICO A [NAME] CAUSALE AFFITTO OTTOBRE",
    "ATM MILANO TICKET",
    "BENEFICIARIO: [NAME] IBAN [IBAN]",
    "TRASFERIMENTO A CONTO RISPARMIO",
    "BAR BASSO MILANO TEL. [PHONE]",
    "PAGAMENTO CARTA [CARD] BAR TICINESE",
]


# ------------------------------------------------------------------ one test per type

@pytest.mark.parametrize("text,expected", [
    ("BONIFICO IT60X0542811101000000123456 PER AFFITTO", "BONIFICO [IBAN] PER AFFITTO"),
    ("IBAN IT60 X054 2811 1010 0000 0123 456 RIF AFFITTO", "IBAN [IBAN] RIF AFFITTO"),
    ("it60x0542811101000000123456", "[IBAN]"),
    ("DE89370400440532013000", "[IBAN]"),
])
def test_iban(text, expected):
    assert anonymise(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("CARTA 5555555555554444 AMAZON", "CARTA [CARD] AMAZON"),
    ("CARTA 5555 5555 5555 4444 AMAZON", "CARTA [CARD] AMAZON"),
    ("CARTA 5555-5555-5555-4444 AMAZON", "CARTA [CARD] AMAZON"),
    ("CARTA 378282246310005 AMAZON", "CARTA [CARD] AMAZON"),          # 15 digits
    ("CARTA ****1234 AMAZON", "CARTA [CARD] AMAZON"),
    ("CARTA **** **** **** 1234 AMAZON", "CARTA [CARD] AMAZON"),
    ("CARTA XXXX XXXX XXXX 1234 AMAZON", "CARTA [CARD] AMAZON"),
])
def test_card(text, expected):
    result = anonymise(text)
    assert result == expected
    assert "1234" not in result and "4444" not in result  # the last 4 are not kept either


@pytest.mark.parametrize("text,expected", [
    ("CF BNCNNA90A41F205Q", "CF [CF]"),
    ("cf bncnna90a41f205q", "cf [CF]"),
    ("CF RSSMRA80A01H50MX", "CF [CF]"),                 # omocodia: a digit replaced by a letter
])
def test_codice_fiscale(text, expected):
    assert anonymise(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("RIMBORSO MARIO.ROSSI@EXAMPLE.COM", "RIMBORSO [EMAIL]"),
    ("rimborso a_b+c@uni.mi.it grazie", "rimborso [EMAIL] grazie"),
])
def test_email(text, expected):
    assert anonymise(text) == expected


@pytest.mark.parametrize("text", [
    "RICARICA +39 333 1234567", "RICARICA 0039 333 1234567", "RICARICA 333 1234567",
    "RICARICA 3331234567", "RICARICA 333 123 4567", "RICARICA +393331234567",
    "RICARICA +44 20 7946 0958", "TEL 02 1234567", "TEL 02/1234567",
])
def test_phone(text):
    result = anonymise(text)
    assert result.endswith("[PHONE]"), result
    assert not any(ch.isdigit() for ch in result.replace("[PHONE]", ""))


@pytest.mark.parametrize("text,expected", [
    ("BONIFICO DA ROSSI MARIO CAUSALE PAGAMENTO LEZIONI", "BONIFICO DA [NAME] CAUSALE PAGAMENTO LEZIONI"),
    ("BONIFICO A ROSSI MARIO CAUSALE AFFITTO", "BONIFICO A [NAME] CAUSALE AFFITTO"),
    ("BONIFICO A ROSSI MARIO AFFITTO OTTOBRE", "BONIFICO A [NAME] AFFITTO OTTOBRE"),
    ("BONIFICO SEPA DA ROSSI MARIO", "BONIFICO SEPA DA [NAME]"),
    ("BONIFICO ISTANTANEO A Giulia Bianchi", "BONIFICO ISTANTANEO A [NAME]"),
    ("BONIFICO A FAVORE DI GIULIA BIANCHI RIF AFFITTO", "BONIFICO A FAVORE DI [NAME] RIF AFFITTO"),
    ("A FAVORE DI Giulia Bianchi", "A FAVORE DI [NAME]"),
    ("ORDINANTE: BIANCHI ANNA", "ORDINANTE: [NAME]"),
    ("ORDINANTE BIANCHI ANNA", "ORDINANTE [NAME]"),
    ("BENEFICIARIO: VERDI LUCA", "BENEFICIARIO: [NAME]"),
    ("beneficiario: verdi luca", "beneficiario: [NAME]"),
    ("PAGAMENTO DA MARIO ROSSI", "PAGAMENTO DA [NAME]"),
    ("BONIFICO DA DE LUCA ANNA MARIA GRAZIA CAUSALE X", "BONIFICO DA [NAME] CAUSALE X"),  # at most 4 words
    ("BONIFICO DA O'BRIEN MARY-ANN CAUSALE X", "BONIFICO DA [NAME] CAUSALE X"),
])
def test_names_after_transfer_words(text, expected):
    assert anonymise(text) == expected


def test_combined_in_one_description():
    text = "BONIFICO A FAVORE DI GIULIA BIANCHI IT60X0542811101000000123456 TEL 3331234567 g.b@example.com"
    assert anonymise(text) == "BONIFICO A FAVORE DI [NAME] [IBAN] TEL [PHONE] [EMAIL]"


# ------------------------------------------------------------------ merchants untouched

@pytest.mark.parametrize("text", [
    "TRASFERIMENTO A CONTO RISPARMIO",
    "BONIFICO A CONTO RISPARMIO",
    "BONIFICO STIPENDIO CAFFE NAVIGLI",
    "BONIFICO DA UNIVERSITA BOCCONI",
    "PAGAMENTO DA ESSELUNGA SPA",
    "PAGAMENTO DA MARIO",                  # bare DA needs two name words
    "GLOVO ORDER 8841", "POS 4421", "PAYPAL *XYZ", "BAR BASSO MILANO", "SPOTIFY AB",
    "AFFITTO SETTEMBRE VIA PADOVA 12", "ATM MILANO ABBONAMENTO MENSILE", "AMAZON EU SARL",
    "CARREFOUR EXPRESS MILANO", "ESSELUNGA MILANO LORENTEGGIO",
])
def test_merchants_and_ordinary_text_are_unchanged(text):
    assert anonymise(text) == text


@pytest.mark.parametrize("name", ["sample_sept.csv", "sample_oct.csv"])
def test_every_description_in_the_sample_statements_is_unchanged(name):
    for t in parse_csv(DATA / name):
        assert anonymise(t.description) == t.description, t.description


def test_sample_private_rows_exact():
    txs = parse_csv(DATA / "sample_private.csv")
    assert len(txs) == 16
    assert [anonymise(t.description) for t in txs] == PRIVATE_EXPECTED


def test_idempotent_and_stripped():
    for text in [t.description for t in parse_csv(DATA / "sample_private.csv")]:
        once = anonymise(text)
        assert anonymise(once) == once
    assert anonymise("  SPOTIFY AB \n") == "SPOTIFY AB"
    assert anonymise("") == ""


def test_masked_text_contains_no_personal_data():
    for t in parse_csv(DATA / "sample_private.csv"):
        result = anonymise(t.description).upper()
        for secret in PERSONAL_DATA:
            assert secret.upper() not in result, (secret, result)


# ------------------------------------------------------------------ nothing leaks to the model

class RecordingOpenAI:
    """Stands in for openai.OpenAI; records every message sent."""
    sent = []

    def __init__(self, api_key=None):
        outer = self

        class Completions:
            def create(self, **kwargs):
                RecordingOpenAI.sent.append(json.dumps(kwargs, ensure_ascii=False))
                message = type("M", (), {"content": json.dumps({"categories": []}), "tool_calls": None})
                return type("R", (), {"choices": [type("C", (), {"message": message})]})
        self.chat = type("Chat", (), {"completions": Completions()})


@pytest.fixture
def recording_openai(monkeypatch):
    import openai
    RecordingOpenAI.sent = []
    monkeypatch.setattr(openai, "OpenAI", RecordingOpenAI)
    monkeypatch.setattr(llm, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("OPENAI_MODEL", "fake-model")
    return RecordingOpenAI


def assert_clean(sent_text, txs):
    upper = sent_text.upper()
    for secret in PERSONAL_DATA:
        assert secret.upper() not in upper, secret
    for t in txs:
        assert str(t.amount) not in sent_text, f"amount {t.amount} was sent"
        assert t.date.isoformat() not in sent_text, f"date {t.date} was sent"
    assert "2025-" not in sent_text


def test_categorising_sends_no_personal_data_amounts_or_dates(recording_openai):
    txs = parse_csv(DATA / "sample_private.csv")
    labels = categorise(txs)
    assert len(labels) == 16                       # the (empty) fake answer -> everything Needs review
    assert len(recording_openai.sent) == 1
    sent = recording_openai.sent[0]
    assert_clean(sent, txs)
    assert "[IBAN]" in sent and "[NAME]" in sent and "ESSELUNGA MILANO LORENTEGGIO" in sent  # merchants stay


def test_agent_tool_results_send_no_personal_data_or_dates(monkeypatch):
    txs = parse_csv(DATA / "sample_private.csv")
    labels = ["Other"] * 16
    labels[1] = labels[6] = labels[8] = "Needs review"
    seen = []
    script = [
        {"content": None, "tool_calls": [
            {"id": "a", "name": "list_transactions", "arguments": '{"category": "Other"}'},
            {"id": "b", "name": "needs_review_items", "arguments": "{}"}]},
        {"content": "ok", "tool_calls": []},
    ]

    def fake(messages, tools):
        seen.append(json.dumps(messages, ensure_ascii=False))
        return script[len(seen) - 1]
    monkeypatch.setattr(llm, "chat_with_tools", fake)
    result = agent.answer_question("What are my biggest expenses?", txs, labels, {})
    assert result.finished
    tool_text = seen[1]
    for secret in PERSONAL_DATA:
        assert secret.upper() not in tool_text.upper(), secret
    assert "2025-" not in tool_text
    assert "[NAME]" in tool_text or "[IBAN]" in tool_text


def test_llm_refuses_anything_but_plain_strings(monkeypatch):
    monkeypatch.setattr(llm, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("OPENAI_MODEL", "fake-model")
    txs = parse_csv(DATA / "sample_private.csv")
    with pytest.raises(TypeError):
        llm.categorise_with_model(txs, ["Other"])          # Transaction objects carry amount and date
    with pytest.raises(TypeError):
        llm.categorise_with_model(["ok", 5], ["Other"])
