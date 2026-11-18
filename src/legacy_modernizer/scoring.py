"""Composite score S (slide 8) and per-batch metrics (slide 9).

    S = w1*compile_pass + w2*test_pass + w3*speedup_term - w4*warning_term

All terms are in [0, 1] (speedup_term in [-1, 1]) so the weights are interpretable:
  compile_pass  fraction of files that compile
  test_pass     mean differential test pass rate (0 for files that do not compile)
  speedup_term  mean clip(log2(speedup), -1, 1) over files that pass all tests
                (2x faster -> +1, same speed -> 0, 2x slower -> -1)
  warning_term  mean min(warnings / warning_cap, 1) over compiled files
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from .config import ScoreWeights
from .verify import Verification


@dataclass
class BatchMetrics:
    n: int
    compile_pass: float
    test_pass: float
    speedup_term: float
    warning_term: float
    mean_speedup: float | None
    mean_warnings: float
    score: float

    def as_dict(self) -> dict:
        return asdict(self)


def score_batch(results: list[Verification], w: ScoreWeights, warning_cap: int = 10) -> BatchMetrics:
    n = len(results)
    if n == 0:
        return BatchMetrics(0, 0, 0, 0, 0, None, 0, 0)
    compiled = [v for v in results if v.compile.ok]
    compile_pass = len(compiled) / n
    test_pass = sum(v.tests.rate for v in compiled if v.tests) / n

    fully = [v for v in compiled if v.tests and v.tests.rate == 1.0 and v.speedup]
    sp_terms = [max(-1.0, min(1.0, math.log2(v.speedup))) for v in fully]
    speedup_term = sum(sp_terms) / n
    mean_speedup = (math.exp(sum(math.log(v.speedup) for v in fully) / len(fully))) if fully else None

    warn = [min(v.warning_count / warning_cap, 1.0) for v in compiled]
    warning_term = sum(warn) / len(compiled) if compiled else 1.0
    mean_warnings = sum(v.warning_count for v in compiled) / len(compiled) if compiled else 0.0

    s = (w.compile_pass * compile_pass + w.test_pass * test_pass
         + w.speedup * speedup_term - w.warnings * warning_term)
    return BatchMetrics(n, compile_pass, test_pass, speedup_term, warning_term,
                        mean_speedup, mean_warnings, round(s, 4))
