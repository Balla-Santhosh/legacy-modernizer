"""Migration agent (slide 7, step 3).

A ReAct-style loop with a fixed tool order:
    Act      - generate the migrated file from source + retrieved repo context
    Observe  - compile, run differential tests, run analyzers
    Reflect  - feed the tool observations back and ask for a repaired file
until the file compiles and passes its tests, or `max_repairs` is spent.

Every step's observation is kept in the trace; the optimizer reads the traces
to build textual gradients for the system prompt.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .config import Settings
from .index import CodeIndex
from .llm import LLM, extract_code
from .prompts import FENCE, LANG_NAME, REPAIR_TEMPLATE, TASK_TEMPLATE
from .verify import CompileResult, LegacyBaseline, Verification, build_baseline, to_jsonable, verify


@dataclass
class Step:
    code: str
    verification: Verification


@dataclass
class MigrationResult:
    path: str
    steps: list[Step] = field(default_factory=list)

    @property
    def first(self) -> Verification:
        return self.steps[0].verification

    @property
    def best_index(self) -> int:
        """Attempt to keep: a repair can make things worse, so pick the best, not the last.
        Ranked by compiles, then test pass rate, then fewer warnings, then earliest."""
        def rank(i: int):
            v = self.steps[i].verification
            return (v.compile.ok, v.tests.rate if v.tests else 0.0, -v.warning_count, -i)
        return max(range(len(self.steps)), key=rank)

    @property
    def final(self) -> Verification:
        return self.steps[self.best_index].verification

    @property
    def code(self) -> str:
        return self.steps[self.best_index].code

    @property
    def succeeded(self) -> bool:
        v = self.final
        return v.compile.ok and v.tests is not None and v.tests.rate == 1.0

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "succeeded": self.succeeded,
            "repairs": len(self.steps) - 1,
            "kept_attempt": self.best_index,
            "first": self.first.summary(),
            "final": self.final.summary(),
            "steps": [to_jsonable(s.verification) for s in self.steps],
        }


def _done(v: Verification) -> bool:
    return v.compile.ok and v.tests is not None and v.tests.rate == 1.0


class MigrationAgent:
    def __init__(self, llm: LLM, settings: Settings, index: CodeIndex | None = None):
        self.llm = llm
        self.s = settings
        self.index = index
        self._baselines: dict[Path, LegacyBaseline] = {}

    def baseline(self, src: Path) -> LegacyBaseline:
        src = src.resolve()
        if src not in self._baselines:
            self._baselines[src] = build_baseline(src, self.s.work_dir / src.stem / "legacy", self.s)
        return self._baselines[src]

    def _task(self, src: Path, rel: str) -> str:
        source = src.read_text(errors="replace")
        ctx = self.index.context_for(source, rel, self.s.source_lang, self.s.retrieval_k) if self.index else []
        return TASK_TEMPLATE.format(
            src_lang=LANG_NAME[self.s.source_lang], tgt_lang=LANG_NAME[self.s.target_lang],
            path=rel, src_fence=FENCE[self.s.source_lang], tgt_fence=FENCE[self.s.target_lang],
            source=source, context="\n\n".join(ctx) if ctx else "(none)")

    def migrate(self, src: Path, system_prompt: str, rel: str | None = None,
                max_repairs: int | None = None, tag: str = "run") -> MigrationResult:
        src = Path(src)
        rel = rel or src.name
        repairs = self.s.max_repairs if max_repairs is None else max_repairs
        base = self.baseline(src)
        work = self.s.work_dir / src.stem / tag

        messages = [{"role": "user", "content": self._task(src, rel)}]
        result = MigrationResult(rel)
        for i in range(repairs + 1):
            reply = self.llm.complete(system_prompt, messages)
            code = extract_code(reply)
            if not code.strip():
                v = Verification(CompileResult(False, 1, 0, "The reply contained no code. Return the complete "
                                               "program in one fenced code block."))
            else:
                v = verify(code, base, work / f"step{i}", self.s)
            result.steps.append(Step(code, v))
            if _done(v):
                break
            messages += [
                {"role": "assistant", "content": reply},
                {"role": "user", "content": REPAIR_TEMPLATE.format(
                    feedback=v.feedback_text(), tgt_fence=FENCE[self.s.target_lang])},
            ]
        return result


def save_result(res: MigrationResult, out_dir: Path, target_ext: str = ".cpp") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(res.path).stem
    (out_dir / f"{stem}{target_ext}").write_text(res.code)
    (out_dir / f"{stem}.report.json").write_text(json.dumps(res.as_dict(), indent=2, default=str))
    return out_dir / f"{stem}{target_ext}"
