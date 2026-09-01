"""Prompt loader (spec §11 task 1, §6).

Prompts live in `recitai/prompts/*.md` and are never inlined in Python (§0.3). Each file
holds a `SYSTEM:` block and a `USER:` block; the version is the filename suffix and is
recorded against every question so a quality change can be traced to the prompt that
caused it (§6).
"""

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    system: str
    user_template: str

    def placeholders(self) -> set[str]:
        return set(_PLACEHOLDER.findall(self.user_template))

    def render(self, **values: object) -> str:
        """Fill the user template.

        Missing placeholders raise rather than rendering the literal `{name}` into the
        prompt, where it would read as instruction text to the model.
        """
        missing = self.placeholders() - set(values)
        if missing:
            raise KeyError(f"{self.name}: missing placeholders {sorted(missing)}")
        out = self.user_template
        for key, value in values.items():
            out = out.replace(f"{{{key}}}", str(value))
        return out


@cache
def load(name: str) -> Prompt:
    """Load `prompts/{name}.md`. Cached; prompts do not change at runtime."""
    path = PROMPT_DIR / f"{name}.md"
    if not path.exists():
        available = ", ".join(sorted(p.stem for p in PROMPT_DIR.glob("*.md")))
        raise FileNotFoundError(f"no prompt '{name}' in {PROMPT_DIR} (have: {available})")

    text = path.read_text(encoding="utf-8")
    if "SYSTEM:" not in text or "USER:" not in text:
        raise ValueError(f"{path.name}: expected both a 'SYSTEM:' and a 'USER:' block")

    system_part, user_part = text.split("USER:", 1)
    system = system_part.split("SYSTEM:", 1)[1].strip()
    version = name.rsplit("_v", 1)[-1] if "_v" in name else "1"
    return Prompt(name=name, version=f"v{version}", system=system, user_template=user_part.strip())
