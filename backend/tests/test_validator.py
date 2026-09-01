"""Validator tests (spec §5.1).

The validator is the quality mechanism — never stubbed, never skipped (§0.2) — so its
checks get direct coverage rather than being exercised only through the pipeline.
"""

import pytest

from recitai.generation.schemas import GeneratedOption, GeneratedQuestion
from recitai.generation.validator import (
    BANNED_PHRASE,
    EMPTY_FIELD,
    LEAKAGE,
    LENGTH_BIAS,
    NEGATION,
    check_banned_phrases,
    check_empty,
    check_leakage,
    check_length_bias,
    check_negation,
)


def _q(
    stem: str = "Which property guarantees every item appears in some fragment?",
    correct: str = "Completeness",
    distractors: tuple[str, str, str] = ("Disjointness", "Reconstruction", "Decomposition"),
    difficulty: str = "recall",
    explanation: str = "The passage defines completeness this way.",
) -> GeneratedQuestion:
    options = [GeneratedOption(id="A", text=correct, is_correct=True, why_wrong=None)]
    for letter, text in zip("BCD", distractors, strict=True):
        options.append(
            GeneratedOption(id=letter, text=text, is_correct=False, why_wrong="a misconception")  # type: ignore[arg-type]
        )
    return GeneratedQuestion(
        stem=stem,
        options=options,
        explanation=explanation,
        difficulty=difficulty,  # type: ignore[arg-type]
    )


def test_a_clean_question_passes_every_free_check() -> None:
    q = _q()
    assert check_empty(q) == []
    assert check_length_bias(q) == []
    assert check_banned_phrases(q) == []
    assert check_negation(q) == []
    assert check_leakage(q) == []


def test_length_bias_catches_a_padded_correct_answer() -> None:
    """§5.1's highest-yield check: models pad the correct answer with qualifying clauses,
    which makes the quiz answerable without reading the material."""
    padded = _q(
        correct=(
            "Completeness, which guarantees that every single data item in the original "
            "relation can also be found in at least one of the resulting fragments"
        )
    )
    assert check_length_bias(padded) == [LENGTH_BIAS]


def test_banned_phrases_are_rejected_case_insensitively() -> None:
    assert check_banned_phrases(_q(distractors=("All of the Above", "B", "C"))) == [BANNED_PHRASE]
    assert check_banned_phrases(_q(distractors=("none of these.", "B", "C"))) == [BANNED_PHRASE]


def test_negation_in_a_non_analysis_stem_is_rejected() -> None:
    assert check_negation(_q(stem="Which of these is NOT a fragment property?")) == [NEGATION]


def test_negation_is_allowed_at_analysis_difficulty() -> None:
    q = _q(stem="Which of these is NOT a fragment property?", difficulty="analysis")
    assert check_negation(q) == []


@pytest.mark.parametrize("word", ["cannot", "notation", "note", "notably", "annotated"])
def test_negation_does_not_fire_on_words_containing_not(word: str) -> None:
    """I-009. A naive substring scan rejects a large share of technical prose, and each
    false rejection burns a regeneration attempt."""
    assert check_negation(_q(stem=f"Which {word} describes the fragmentation rule?")) == []


def test_leakage_catches_the_answer_phrase_repeated_in_the_stem() -> None:
    q = _q(
        stem="Which rule ensures lossless decomposition of a relation into fragments?",
        correct="lossless decomposition of a relation",
    )
    assert check_leakage(q) == [LEAKAGE]


def test_leakage_ignores_stopword_only_overlap() -> None:
    """ "of the" appearing in both is not leakage."""
    q = _q(stem="What is the goal of the design step?", correct="of the")
    assert check_leakage(q) == []


def test_empty_explanation_is_rejected_at_the_schema_boundary() -> None:
    """Defence in depth: the schema refuses it first, so the validator's EMPTY_FIELD
    check never sees a model built the normal way."""
    with pytest.raises(ValueError, match="empty or whitespace-only"):
        _q(explanation="   ")


def test_empty_field_check_is_the_backstop() -> None:
    """For a model built without validation — a future code path, a loaded record — the
    validator still catches it."""
    q = GeneratedQuestion.model_construct(
        stem="   ",
        options=_q().options,
        explanation="fine",
        difficulty="recall",
    )
    assert check_empty(q) == [EMPTY_FIELD]


def test_distractor_without_a_rationale_fails_schema() -> None:
    """The wrong-answer moment is the product (§4.5); a distractor with no rationale
    cannot render it."""
    q = _q()
    q.options[1].why_wrong = ""
    assert check_empty(q) == ["SCHEMA"]


def test_schema_rejects_two_correct_options() -> None:
    with pytest.raises(ValueError, match="exactly one option must be correct"):
        GeneratedQuestion(
            stem="s",
            options=[
                GeneratedOption(id="A", text="a", is_correct=True),
                GeneratedOption(id="B", text="b", is_correct=True),
                GeneratedOption(id="C", text="c", is_correct=False, why_wrong="w"),
                GeneratedOption(id="D", text="d", is_correct=False, why_wrong="w"),
            ],
            explanation="e",
            difficulty="recall",
        )
