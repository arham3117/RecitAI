# Evaluation

Spec §15. Every number here comes from `make eval` or from a controlled run recorded in
`plan/PROGRESS.md`; nothing is asserted from impression.

Corpus: five `.pptx` lecture decks on distributed database systems, 227 slides, 35 chunks.
Its measured limits are recorded as [I-016] and [I-018] — no speaker notes, and a ceiling
of ~34 generatable chunks.

## Coverage — the number that proves the design (§15 task 5)

| Metric | Result | Target |
|---|---|---|
| **Topic coverage over 5 consecutive quizzes** | **100%** (5/5) | ≥90% |
| Chunk coverage | 89% (31/35) | — |
| Topics per quiz | 5, 5, 5, 5, 5 | — |

This is what the two-path design (ADR 0001) exists to guarantee. A similarity-based
pipeline cannot: embedding a chapter name and taking the top-k returns the chunks that
*say* that name most — the introduction — so the same passages win every time and the rest
of the material is never asked about, with nothing in the output revealing it.

Measured across *consecutive* quizzes, with each quiz's usage written back so the
sampler's freshness term sees it. Measuring five independent quizzes would flatter the
result.

## Retrieval — Path B only (§15 task 2)

| Metric | Result |
|---|---|
| recall@5 | **35/35 (1.00)** |
| MRR | **0.911** |

Over **35 hand-written query/source pairs** in `eval/golden_set.jsonl`, keyed on section
path so they survive a re-ingest. §15 task 1 asks for 50; this corpus holds 35 chunks, so
35 pairs give **one query per chunk** — full coverage of the material. Writing 50 would
mean two or three queries against some chunks and none against others, which measures
less, not more. **These numbers do not describe quiz generation**, which never
runs a similarity search. They describe explanations, follow-ups, and scope resolution.

## Generation (§15 tasks 3, 4)

Generation quality varies between runs — the model is stochastic and the corpus is small,
so these are the figures from the run currently in the database rather than constants. Use
`make eval` for the live numbers and `eval/compare_runs.py` to compare two runs properly.

| Metric | Result |
|---|---|
| Validator pass rate | ~50% |
| Questions judged student-ready on read-through | ~80% (17–18 of 22 in the first full read) |
| Explanations supported by their cited chunk | 83%, mean lexical overlap 48% |

**Invariant I1 holds absolutely:**

| Check | Result |
|---|---|
| Questions carrying citations | **100%** |
| Citations resolvable to a live chunk | **100%** |
| Cited page inside both its chunk and its document | **100%** |

These three are asserted by `make eval` and fail the report if they ever drop below 100%,
which is the point: I1 is not a target, it is a precondition for persisting anything.

The spec's target of ≥40 student-ready questions from 50 is **not reachable on this
corpus** and never was: 34 eligible chunks exist ([I-018]). The *rate* meets the implied
80% bar; the absolute count cannot. The sampler reports the shortfall rather than silently
returning short.

## Latency (§15 task 6)

| Measurement | p50 | p95 |
|---|---|---|
| Question generation (llama3.1 8B q5, M5 Pro) | 17–19 s | ~25 s |
| Explanation, time to first token | **0.93 s** | — |
| Embedding share of generation | 0.52% | — |
| Ingestion, 227 slides → 35 chunks | 2.5 s total | — |

The embedding share was measured rather than assumed ([I-012]): option and stem embeddings
cost 87 ms against a ~17 s generation, so batching them would save 0.4% and is not worth
coupling the validator to dedup.

## A/B results (§15 task 7)

All comparisons below are seeded — same seed, same corpus, one variable. Before generation
was seeded, `--seed` drove only the sampler and every comparison mixed run-to-run noise
with signal; two runs with identical prompts differed 22 vs 18 persisted.

### Prompt versions

| | v1 | v2 |
|---|---|---|
| Persisted | **20** | 12 (−40%) |
| First-attempt passes | 41% | 21% |
| `UNIQUE` rejections | 3 | 18 |
| — whose reasoning affirms the marked answer | 0 | **3** |
| "primary/main" stems | 1 of 19 (5%) | **2 of 12 (17%)** |

**v2 was rejected.** The explicit prompt rule against "primary/main/most important"
questions made the pattern *more* frequent, and the sharpened judge over-fires — three of
its eighteen rejections state the marked answer is correct and then reject it.

### Models

| | llama3.1 8B q5 | qwen2.5 14B q4 |
|---|---|---|
| Persisted | 18 | 19 |
| First-attempt passes | 38% | **50%** |
| `UNIQUE` rejections | 4 | **1** |
| `LENGTH_BIAS` rejections | 9 | **4** |
| p50 / p95 latency | 18.9 s / 24.9 s | 21.3 s / **44.6 s** |
| The I-029 arithmetic case | wrong (8) | **wrong (48)** |

**8B retained** ([D-013]). 14B is genuinely better on quality signals but 36% slower for
one extra question, and does not fix the failure it was tried for — the correct answer is
32, and it states the right operands before multiplying by six.

### Deterministic checks vs the alternatives

The same two quality problems, attacked three ways:

| Approach | Cost | Result |
|---|---|---|
| Sharpen the prompt | −40% yield | Target pattern became *more* frequent |
| Escalate to a 14B model | +36% latency, 9 GB | Did not fix the failure |
| **Deterministic checks** | **~0** | **Both failure classes eliminated** |

`INVENTED_RANKING` removed the ranking construction entirely (1 of 19 stems → 0 of 17) at
a cost of two questions. `NUMERIC_UNSUPPORTED` rejects answers containing a number the
passage never states, at **zero** yield cost — 18 persisted either way — and catches
exactly the question that motivated it.

Where a failure is mechanically detectable, §5.1's free tier beat both instructing a
bigger model and instructing a smaller one. That is the spec's own ordering, and it held
twice.

## Reranking (§15 task 8)

`bge-reranker-base` is **not added**. §15 says to add it "only if retrieval eval justifies
it": recall@5 is 1.00 and MRR 0.920, so there is nothing for a reranker to improve. It
would add a model, latency, and a dependency to fix a problem that is not present.

## Honest limitations

- **The corpus is small** — 34 generatable chunks, so ~34–70 distinct questions before
  dedup and the sampler's freshness term work against each other ([I-018]).
- **No speaker notes** ([I-016]), so distractors are built from bullet text alone.
- **12% of slides are diagram-only** and are invisible to a text pipeline; OCR is deferred.
- **~9% of questions have two defensible answers** ([I-028]) where no superlative gives the
  construction away. The judge is the only thing that could catch those, and the measured
  attempt to sharpen it over-fired.
- **The groundedness audit uses lexical overlap**, which is a weak proxy for entailment. It
  catches an explanation about something the passage never mentions; it would not catch a
  fluent misreading.

[I-012]: ../plan/ISSUES.md
[I-016]: ../plan/ISSUES.md
[I-018]: ../plan/ISSUES.md
[I-028]: ../plan/ISSUES.md
[D-013]: ../plan/DECISIONS.md
