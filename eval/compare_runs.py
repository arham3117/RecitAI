"""Compare generation runs from their logs (spec §15 task 7 — prompt/model A/B).

A run's log holds everything needed: per-question outcomes, validator verdicts, attempt
counts and latencies. Parsing it keeps comparisons reproducible instead of ad-hoc shell,
and it works on runs that were never persisted (`--dry-run`).

    python eval/compare_runs.py before.txt after.txt --labels v1 v2
"""

import argparse
import re
import statistics as st
from dataclasses import dataclass, field
from pathlib import Path

_VALIDATOR = re.compile(r"validator\.checked.*?attempt=(\d+).*?failures=\[(.*?)\].*?passed=(\w+)")
_QUESTION = re.compile(r"generator\.question.*?attempts=(\d+).*?duration_ms=(\d+).*?ok=(\w+)")
_SUMMARY = re.compile(r"(\d+)/(\d+) questions persisted\s+validator pass rate (\d+)%\s+([\d.]+)s")
_DUPES = re.compile(r"rejected as duplicates: (\d+)")


@dataclass
class RunStats:
    label: str
    persisted: int = 0
    requested: int = 0
    duration_s: float = 0.0
    duplicates: int = 0
    chunks: int = 0
    validations: int = 0
    validator_passes: int = 0
    first_attempt_passes: int = 0
    latencies_ms: list[int] = field(default_factory=list)
    failures: dict[str, int] = field(default_factory=dict)

    @property
    def first_pass_rate(self) -> float:
        return self.first_attempt_passes / self.chunks if self.chunks else 0.0

    @property
    def validator_pass_rate(self) -> float:
        return self.validator_passes / self.validations if self.validations else 0.0

    @property
    def p50_s(self) -> float:
        return st.median(self.latencies_ms) / 1000 if self.latencies_ms else 0.0

    @property
    def p95_s(self) -> float:
        if not self.latencies_ms:
            return 0.0
        ordered = sorted(self.latencies_ms)
        return ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))] / 1000


def parse(path: Path, label: str) -> RunStats:
    stats = RunStats(label=label)
    for line in path.read_text(errors="replace").splitlines():
        if m := _VALIDATOR.search(line):
            stats.validations += 1
            passed = m.group(3) == "True"
            if passed:
                stats.validator_passes += 1
                if m.group(1) == "1":
                    stats.first_attempt_passes += 1
            for code in re.findall(r"'([A-Z_]+)'", m.group(2)):
                stats.failures[code] = stats.failures.get(code, 0) + 1
        if m := _QUESTION.search(line):
            stats.chunks += 1
            stats.latencies_ms.append(int(m.group(2)))
        if m := _SUMMARY.search(line):
            stats.persisted, stats.requested = int(m.group(1)), int(m.group(2))
            stats.duration_s = float(m.group(4))
        if m := _DUPES.search(line):
            stats.duplicates = int(m.group(1))
    return stats


def render(runs: list[RunStats]) -> str:
    rows: list[tuple[str, list[str]]] = [
        ("chunks attempted", [str(r.chunks) for r in runs]),
        ("validations (incl. retries)", [str(r.validations) for r in runs]),
        ("passed the validator", [str(r.validator_passes) for r in runs]),
        ("first-attempt passes", [f"{r.first_attempt_passes} ({r.first_pass_rate:.0%})" for r in runs]),
        ("persisted", [str(r.persisted) for r in runs]),
        ("rejected as duplicates", [str(r.duplicates) for r in runs]),
        ("p50 latency", [f"{r.p50_s:.1f}s" for r in runs]),
        ("p95 latency", [f"{r.p95_s:.1f}s" for r in runs]),
        ("total duration", [f"{r.duration_s:.0f}s" for r in runs]),
    ]
    codes = sorted({c for r in runs for c in r.failures})
    for code in codes:
        rows.append((f"  rejected: {code}", [str(r.failures.get(code, 0)) for r in runs]))

    width = max(len(name) for name, _ in rows) + 2
    col = max(14, max(len(r.label) for r in runs) + 2)
    out = [" " * width + "".join(f"{r.label:>{col}}" for r in runs)]
    out.append("-" * (width + col * len(runs)))
    for name, values in rows:
        out.append(f"{name:<{width}}" + "".join(f"{v:>{col}}" for v in values))
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+", type=Path)
    ap.add_argument("--labels", nargs="*", default=None)
    args = ap.parse_args()
    labels = args.labels or [p.stem for p in args.logs]
    if len(labels) != len(args.logs):
        raise SystemExit("need one label per log")
    print(render([parse(p, label) for p, label in zip(args.logs, labels, strict=True)]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
