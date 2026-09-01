"""The answer-leak boundary (spec §12, plan/ISSUES.md I-010).

Correctness lives inside the stored options blob with no separate column, so the strip
happens at serialization. If it is ever missed, every answer is in the network tab while
the UI looks normal — invisible and total. These tests assert the property directly on
the serialised bytes, not on the code path that produces them.
"""

import uuid

import pytest
from pydantic import ValidationError

from recitai.api.schemas import PublicOption, PublicQuestion, to_public_question

STORED_OPTIONS = [
    {"id": "A", "text": "Completeness", "is_correct": True, "why_wrong": None},
    {"id": "B", "text": "Disjointness", "is_correct": False, "why_wrong": "confuses overlap"},
    {"id": "C", "text": "Reconstruction", "is_correct": False, "why_wrong": "confuses rebuild"},
    {"id": "D", "text": "Decomposition", "is_correct": False, "why_wrong": "confuses splitting"},
]


def _public() -> PublicQuestion:
    return to_public_question(
        uuid.uuid4(),
        "Which property guarantees every item appears in some fragment?",
        STORED_OPTIONS,
        difficulty="recall",
        page_refs=[9, 10],
    )


def test_serialised_payload_contains_no_answer() -> None:
    """The assertion that matters: neither substring may appear in what goes over the
    wire, however the object was built."""
    payload = _public().model_dump_json()
    assert "is_correct" not in payload
    assert "why_wrong" not in payload
    assert "confuses overlap" not in payload


def test_all_four_options_survive_the_strip() -> None:
    """Stripping the answer must not lose the question."""
    public = _public()
    assert [o.id for o in public.options] == ["A", "B", "C", "D"]
    assert [o.text for o in public.options] == [o["text"] for o in STORED_OPTIONS]


def test_the_public_option_cannot_carry_correctness_at_all() -> None:
    """Not "we remember to strip it" but "there is nowhere to put it"."""
    assert "is_correct" not in PublicOption.model_fields
    assert "why_wrong" not in PublicOption.model_fields
    with pytest.raises(ValidationError):
        PublicOption(id="A", text="x", is_correct=True)  # type: ignore[call-arg]


def test_a_field_added_to_the_stored_blob_is_not_forwarded() -> None:
    """A future column on the stored option must not leak by default."""
    stored = [dict(o, secret_hint="the answer is A") for o in STORED_OPTIONS]
    payload = to_public_question(uuid.uuid4(), "s", stored).model_dump_json()
    assert "secret_hint" not in payload


def test_citations_are_preserved_because_the_student_needs_them() -> None:
    """I1: page references are not secret — they are the product."""
    public = _public()
    assert public.page_refs == [9, 10]
