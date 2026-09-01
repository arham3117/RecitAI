"""`make eval` — the metrics report (spec §15 VERIFY).

Replaces "seems good" with numbers. Every section names the spec task it answers, so a
claim in the README can be traced to the measurement behind it.
"""

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import coverage_eval  # noqa: E402
import generation_eval  # noqa: E402
import retrieval_eval  # noqa: E402


async def main() -> int:
    print("=" * 72)
    print("RecitAI — evaluation report")
    print(f"generated {datetime.now(UTC).isoformat(timespec='seconds')}")
    print("=" * 72)

    failures: list[str] = []

    print("\nCOVERAGE  (§15 task 5 — the number that proves the Path A design works)")
    try:
        coverage = await coverage_eval.evaluate()
        print(coverage.report())
        if coverage.topic_coverage < 0.90:
            failures.append(f"topic coverage {coverage.topic_coverage:.0%} is below the 90% target")
    except SystemExit as exc:
        print(f"  skipped: {exc}")

    print("\nRETRIEVAL  (§15 task 2 — Path B only; generation never uses it)")
    try:
        retrieval = await retrieval_eval.evaluate()
        print(retrieval.report())
        if retrieval.queries and retrieval.recall_at_k < 0.80:
            failures.append(f"recall@5 {retrieval.recall_at_k:.0%} is below the 80% bar")
    except SystemExit as exc:
        print(f"  skipped: {exc}")

    print("\nGENERATION  (§15 tasks 3, 4, 6)")
    try:
        generation = await generation_eval.evaluate()
        print(generation.report())
        if generation.with_citations != generation.questions:
            failures.append("invariant I1: some persisted questions carry no citations")
        if generation.pages_in_range != generation.questions:
            failures.append("invariant I1: some cited pages fall outside their chunk or document")
    except SystemExit as exc:
        print(f"  skipped: {exc}")

    print("\n" + "=" * 72)
    if failures:
        print("FAILURES")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("All measured thresholds met.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
