"""Verification stage (slide 7, step 4): compile, differential tests, speedup, static analysis.

Functional equivalence is checked differentially: the legacy program and the
migrated program are run on the same test cases and their stdout and exit
codes must match (slide 11, "semantic drift" mitigation).

Test cases live next to the source as `<stem>.tests.json`:
    {"cases": [{"args": ["3", "4"], "stdin": ""}, ...]}
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import Settings

_DIAG = re.compile(r"^(?P<file>[^:\n]+):(?P<line>\d+):(?:(?P<col>\d+):)?\s*(?P<sev>error|warning|fatal error)[: ]",
                   re.MULTILINE)


@dataclass
class CompileResult:
    ok: bool
    errors: int
    warnings: int
    diagnostics: str
    binary: Path | None = None


@dataclass
class CaseRun:
    stdout: str
    returncode: int
    seconds: float
    timed_out: bool = False


@dataclass
class TestResult:
    passed: int
    total: int
    mismatches: list[str] = field(default_factory=list)

    @property
    def rate(self) -> float:
        return self.passed / self.total if self.total else 0.0


@dataclass
class AnalysisResult:
    tool: str
    findings: list[str]
    available: bool = True


@dataclass
class Verification:
    compile: CompileResult
    tests: TestResult | None = None
    speedup: float | None = None
    analysis: list[AnalysisResult] = field(default_factory=list)

    @property
    def warning_count(self) -> int:
        return self.compile.warnings + sum(len(a.findings) for a in self.analysis)

    def feedback_text(self, max_chars: int = 4000) -> str:
        """Textual feedback for the agent and the prompt critic (the 'textual gradient' input)."""
        parts = []
        if not self.compile.ok:
            parts.append("COMPILE FAILED:\n" + self.compile.diagnostics.strip())
        elif self.compile.diagnostics.strip():
            parts.append("COMPILER WARNINGS:\n" + self.compile.diagnostics.strip())
        if self.tests is not None and self.tests.mismatches:
            parts.append(f"TESTS {self.tests.passed}/{self.tests.total} PASSED. MISMATCHES:\n"
                         + "\n".join(self.tests.mismatches))
        for a in self.analysis:
            if a.findings:
                parts.append(f"{a.tool.upper()} FINDINGS:\n" + "\n".join(a.findings))
        text = "\n\n".join(parts) or "All checks passed."
        return text if len(text) <= max_chars else text[:max_chars] + "\n...[truncated]"

    def summary(self) -> dict:
        return {
            "compile_ok": self.compile.ok,
            "compile_errors": self.compile.errors,
            "tests_passed": self.tests.passed if self.tests else None,
            "tests_total": self.tests.total if self.tests else None,
            "speedup": self.speedup,
            "warnings": self.warning_count,
        }


# --------------------------------------------------------------------------- compile
def compile_program(src: Path, out: Path, lang: str, s: Settings) -> CompileResult:
    if lang == "c":
        cmd = [s.cc, f"-std={s.c_std}", "-O2", "-Wall", "-Wextra", str(src), "-o", str(out), "-lm"]
    elif lang == "cpp":
        cmd = [s.cxx, f"-std={s.cxx_std}", "-O2", "-Wall", "-Wextra", str(src), "-o", str(out)]
    else:
        raise ValueError(f"no compiler for {lang}")
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    diag = p.stderr.replace(str(src.parent) + "/", "")
    sevs = [m.group("sev") for m in _DIAG.finditer(p.stderr)]
    errors = sum(1 for x in sevs if "error" in x)
    if p.returncode and errors == 0:
        errors = 1  # e.g. linker errors ("undefined reference to main") have no file:line prefix
    return CompileResult(ok=p.returncode == 0, errors=errors if p.returncode else 0,
                         warnings=sum(1 for x in sevs if x == "warning"), diagnostics=diag,
                         binary=out if p.returncode == 0 else None)


# --------------------------------------------------------------------------- run / tests
def load_cases(src: Path) -> list[dict]:
    spec = src.with_name(src.stem + ".tests.json")
    if spec.exists():
        return json.loads(spec.read_text())["cases"]
    return [{"args": [], "stdin": ""}]


def run_case(cmd: list[str], case: dict, timeout: float) -> CaseRun:
    t0 = time.perf_counter()
    try:
        p = subprocess.run(cmd + [str(a) for a in case.get("args", [])], input=case.get("stdin", ""),
                           capture_output=True, text=True, timeout=timeout)
        return CaseRun(p.stdout, p.returncode, time.perf_counter() - t0)
    except subprocess.TimeoutExpired:
        return CaseRun("", -1, timeout, timed_out=True)


def timed(cmd: list[str], cases: list[dict], s: Settings) -> list[CaseRun]:
    """Run every case `timing_repeats` times; keep output of the first run and the fastest time."""
    out = []
    for case in cases:
        runs = [run_case(cmd, case, s.run_timeout_s)]
        if not runs[0].timed_out:  # don't re-run a program that hangs
            runs += [run_case(cmd, case, s.run_timeout_s) for _ in range(max(1, s.timing_repeats) - 1)]
        best = min(r.seconds for r in runs)
        out.append(CaseRun(runs[0].stdout, runs[0].returncode, best, runs[0].timed_out))
    return out


def differential(legacy: list[CaseRun], migrated: list[CaseRun], cases: list[dict],
                 max_report: int = 5) -> TestResult:
    passed, mism = 0, []
    for i, (a, b, c) in enumerate(zip(legacy, migrated, cases)):
        if not b.timed_out and a.stdout == b.stdout and a.returncode == b.returncode:
            passed += 1
        elif len(mism) < max_report:
            why = "timed out" if b.timed_out else (
                f"exit {b.returncode} != expected {a.returncode}" if a.returncode != b.returncode
                else "stdout differs")
            mism.append(f"case {i} args={c.get('args', [])} stdin={c.get('stdin', '')[:60]!r}: {why}\n"
                        f"  expected: {a.stdout[:200]!r}\n  got:      {b.stdout[:200]!r}")
    return TestResult(passed, len(cases), mism)


def speedup(legacy: list[CaseRun], migrated: list[CaseRun], min_s: float = 0.02) -> float | None:
    """Legacy time / migrated time over cases long enough to measure.

    Cases where the legacy run takes < min_s are dominated by process start-up and are ignored;
    returns None when no case qualifies (speedup not measured for this file).
    """
    pairs = [(a, b) for a, b in zip(legacy, migrated) if a.seconds >= min_s and not b.timed_out]
    ta = sum(a.seconds for a, _ in pairs)
    tb = sum(b.seconds for _, b in pairs)
    return ta / tb if pairs and tb > 0 else None


# --------------------------------------------------------------------------- static analysis
CLANG_TIDY_CHECKS = ",".join([
    "-*", "bugprone-*", "cppcoreguidelines-no-malloc", "cppcoreguidelines-owning-memory",
    "modernize-*", "-modernize-use-trailing-return-type", "performance-*",
    "clang-analyzer-*", "cert-*", "-cert-err33-c",
])


def clang_tidy(src: Path, s: Settings) -> AnalysisResult:
    if not shutil.which("clang-tidy"):
        return AnalysisResult("clang-tidy", [], available=False)
    p = subprocess.run(["clang-tidy", str(src), f"-checks={CLANG_TIDY_CHECKS}", "--quiet", "--",
                        f"-std={s.cxx_std}"], capture_output=True, text=True, timeout=180)
    findings = [ln.replace(str(src.parent) + "/", "") for ln in p.stdout.splitlines()
                if re.search(r":\d+:\d+: (warning|error):", ln)]
    return AnalysisResult("clang-tidy", findings)


def cppcheck(src: Path, s: Settings) -> AnalysisResult:
    if not shutil.which("cppcheck"):
        return AnalysisResult("cppcheck", [], available=False)
    p = subprocess.run(["cppcheck", "--enable=warning,performance,portability", "--quiet",
                        f"--std={s.cxx_std}", "--template={file}:{line}: {severity}: {message} [{id}]",
                        str(src)], capture_output=True, text=True, timeout=180)
    return AnalysisResult("cppcheck", [ln.replace(str(src.parent) + "/", "")
                                       for ln in p.stderr.splitlines() if ln.strip()])


def bandit(src: Path, s: Settings) -> AnalysisResult:
    if not shutil.which("bandit"):
        return AnalysisResult("bandit", [], available=False)
    p = subprocess.run(["bandit", "-q", "-f", "json", str(src)], capture_output=True, text=True, timeout=180)
    try:
        res = json.loads(p.stdout or "{}").get("results", [])
    except json.JSONDecodeError:
        res = []
    return AnalysisResult("bandit", [f"line {r['line_number']}: {r['issue_text']} [{r['test_id']}]"
                                     for r in res])


ANALYZERS = {"cpp": [clang_tidy, cppcheck], "python": [bandit]}


# --------------------------------------------------------------------------- legacy baseline
@dataclass
class LegacyBaseline:
    src: Path
    cases: list[dict]
    runs: list[CaseRun]
    compile: CompileResult


def build_baseline(src: Path, work: Path, s: Settings) -> LegacyBaseline:
    work.mkdir(parents=True, exist_ok=True)
    cr = compile_program(src, work / f"{src.stem}.legacy", s.source_lang, s)
    if not cr.ok:
        raise RuntimeError(f"legacy build of {src} failed:\n{cr.diagnostics}")
    cases = load_cases(src)
    return LegacyBaseline(src, cases, timed([str(cr.binary)], cases, s), cr)


def verify(candidate: str, baseline: LegacyBaseline, work: Path, s: Settings,
           run_analyzers: bool = True) -> Verification:
    work.mkdir(parents=True, exist_ok=True)
    ext = {"cpp": ".cpp", "python": ".py"}[s.target_lang]
    src = (work / f"{baseline.src.stem}{ext}").resolve()
    src.write_text(candidate)
    cr = compile_program(src, work / f"{baseline.src.stem}.migrated", s.target_lang, s)
    v = Verification(cr)
    if cr.ok:
        runs = timed([str(cr.binary)], baseline.cases, s)
        v.tests = differential(baseline.runs, runs, baseline.cases)
        v.speedup = speedup(baseline.runs, runs, s.speedup_min_s)
        if run_analyzers:
            v.analysis = [a(src, s) for a in ANALYZERS[s.target_lang]]
    return v


def to_jsonable(v: Verification) -> dict:
    d = asdict(v)
    d["compile"]["binary"] = str(v.compile.binary) if v.compile.binary else None
    return d
