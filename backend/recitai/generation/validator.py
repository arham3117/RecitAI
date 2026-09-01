"""The validator (spec §5).

Small local models fail at MCQ generation in predictable, mechanically detectable ways.
This is the quality mechanism — never stubbed, never skipped (§0.2).

Deterministic checks run first because they are free; the LLM judge runs only on
survivors, batched into one call per question (§5.2).
"""

import re
import time

import numpy as np
import structlog

from recitai.config import settings
from recitai.constants import (
    BANNED_PHRASES,
    MAX_CORRECT_LENGTH_RATIO,
    MAX_OPTION_SIMILARITY,
)
from recitai.generation.prompts import load
from recitai.generation.schemas import (
    GeneratedQuestion,
    JudgeVerdict,
    ValidatorReport,
)
from recitai.llm.base import LLMClient

log = structlog.get_logger(__name__)

#: Failure codes, exactly as §5.1 names them.
SCHEMA = "SCHEMA"
LENGTH_BIAS = "LENGTH_BIAS"
OPTION_OVERLAP = "OPTION_OVERLAP"
BANNED_PHRASE = "BANNED_PHRASE"
NEGATION = "NEGATION"
LEAKAGE = "LEAKAGE"
EMPTY_FIELD = "EMPTY_FIELD"

#: §5.1's negation check. Word-boundary matched: a naive substring scan fires on
#: "cannot", "note", "notation" and "notably", which technical prose is full of (I-009).
_NEGATION_WORDS = re.compile(r"\b(not|except|least)\b", re.I)

#: Words too common to make a phrase distinctive; a leakage match on these is noise.
# fmt: off
_STOPWORDS = frozenset(
    {
        "a", "an", "the", "of", "to", "in", "on", "for", "and", "or",
        "is", "are", "was", "were", "be", "been", "by", "with", "as", "at",
        "from", "that", "this", "it", "its", "which", "each", "any", "all",
        "more", "most", "such", "into", "than", "then", "when", "where", "while",
    }
)
# fmt: on

#: §5.1 leakage: the correct option's longest noun-ish phrase of at least this many words.
MIN_LEAKAGE_PHRASE_WORDS = 3


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def check_empty(question: GeneratedQuestion) -> list[str]:
    if not question.stem.strip() or not question.explanation.strip():
        return [EMPTY_FIELD]
    for option in question.options:
        if not option.text.strip():
            return [EMPTY_FIELD]
        if not option.is_correct and not (option.why_wrong or "").strip():
            # §5.1 schema check: every distractor must carry a rationale, because the
            # wrong-answer moment is the product (§4.5).
            return [SCHEMA]
    return []


def check_length_bias(question: GeneratedQuestion) -> list[str]:
    """§5.1's highest-yield check.

    Small models pad the correct answer with qualifying clauses, making the quiz
    answerable without reading the material. Measured in characters: that is what a
    student's eye registers as "the long one", and it needs no tokenizer (I-007).
    """
    distractors = question.distractors
    if not distractors:
        return [SCHEMA]
    mean_length = sum(len(d.text) for d in distractors) / len(distractors)
    if mean_length == 0:
        return [EMPTY_FIELD]
    if len(question.correct.text) > MAX_CORRECT_LENGTH_RATIO * mean_length:
        return [LENGTH_BIAS]
    return []


def check_banned_phrases(question: GeneratedQuestion) -> list[str]:
    for option in question.options:
        normalised = option.text.strip().lower().rstrip(".")
        if any(phrase in normalised for phrase in BANNED_PHRASES):
            return [BANNED_PHRASE]
    return []


def check_negation(question: GeneratedQuestion) -> list[str]:
    if question.difficulty == "analysis":
        return []
    if _NEGATION_WORDS.search(question.stem):
        return [NEGATION]
    return []


def check_leakage(question: GeneratedQuestion) -> list[str]:
    """The correct option's longest distinctive phrase appearing verbatim in the stem."""
    stem_words = _words(question.stem)
    option_words = _words(question.correct.text)
    if len(option_words) < MIN_LEAKAGE_PHRASE_WORDS or not stem_words:
        return []

    stem_text = " ".join(stem_words)
    for size in range(len(option_words), MIN_LEAKAGE_PHRASE_WORDS - 1, -1):
        for start in range(len(option_words) - size + 1):
            phrase = option_words[start : start + size]
            if all(w in _STOPWORDS for w in phrase):
                continue
            if " ".join(phrase) in stem_text:
                return [LEAKAGE]
    return []


async def check_option_overlap(question: GeneratedQuestion, client: LLMClient) -> list[str]:
    """No two options may be near-duplicates (§5.1).

    Costs four embeddings per question; batched in one call (I-012).
    """
    vectors = await client.embed([o.text for o in question.options])
    matrix = np.array(vectors, dtype=float)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    unit = matrix / norms
    similarity = unit @ unit.T
    np.fill_diagonal(similarity, 0.0)
    if float(similarity.max()) >= MAX_OPTION_SIMILARITY:
        return [OPTION_OVERLAP]
    return []


async def run_deterministic(
    question: GeneratedQuestion, client: LLMClient | None = None
) -> list[str]:
    """§5.1. All checks run; the report lists every failure, not just the first."""
    failures: list[str] = []
    failures += check_empty(question)
    failures += check_length_bias(question)
    failures += check_banned_phrases(question)
    failures += check_negation(question)
    failures += check_leakage(question)
    if client is not None and not failures:
        # Only worth the embedding calls if the free checks already passed.
        failures += await check_option_overlap(question, client)
    return failures


async def run_judge(
    question: GeneratedQuestion, chunk_text: str, client: LLMClient
) -> JudgeVerdict:
    """§5.2 — grounded, unique, plausible, in one call at temperature 0."""
    prompt = load(settings.judge_prompt)
    by_id = {o.id: o.text for o in question.options}
    rendered = prompt.render(
        chunk_text=chunk_text,
        stem=question.stem,
        option_a=by_id.get("A", ""),
        option_b=by_id.get("B", ""),
        option_c=by_id.get("C", ""),
        option_d=by_id.get("D", ""),
        correct_id=question.correct.id,
    )
    raw = await client.complete(
        rendered,
        system=prompt.system,
        temperature=0.0,
        schema=JudgeVerdict.model_json_schema(),
    )
    return JudgeVerdict.model_validate_json(raw)


async def validate(
    question: GeneratedQuestion,
    chunk_text: str,
    client: LLMClient,
    *,
    attempt: int = 1,
    run_judge_checks: bool = True,
) -> ValidatorReport:
    """Full validation: deterministic first, judge only on survivors (§5)."""
    started = time.perf_counter()
    failures = await run_deterministic(question, client)

    judge_results: dict[str, bool] = {}
    if not failures and run_judge_checks:
        verdict = await run_judge(question, chunk_text, client)
        judge_results = {
            "grounded": verdict.grounded,
            "unique": verdict.unique,
            "plausible": verdict.plausible,
        }
        failures += [name.upper() for name, ok in judge_results.items() if not ok]

    report = ValidatorReport(
        passed=not failures,
        attempts=attempt,
        deterministic_failures=failures,
        judge_results=judge_results,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    log.info(
        "validator.checked",
        passed=report.passed,
        failures=failures,
        attempt=attempt,
        duration_ms=report.duration_ms,
    )
    return report
