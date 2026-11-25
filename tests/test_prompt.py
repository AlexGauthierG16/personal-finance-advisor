"""The categorising prompt: general guidance by type of business, no merchant names taken from
our data files (that would overfit the evaluation), and "Needs review" only for descriptions
that give no clue about what was bought."""
import csv
import re
from pathlib import Path

from backend import llm
from backend.categorise import CATEGORIES

DATA = Path(__file__).resolve().parent.parent / "data"
PROMPT = llm.build_system_prompt(CATEGORIES)
WORD = re.compile(r"[a-zà-ÿ]{4,}")


def test_every_category_is_in_the_prompt():
    assert all(c in PROMPT for c in CATEGORIES)


def test_guidance_is_by_type_of_business():
    for kinds, category in [
        (("restaurants", "food delivery"), "Eating out"),
        (("supermarkets", "bakeries"), "Groceries"),
        (("public transport", "trains"), "Transport"),
    ]:
        line = next(l for l in PROMPT.split("\n") if f"-> {category}" in l)   # one mapping per category
        assert all(k in line for k in kinds), (category, line)


def test_needs_review_is_only_for_descriptions_with_no_clue():
    assert "only when" in PROMPT
    assert "no clue" in PROMPT
    assert '"POS 1234"' in PROMPT and '"PAYPAL *XYZ"' in PROMPT        # the examples we were asked to give
    assert "most likely category" in PROMPT                            # recognisable business: pick one


def test_the_old_refuse_when_unsure_wording_is_gone():
    assert "Do not guess" not in PROMPT
    assert "If you are not sure" not in PROMPT


def test_the_prompt_names_no_merchant_from_our_data_files():
    data_words = set()
    for name in ["sample_sept.csv", "sample_oct.csv", "demo_nov.csv", "sample_private.csv"]:
        with (DATA / name).open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                data_words |= set(WORD.findall(row["description"].lower()))
    shared = set(WORD.findall(PROMPT.lower())) & data_words
    # allowed overlaps: "paypal" (the "PAYPAL *XYZ" example we were asked to give) and "iban"
    # (the [IBAN] privacy placeholder the prompt already explains): neither is a merchant name
    assert shared <= {"paypal", "iban"}, sorted(shared)


def test_the_prompt_still_asks_for_json_and_treats_descriptions_as_data():
    assert "untrusted data" in PROMPT
    assert '"categories"' in PROMPT and "one entry per transaction id" in PROMPT
