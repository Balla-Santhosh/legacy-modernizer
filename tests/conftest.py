from pathlib import Path

import pytest

from legacy_modernizer.config import Settings

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "legacy_c"
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def settings(tmp_path) -> Settings:
    s = Settings(llm="scripted", timing_repeats=1)
    s.work_dir = tmp_path / "work"
    s.index_dir = tmp_path / "index"
    return s


def good(stem: str) -> str:
    return (FIXTURES / f"{stem}_good.cpp").read_text()


def fenced(code: str) -> str:
    return f"Here is the migration.\n```cpp\n{code}```\n"
