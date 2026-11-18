"""Prompt optimization loop (slide 8): feedback as gradient.

Each round:
  1. the agent migrates the TRAIN batch with the current system prompt
  2. compiler / test / analyzer output is collected as text
  3. a critic LLM turns that text into a textual gradient on the prompt
  4. an editor LLM applies the gradient, proposing `candidates` revised prompts
  5. candidates are scored with S on the VALIDATION batch; the best replaces the
     current prompt only if it beats the current prompt's validation score

This is a self-contained implementation of the TextGrad idea (Yuksekgonul et
al., 2024) specialised to code migration. External backends (the textgrad
package, DSPy MIPROv2/GEPA) can be added behind the same `evaluate()` metric.
During optimization the agent runs with `max_repairs=0` by default, so the
score measures the prompt's first-attempt quality rather than the repair loop.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .agent import MigrationAgent, MigrationResult
from .llm import LLM, extract_tag
from .prompts import CRITIC_SYSTEM, CRITIC_TEMPLATE, EDITOR_SYSTEM, EDITOR_TEMPLATE
from .scoring import BatchMetrics, score_batch


@dataclass
class Evaluation:
    prompt: str
    metrics: BatchMetrics
    results: list[MigrationResult]


@dataclass
class RoundLog:
    round: int
    current_val: float
    train: dict
    gradient: str
    candidates: list[dict] = field(default_factory=list)
    accepted: bool = False
    seconds: float = 0.0
    train_files: list[dict] = field(default_factory=list)


def file_report(r: MigrationResult) -> dict:
    """Compact per-file outcome stored in history.json, so a bad score explains itself."""
    v = r.final
    if not v.compile.ok:
        status, detail = "compile_failed", v.compile.diagnostics.strip()
    elif v.tests and v.tests.mismatches:
        status, detail = f"tests {v.tests.passed}/{v.tests.total}", v.tests.mismatches[0]
    else:
        status, detail = "ok", ""
    return {"file": r.path, "status": status, "warnings": v.warning_count, "detail": detail[:400]}


def critic_feedback(r: MigrationResult, idx: int) -> str:
    """Failures first and in full; analyzer findings condensed to a count (they matter least)."""
    v = r.final
    head = f"### file {idx}"
    if not v.compile.ok:
        return f"{head}: COMPILE FAILED\n{v.compile.diagnostics.strip()[:1500]}"
    parts = []
    if v.tests and v.tests.mismatches:
        parts.append(f"{head}: TESTS {v.tests.passed}/{v.tests.total} passed\n" + "\n".join(v.tests.mismatches))
    n_warn = v.warning_count
    if n_warn:
        checks = sorted({f.split("[")[-1].rstrip("]") for a in v.analysis for f in a.findings if "[" in f})
        parts.append(f"{head}: {n_warn} static-analysis findings ({', '.join(checks[:6])})")
    return "\n".join(parts) if parts else f"{head}: all checks passed"


def split_units(units: list[Path], val_fraction: float = 0.34) -> tuple[list[Path], list[Path]]:
    """Deterministic train/validation split (held-out files guard against overfitting)."""
    units = sorted(units)
    n_val = max(1, round(len(units) * val_fraction)) if len(units) > 1 else 0
    return units[n_val:] or units, units[:n_val] or units


class PromptOptimizer:
    def __init__(self, agent: MigrationAgent, critic: LLM, editor: LLM | None = None,
                 repairs_during_opt: int = 0, candidates: int = 2, max_prompt_words: int = 200, max_new_lines: int = 4):
        self.agent = agent
        self.critic = critic
        self.editor = editor or critic
        self.repairs = repairs_during_opt
        self.candidates = candidates
        self.max_words = max_prompt_words
        self.max_new = max_new_lines

    # ---- metric --------------------------------------------------------
    def evaluate(self, prompt: str, units: list[Path], tag: str) -> Evaluation:
        results = [self.agent.migrate(u, prompt, max_repairs=self.repairs, tag=tag) for u in units]
        return Evaluation(prompt, score_batch([r.final for r in results], self.agent.s.weights), results)

    # ---- textual gradient ---------------------------------------------
    def gradient(self, ev: Evaluation, nonce: str = "r1") -> str:
        # failing files first, so they are never crowded out by warnings
        order = sorted(ev.results, key=lambda r: (r.final.compile.ok, r.final.tests.rate if r.final.tests else 0))
        fb = [critic_feedback(r, i + 1) for i, r in enumerate(order)]
        reply = self.critic.complete(CRITIC_SYSTEM, [{"role": "user", "content": CRITIC_TEMPLATE.format(
            nonce=nonce, prompt=ev.prompt, metrics=json.dumps(ev.metrics.as_dict(), indent=1),
            feedback="\n\n".join(fb))}])
        return extract_tag(reply, "gradient") or reply.strip()

    def apply(self, prompt: str, grad: str, history: list[RoundLog], nonce: str = "r1c0") -> str | None:
        hist = "\n".join(f"round {h.round}: val S={h.current_val:.3f}, accepted={h.accepted}"
                         for h in history[-5:]) or "(none)"
        reply = self.editor.complete(EDITOR_SYSTEM.format(max_words=self.max_words, max_new=self.max_new,
                                                          nonce=nonce), [{
            "role": "user", "content": EDITOR_TEMPLATE.format(prompt=prompt, gradient=grad, history=hist)}])
        new = extract_tag(reply, "prompt")
        return new if new and new.strip() != prompt.strip() else None

    # ---- loop -----------------------------------------------------------
    def run(self, seed_prompt: str, train: list[Path], val: list[Path], rounds: int,
            out_dir: Path, log=print) -> tuple[str, list[RoundLog]]:
        out_dir.mkdir(parents=True, exist_ok=True)
        current = seed_prompt
        cur_val = self.evaluate(current, val, "r0_val")
        log(f"[round 0] seed prompt  val S={cur_val.metrics.score:.3f}  "
            f"compile={cur_val.metrics.compile_pass:.2f} tests={cur_val.metrics.test_pass:.2f}")
        history: list[RoundLog] = []
        curve = [{"round": 0, "val": cur_val.metrics.as_dict(),
                  "files": [file_report(x) for x in cur_val.results]}]

        for r in range(1, rounds + 1):
            t0 = time.time()
            tr = self.evaluate(current, train, f"r{r}_train")
            grad = self.gradient(tr, nonce=f"r{r}")
            rl = RoundLog(r, cur_val.metrics.score, tr.metrics.as_dict(), grad)
            rl.train_files = [file_report(x) for x in tr.results]
            best: Evaluation | None = None
            for c in range(self.candidates):
                cand = self.apply(current, grad, history, nonce=f"r{r}c{c}")
                if cand is None:
                    continue
                ev = self.evaluate(cand, val, f"r{r}_c{c}_val")
                rl.candidates.append({"prompt": cand, "val": ev.metrics.as_dict(),
                                      "files": [file_report(x) for x in ev.results]})
                if best is None or ev.metrics.score > best.metrics.score:
                    best = ev
            if best is not None and best.metrics.score > cur_val.metrics.score:
                current, cur_val, rl.accepted = best.prompt, best, True
            rl.seconds = round(time.time() - t0, 1)
            history.append(rl)
            curve.append({"round": r, "val": cur_val.metrics.as_dict()})
            log(f"[round {r}] train S={tr.metrics.score:.3f}  best candidate S="
                f"{best.metrics.score if best else float('nan'):.3f}  "
                f"{'ACCEPTED' if rl.accepted else 'kept current'}  val S={cur_val.metrics.score:.3f}")

            self._save(out_dir, seed_prompt, current, curve, history)
        self._save(out_dir, seed_prompt, current, curve, history)
        return current, history

    @staticmethod
    def _save(out_dir: Path, seed: str, best: str, curve: list, history: list[RoundLog]) -> None:
        (out_dir / "best_prompt.txt").write_text(best)
        (out_dir / "history.json").write_text(json.dumps(
            {"seed_prompt": seed, "best_prompt": best, "curve": curve,
             "rounds": [rl.__dict__ for rl in history]}, indent=2, default=str))
