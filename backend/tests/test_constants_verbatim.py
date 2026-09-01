"""`constants.py` must stay byte-identical to spec §4.1.

Spec §0.1: stated constants are used verbatim because later phases depend on them, and
§0.2 forbids quietly lowering a threshold to make something pass. A comment saying so is
not enforcement — this is. If a constant genuinely needs to change, change it in the spec
and record the change in plan/DECISIONS.md, then this test tells you the two are back in
agreement.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SPEC = REPO / "plan" / "RECITAI_BUILD_SPEC.md"
CONSTANTS = REPO / "backend" / "recitai" / "constants.py"

START = "# ---- Chunking ----"
END = "FSRS_DESIRED_RETENTION = 0.9"


def _block(text: str) -> str:
    start = text.index(START)
    end = text.index(END, start) + len(END)
    return text[start:end]


def test_constants_match_spec_section_4_1() -> None:
    spec_block = _block(SPEC.read_text(encoding="utf-8"))
    module_block = _block(CONSTANTS.read_text(encoding="utf-8"))
    assert module_block == spec_block, (
        "constants.py has drifted from spec §4.1. Reconcile them and record the change "
        "in plan/DECISIONS.md — do not edit one to match the other silently."
    )


def test_spec_block_is_actually_populated() -> None:
    # Guards the guard: a bad slice that returns almost nothing would make the test above
    # pass vacuously.
    block = _block(CONSTANTS.read_text(encoding="utf-8"))
    assert len(re.findall(r"^[A-Z_]+ = ", block, re.M)) >= 20
