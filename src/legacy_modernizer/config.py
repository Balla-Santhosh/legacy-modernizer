"""Central settings. Everything has a sensible default so the CLI works with few flags."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ScoreWeights:
    """Weights of the composite score S (slide 8).

    S = w1*compile_pass + w2*test_pass + w3*speedup_term - w4*warning_term
    """

    compile_pass: float = 0.4
    test_pass: float = 0.4
    speedup: float = 0.1
    warnings: float = 0.1


@dataclass
class Settings:
    # Language pair. Only c -> cpp is wired end to end in v0.1.
    source_lang: str = "c"
    target_lang: str = "cpp"

    # LLM, as "<provider>:<model>", e.g. "openai:gpt-4o-mini", "anthropic:claude-sonnet-4-5",
    # "ollama:qwen2.5-coder:7b". "scripted" is the offline test double.
    llm: str = "openai:gpt-4o-mini"
    temperature: float = 0.2

    # Agent
    max_repairs: int = 2          # compile/test repair turns after the first attempt
    retrieval_k: int = 6          # chunks of repo context per file

    # Toolchain
    cc: str = "gcc"
    cxx: str = "g++"
    c_std: str = "c99"
    cxx_std: str = "c++17"
    run_timeout_s: float = 10.0
    timing_repeats: int = 3
    speedup_min_s: float = 0.02   # ignore cases faster than this when measuring speedup

    # Index
    index_dir: Path = Path(".modernizer/index")
    work_dir: Path = Path(".modernizer/work")

    weights: ScoreWeights = field(default_factory=ScoreWeights)
