"""Masks personal data in transaction descriptions before anything is sent to the model.

Pure Python rules (regular expressions), no model call. Placeholders: [IBAN], [EMAIL], [CF],
[PHONE], [CARD], [NAME]. Merchant names are left alone.

Rules, applied in this order so that longer patterns win:
  IBAN, email, codice fiscale, international phone (+CC / 00CC), card number (13-19 digits, or
  masked forms like ****1234; not even the last 4 are kept), Italian mobile, Italian landline,
  then names after a transfer word.

Names: only after DA, A FAVORE DI, BONIFICO [SEPA|ISTANTANEO|ESTERO] A/DA, ORDINANTE,
BENEFICIARIO. Everything after the keyword is masked while the words look like a name, up to
the next stop word (CAUSALE, IBAN, CF, RIF, ... see STOPWORDS), a digit, a placeholder or the
end of the description. Bare DA needs at least two name words, so "PAGAMENTO DA ESSELUNGA SPA"
and "BONIFICO DA UNIVERSITA BOCCONI" stay readable.

Limits (over-masking is the safe direction, under-masking is the risk):
  * names that do not follow one of those words (e.g. "PAGAMENTO POS MARIO ROSSI",
    "PAYPAL *LUCA VERDI") are NOT masked; nor are nicknames or street addresses;
  * a word after the name that is not in STOPWORDS is taken as part of the name and masked;
  * employer names after DA / BONIFICO DA get masked unless a stop word comes first;
  * long reference numbers can look like phone numbers or cards and are masked;
  * dates or amounts written inside the description text are NOT removed;
  * no checksum validation: mistyped IBANs and codici fiscali are still masked.
"""
import re

_FLAGS = re.IGNORECASE

IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b", _FLAGS)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", _FLAGS)
_CF_DIGIT = r"[\dLMNPQRSTUV]"  # a digit, or the letter that replaces it in "omocodia" cases
CODICE_FISCALE = re.compile(
    rf"\b[A-Z]{{6}}{_CF_DIGIT}{{2}}[A-EHLMPR-T]{_CF_DIGIT}{{2}}[A-Z]{_CF_DIGIT}{{3}}[A-Z]\b", _FLAGS)
PHONE_INTL = re.compile(r"(?<![\w+])(?:\+|00)\d{1,3}[ .-]?\d(?:[ .-]?\d){6,11}(?!\d)")
CARD_DIGITS = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
CARD_STARS = re.compile(r"(?<![\w*])\*{4,}(?:[ -]?\*{4})*[ -]?\d{4}(?!\d)")
CARD_XS = re.compile(r"(?<!\w)(?:X{4}[ -]?){2,3}\d{4}(?!\d)", _FLAGS)
PHONE_MOBILE = re.compile(r"(?<![\w+])3\d{2}[ .-]?\d{3}[ .-]?\d{3,4}(?!\d)")
PHONE_LANDLINE = re.compile(r"(?<![\w+])0\d{1,3}[ /.-]\d{5,8}(?!\d)")

_MASKS = [
    (IBAN, "[IBAN]"),
    (EMAIL, "[EMAIL]"),
    (CODICE_FISCALE, "[CF]"),
    (PHONE_INTL, "[PHONE]"),
    (CARD_DIGITS, "[CARD]"),
    (CARD_STARS, "[CARD]"),
    (CARD_XS, "[CARD]"),
    (PHONE_MOBILE, "[PHONE]"),
    (PHONE_LANDLINE, "[PHONE]"),
]

# Transfer words after which a person's name is expected. Longest alternatives first.
_KEYWORD = re.compile(
    r"\b(?:BONIFICO(?:\s+(?:SEPA|ISTANTANEO|ESTERO))?\s+(?:A\s+FAVORE\s+DI|A|DA)"
    r"|A\s+FAVORE\s+DI|ORDINANTE|BENEFICIARIO|DA)\b:?",
    _FLAGS,
)
_BARE_DA = re.compile(r"DA", _FLAGS)
_WORD = re.compile(r"\S+")
_NAME_WORD = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*\.?")  # letters, with ' - and a final .

# Words that end a name: structure words and merchants/institutions, never part of a person's name.
STOPWORDS = frozenset("""
CONTO RISPARMIO CAUSALE RIF RIFERIMENTO REF CRO TRN IBAN CF CODICE FISCALE
SPA SRL SARL SNC SAS UNIVERSITA POLITECNICO COMUNE REGIONE INPS BANCA
PAGAMENTO RICARICA AFFITTO STIPENDIO RIMBORSO CARTA POS TEL
ESSELUNGA CARREFOUR GLOVO SPOTIFY AMAZON PAYPAL ATM NETFLIX
""".split())


def _name_span(text: str, start: int, min_words: int):
    """(first, end) of the name starting at `start`, or None if it is too short."""
    first = end = None
    count = 0
    pos = start
    while True:
        m = _WORD.search(text, pos)
        if not m:
            break
        word = m.group()
        bare = word.rstrip(",;:")
        if not _NAME_WORD.fullmatch(bare) or bare.upper() in STOPWORDS:
            break
        if first is None:
            first = m.start()
        end = m.start() + len(bare)
        count += 1
        pos = m.end()
        if bare != word:  # a comma or semicolon ends the name
            break
    return (first, end) if count >= min_words else None


def _mask_names(text: str) -> str:
    out, pos = [], 0
    for m in _KEYWORD.finditer(text):
        if m.start() < pos:
            continue
        min_words = 2 if _BARE_DA.fullmatch(m.group().rstrip(":")) else 1
        span = _name_span(text, m.end(), min_words)
        if span:
            out.append(text[pos:span[0]])
            out.append("[NAME]")
            pos = span[1]
    out.append(text[pos:])
    return "".join(out)


def anonymise(description: str) -> str:
    """The description with personal data replaced by placeholders (idempotent)."""
    text = description.strip()
    for pattern, placeholder in _MASKS:
        text = pattern.sub(placeholder, text)
    return _mask_names(text)
