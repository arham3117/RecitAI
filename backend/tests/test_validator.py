"""Validator tests (spec §5.1).

The validator is the quality mechanism — never stubbed, never skipped (§0.2) — so its
checks get direct coverage rather than being exercised only through the pipeline.
"""

import pytest

from recitai.generation.schemas import GeneratedOption, GeneratedQuestion
from recitai.generation.validator import (
    BANNED_PHRASE,
    EMPTY_FIELD,
    INVENTED_RANKING,
    LEAKAGE,
    LENGTH_BIAS,
    NEGATION,
    NUMERIC_UNSUPPORTED,
    check_banned_phrases,
    check_empty,
    check_invented_ranking,
    check_leakage,
    check_length_bias,
    check_negation,
    check_unsupported_number,
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
            GeneratedOption(id=letter, text=text, is_correct=False, why_wrong="a misconception")
        )
    return GeneratedQuestion(
        stem=stem,
        options=options,
        explanation=explanation,
        difficulty=difficulty,
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


# ------------------------------------------------------- invented ranking (I-028) ----


def test_invented_ranking_is_rejected_when_the_passage_ranks_nothing() -> None:
    """The commonest source of two defensible answers: the passage lists several
    properties, the model asks which is *most important*, and a student who reasons
    correctly is marked wrong."""
    q = _q(stem="What is the main problem with deletion in non-recursive views?")
    passage = "Deletion in non-recursive views is difficult. View maintenance is costly."
    assert check_invented_ranking(q, passage) == [INVENTED_RANKING]


def test_invented_ranking_is_allowed_when_the_passage_ranks() -> None:
    """A question is fair if the passage itself picks one out."""
    q = _q(stem="What is the primary objective of semantic data control?")
    passage = "The primary objective of semantic data control is to ensure integrity."
    assert check_invented_ranking(q, passage) == []


def test_ordinary_stems_are_untouched_by_the_ranking_check() -> None:
    assert check_invented_ranking(_q(), "any passage at all") == []


@pytest.mark.parametrize(
    "stem",
    [
        "What is the primary key of the relation?",
        "Which is the chief advantage of vertical fragmentation?",
        "What is the most important step in the VF algorithm?",
    ],
)
def test_ranking_variants_are_caught(stem: str) -> None:
    assert check_invented_ranking(_q(stem=stem), "a passage without ranking words") == [
        INVENTED_RANKING
    ]


# ------------------------------------------------- unsupported numbers (I-029) ----


def test_a_number_the_passage_never_states_is_rejected() -> None:
    """The measured failure: llama3.1:8b answered "8 rows" and qwen2.5:14b answered "48"
    for a Cartesian product with 32. Both narrated the correct method and then computed
    wrongly, and no judge catches it — the claim is grounded, unique and plausible."""
    q = _q(correct="A table with 8 rows and 5 columns")
    passage = "EMP | ENO | ENAME\nE1 | J. Doe\nE8 | J. Jones\nSALARY 55000"
    assert check_unsupported_number(q, passage) == [NUMERIC_UNSUPPORTED]


def test_digits_inside_a_larger_token_do_not_count_as_present() -> None:
    """The check is word-boundary anchored on purpose. The "8" in "E8" and the "5" in
    "55000" are not the numbers 8 and 5 — reading them as present is what made an earlier
    version of this check appear useless, and led me to dismiss it."""
    passage = "E8 pays 55000"
    assert check_unsupported_number(_q(correct="8"), passage) == [NUMERIC_UNSUPPORTED]
    assert check_unsupported_number(_q(correct="5"), passage) == [NUMERIC_UNSUPPORTED]


def test_a_number_stated_in_the_passage_is_allowed() -> None:
    """Recall questions over stated figures must stay askable."""
    passage = "PROJ | P1 | Instrumentation | 150000 | Montreal"
    assert check_unsupported_number(_q(correct="150000"), passage) == []


def test_answers_without_numbers_are_untouched() -> None:
    assert check_unsupported_number(_q(correct="Completeness"), "any passage") == []


def test_complexity_notation_passes_when_the_passage_shows_it() -> None:
    """O(2^m) contains a 2; the passage states it, so the question is fair."""
    passage = "The cost of m-way partitioning is O(2^m)."
    assert check_unsupported_number(_q(correct="O(2^m)"), passage) == []
